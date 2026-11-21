"""LLM intercambiable. ScriptedLLM para pruebas deterministas; HTTPLLM habla con el servicio de modelos."""
from __future__ import annotations

import json
import re
from typing import Protocol

import httpx


class LLM(Protocol):
    def complete(self, messages: list[dict]) -> str: ...


class ScriptedLLM:
    """Responde con un guion fijo. Simula un modelo que SÍ obedece la inyección o que se porta bien."""

    def __init__(self, script: list[str]):
        self.script = list(script)
        self.calls = 0

    def complete(self, messages: list[dict]) -> str:
        i = min(self.calls, len(self.script) - 1)
        self.calls += 1
        return self.script[i]


class HTTPLLM:
    """Cliente del endpoint /v1/chat/completions (compatible con OpenAI) de serving.app o de vLLM."""

    def __init__(self, base_url: str, model: str = "local", timeout: float = 120.0, max_tokens: int = 256):
        self.base_url, self.model, self.timeout, self.max_tokens = base_url.rstrip("/"), model, timeout, max_tokens

    def complete(self, messages: list[dict]) -> str:
        r = httpx.post(f"{self.base_url}/v1/chat/completions", timeout=self.timeout,
                       json={"model": self.model, "messages": messages, "max_tokens": self.max_tokens, "temperature": 0})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


_JSON = re.compile(r"\{.*\}", re.DOTALL)


def parse_action(text: str) -> dict | None:
    """Extrae {"tool":..., "args":{...}} o {"final":...}. Devuelve None si no hay JSON válido."""
    m = _JSON.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and ("tool" in obj or "final" in obj):
        return obj
    return None
