"""Servicio de modelos con API compatible con OpenAI (subconjunto de /v1/chat/completions).

Decisiones: liveness (/healthz) distinto de readiness (/readyz, el modelo cargó); un semáforo
serializa el acceso a la GPU; tope de max_tokens y de tamaño de entrada; clave de API opcional.
Sin batching continuo: para producción real corresponde vLLM o TGI (ver docs/serving.md)."""
from __future__ import annotations

import hmac
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .backends import Backend, make_backend
from .metrics import Metrics

log = logging.getLogger("secmcp.serving")
MAX_TOKENS_CAP = int(os.environ.get("MAX_TOKENS_CAP", "512"))
MAX_INPUT_CHARS = int(os.environ.get("MAX_INPUT_CHARS", "16000"))


class Msg(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    model: str = "local"
    messages: list[Msg] = Field(min_length=1)
    max_tokens: int = 256
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


def create_app(backend: Backend | None = None, api_key: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # La carga del modelo corre en un hilo para no bloquear el puerto; /readyz lo refleja.
        threading.Thread(target=load, daemon=True).start()
        yield

    app = FastAPI(title="secmcp-serving", lifespan=lifespan)
    app.state.backend = backend
    app.state.metrics = Metrics()
    app.state.gpu_lock = threading.Semaphore(1)
    key = api_key if api_key is not None else os.environ.get("SERVE_API_KEY", "")

    def load() -> None:
        if app.state.backend is None:
            app.state.backend = make_backend()

    def auth(authorization: str = Header(default="")) -> None:
        if not key:
            return
        token = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(token, key):
            raise HTTPException(401, "no autorizado")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict:
        if app.state.backend is None:
            raise HTTPException(503, "modelo cargando")
        return {"status": "ready", **app.state.backend.info()}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        return app.state.metrics.prometheus()

    @app.get("/v1/info", dependencies=[Depends(auth)])
    def info() -> dict:
        if app.state.backend is None:
            raise HTTPException(503, "modelo cargando")
        return {**app.state.backend.info(), **app.state.metrics.snapshot()}

    @app.post("/v1/chat/completions", dependencies=[Depends(auth)])
    def chat(req: ChatRequest) -> dict:
        be = app.state.backend
        if be is None:
            raise HTTPException(503, "modelo cargando")
        if sum(len(m.content) for m in req.messages) > MAX_INPUT_CHARS:
            app.state.metrics.reject()
            raise HTTPException(413, "entrada demasiado larga")
        max_tokens = min(req.max_tokens, MAX_TOKENS_CAP)
        t0 = time.perf_counter()
        try:
            with app.state.gpu_lock:
                g = be.generate([m.model_dump() for m in req.messages], max_tokens, req.temperature)
        except Exception:
            log.exception("fallo de generación")
            app.state.metrics.error()
            raise HTTPException(500, "error de generación") from None
        dt = time.perf_counter() - t0
        app.state.metrics.record(dt, g.completion_tokens)
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion", "model": req.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": g.text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": g.prompt_tokens, "completion_tokens": g.completion_tokens,
                      "total_tokens": g.prompt_tokens + g.completion_tokens},
        }

    return app


def app_factory() -> FastAPI:
    return create_app()
