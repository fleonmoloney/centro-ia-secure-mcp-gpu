"""Calidad del modelo cuantizado: ¿cuánto se degrada al pasar de fp16 a 4 bits?

Dos medidas, ambas con el modelo cargado en el propio proceso (no hace falta levantar el servicio):
  1. Perplejidad sobre texto (inglés: wikitext-2 si hay `datasets`; español: los documentos ficticios del repo).
     Es la medida estándar de degradación por cuantización; menor es mejor.
  2. Comportamiento como agente: sobre 24 pedidos (evals/quality_prompts.jsonl, escritos por el autor) se mide
     (a) qué porcentaje de las respuestas es una acción JSON válida con una herramienta conocida, y
     (b) qué porcentaje elige la acción esperada. Con intervalo de Wilson al 95 %.
Son muestras chicas: sirven como indicio, no como prueba.

Uso:
  python -m secmcp.quality --quant none --out results/q_fp16.json
  python -m secmcp.quality --quant 4bit --out results/q_4bit.json
  python -m secmcp.quality --compare results/q_fp16.json results/q_4bit.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from .agent import SYSTEM
from .llm import parse_action

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "evals" / "quality_prompts.jsonl"
DOCS = ROOT / "data" / "docs"
TOOLS = {"search_docs", "read_private_note", "send_report", "http_post"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def classify(text: str) -> str | None:
    """Acción válida: 'final' o el nombre de una herramienta conocida. None si no es válida."""
    act = parse_action(text)
    if act is None:
        return None
    if "final" in act:
        return "final"
    tool = str(act.get("tool", ""))
    return tool if tool in TOOLS else None


def score(rows: list[dict]) -> dict:
    """rows: [{'expected': str, 'got': str|None}]."""
    n = len(rows)
    valid = sum(1 for r in rows if r["got"] is not None)
    hit = sum(1 for r in rows if r["got"] == r["expected"])
    out = {"n": n}
    for name, k in (("valid", valid), ("expected", hit)):
        lo, hi = wilson(k, n)
        out[name] = {"k": k, "rate": round(k / n, 3) if n else 0.0, "lo": round(lo, 3), "hi": round(hi, 3)}
    return out


def ppl_from_nll(total_nll: float, n_tokens: int) -> float:
    return math.exp(total_nll / n_tokens)


def load_prompts(path: Path = PROMPTS) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def agent_behaviour(backend, prompts: list[dict]) -> tuple[dict, list[dict]]:
    rows = []
    for p in prompts:
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": p["prompt"]}]
        text = backend.generate(msgs, 128, 0.0).text
        rows.append({"id": p["id"], "expected": p["expected"], "got": classify(text), "raw": text[:160]})
    return score(rows), rows


def perplexity(backend, text: str, block: int = 512, max_blocks: int = 40) -> dict:
    """Perplejidad por bloques no solapados de `block` tokens (aproximación estándar, rápida)."""
    torch = backend.torch
    ids = backend.tok(text, return_tensors="pt")["input_ids"][0]
    block = min(block, int(ids.shape[0]) - 1)
    if block < 8:
        return {"ppl": None, "tokens": int(ids.shape[0]), "blocks": 0}
    total, count, nb = 0.0, 0, 0
    for s in range(0, int(ids.shape[0]) - block, block):
        if nb >= max_blocks:
            break
        x = ids[s:s + block].unsqueeze(0).to(backend.model.device)
        with torch.inference_mode():
            loss = backend.model(x, labels=x).loss.item()
        total += loss * (block - 1)
        count += block - 1
        nb += 1
    return {"ppl": round(ppl_from_nll(total, count), 3), "tokens": count, "blocks": nb}


def spanish_text() -> str:
    return "\n\n".join(p.read_text(encoding="utf-8") for p in sorted(DOCS.glob("*.md")))


def english_text() -> str:
    """wikitext-2 (test). Si falla (sin red, sin `datasets`, versiones), la excepción se registra en el resultado."""
    from datasets import load_dataset
    ds = load_dataset("Salesforce/wikitext", "wikitext-2-raw-v1", split="test")
    return "\n\n".join(ds["text"])


def compare_md(a: dict, b: dict) -> str:
    def pct(m):
        return f"{m['rate']*100:.0f} % [{m['lo']*100:.0f}–{m['hi']*100:.0f}]"

    def ppl(x):
        return "—" if x is None or x.get("ppl") is None else f"{x['ppl']}"
    la, lb = a["quant"], b["quant"]
    rows = [
        ("Memoria GPU tras cargar (MB)", a.get("gpu_mem_mb", "—"), b.get("gpu_mem_mb", "—")),
        ("Perplejidad, inglés (wikitext-2)", ppl(a.get("ppl_en")), ppl(b.get("ppl_en"))),
        ("Perplejidad, español (docs del repo, muestra chica)", ppl(a.get("ppl_es")), ppl(b.get("ppl_es"))),
        (f"Acción JSON válida (n={a['agent']['n']}), % [IC 95 %]", pct(a["agent"]["valid"]), pct(b["agent"]["valid"])),
        ("Acción esperada, % [IC 95 %]", pct(a["agent"]["expected"]), pct(b["agent"]["expected"])),
    ]
    out = [f"| Medida | {la} | {lb} |", "|---|---|---|"]
    out += [f"| {r[0]} | {r[1]} | {r[2]} |" for r in rows]
    for r in (a, b):
        if r.get("ppl_en_error"):
            out.append(f"\nNota ({r['quant']}): perplejidad en inglés no disponible: {r['ppl_en_error']}")
            break
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--quant", default="none", choices=["none", "4bit"])
    ap.add_argument("--out", default="")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    a = ap.parse_args()
    if a.compare:
        print(compare_md(*[json.loads(Path(p).read_text()) for p in a.compare]))
        return
    from .serving.backends import TransformersBackend
    t0 = time.perf_counter()
    be = TransformersBackend(a.model, a.quant)
    info = be.info()
    res: dict = {"model": a.model, "quant": "fp16" if a.quant == "none" else "4 bits", "gpu": info.get("gpu"),
                 "gpu_mem_mb": info.get("gpu_mem_alloc_mb")}
    try:
        res["ppl_en"] = perplexity(be, english_text())
    except Exception as e:  # noqa: BLE001 - es opcional, pero se dice por qué no está
        res["ppl_en"] = None
        res["ppl_en_error"] = f"{type(e).__name__}: {e}"[:300]
        print("AVISO: no se pudo medir la perplejidad en inglés:", res["ppl_en_error"], file=sys.stderr)
    res["ppl_es"] = perplexity(be, spanish_text())
    res["agent"], rows = agent_behaviour(be, load_prompts())
    res["agent_rows"] = rows
    res["seconds"] = round(time.perf_counter() - t0, 1)
    txt = json.dumps(res, ensure_ascii=False, indent=2)
    print(txt)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
