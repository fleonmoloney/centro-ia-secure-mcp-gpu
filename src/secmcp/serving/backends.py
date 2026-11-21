"""Backends de generación. MockBackend para CI y desarrollo; TransformersBackend para GPU."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Generation:
    text: str
    prompt_tokens: int
    completion_tokens: int


class Backend(Protocol):
    name: str
    def info(self) -> dict: ...
    def generate(self, messages: list[dict], max_tokens: int, temperature: float) -> Generation: ...


class MockBackend:
    """Determinista y sin dependencias. Responde terminar la tarea; sirve para probar el servicio."""
    name = "mock"

    def __init__(self, latency_s: float = 0.0):
        self.latency_s = latency_s

    def info(self) -> dict:
        return {"backend": "mock", "device": "cpu", "model": "mock"}

    def generate(self, messages, max_tokens, temperature):
        if self.latency_s:
            time.sleep(self.latency_s)
        last = messages[-1]["content"] if messages else ""
        text = '{"final": "mock: ' + last[:40].replace('"', "'").replace("\n", " ") + '"}'
        return Generation(text, sum(len(m["content"]) // 4 for m in messages), len(text) // 4)


class TransformersBackend:
    """Hugging Face transformers en GPU (fp16) o con cuantización de 4 bits (bitsandbytes).

    Variables: MODEL_ID (por defecto Qwen/Qwen2.5-1.5B-Instruct), QUANT=none|4bit.
    No está probado en este repositorio contra una GPU real salvo por el notebook de Colab."""
    name = "transformers"

    def __init__(self, model_id: str | None = None, quant: str | None = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.model_id = model_id or os.environ.get("MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct")
        quant = quant or os.environ.get("QUANT", "none")
        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        kw: dict = {}
        if quant == "4bit":
            from transformers import BitsAndBytesConfig
            kw["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16, bnb_4bit_quant_type="nf4")
            kw["device_map"] = "auto"
        else:
            kw["torch_dtype"] = torch.float16 if self.device == "cuda" else torch.float32
        self.tok = AutoTokenizer.from_pretrained(self.model_id)
        self.model = AutoModelForCausalLM.from_pretrained(self.model_id, **kw)
        if quant != "4bit":
            self.model.to(self.device)
        self.model.eval()
        self.quant = quant

    def info(self) -> dict:
        d = {"backend": "transformers", "model": self.model_id, "device": self.device, "quant": self.quant}
        if self.device == "cuda":
            d["gpu"] = self.torch.cuda.get_device_name(0)
            d["gpu_mem_alloc_mb"] = round(self.torch.cuda.memory_allocated() / 2**20)
        return d

    def generate(self, messages, max_tokens, temperature):
        ids = self.tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to(self.model.device)
        with self.torch.inference_mode():
            out = self.model.generate(
                ids, max_new_tokens=max_tokens, do_sample=temperature > 0,
                temperature=temperature or None, pad_token_id=self.tok.eos_token_id)
        new = out[0, ids.shape[1]:]
        return Generation(self.tok.decode(new, skip_special_tokens=True), int(ids.shape[1]), int(new.shape[0]))


def make_backend() -> Backend:
    kind = os.environ.get("BACKEND", "mock")
    if kind == "mock":
        return MockBackend()
    if kind == "transformers":
        return TransformersBackend()
    raise ValueError(f"BACKEND desconocido: {kind}")
