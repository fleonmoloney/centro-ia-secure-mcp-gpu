"""Benchmark simple de latencia y rendimiento contra un endpoint. Cifras de una corrida, no garantías."""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from .metrics import percentile

PROMPT = [{"role": "user", "content": "Resumí en una frase qué es un viático."}]


def one(url: str, max_tokens: int, key: str) -> tuple[float, int]:
    h = {"Authorization": f"Bearer {key}"} if key else {}
    t0 = time.perf_counter()
    r = httpx.post(f"{url}/v1/chat/completions", headers=h, timeout=300,
                   json={"messages": PROMPT, "max_tokens": max_tokens, "temperature": 0})
    r.raise_for_status()
    return time.perf_counter() - t0, r.json()["usage"]["completion_tokens"]


def run(url: str, n: int, concurrency: int, max_tokens: int, key: str = "") -> dict:
    one(url, 8, key)  # calentamiento, no se mide
    t0 = time.perf_counter()
    with ThreadPoolExecutor(concurrency) as ex:
        res = list(ex.map(lambda _: one(url, max_tokens, key), range(n)))
    wall = time.perf_counter() - t0
    lat = [r[0] for r in res]
    toks = sum(r[1] for r in res)
    return {"n": n, "concurrency": concurrency, "max_tokens": max_tokens,
            "p50_s": round(percentile(lat, .5), 3), "p95_s": round(percentile(lat, .95), 3),
            "p99_s": round(percentile(lat, .99), 3), "tokens_per_s_total": round(toks / wall, 1),
            "wall_s": round(wall, 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("-c", "--concurrency", type=int, default=1)
    ap.add_argument("--max-tokens", type=int, default=64)
    ap.add_argument("--key", default="")
    a = ap.parse_args()
    print(json.dumps(run(a.url, a.n, a.concurrency, a.max_tokens, a.key), indent=2))


if __name__ == "__main__":
    main()
