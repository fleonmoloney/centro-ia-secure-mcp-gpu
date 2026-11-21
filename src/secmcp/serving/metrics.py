from __future__ import annotations

import threading
from collections import deque


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    i = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return s[i]


class Metrics:
    """Ventana deslizante de latencias. Las cifras son de este proceso y se pierden al reiniciar."""

    def __init__(self, window: int = 1000):
        self._lat: deque[float] = deque(maxlen=window)
        self._tok: deque[tuple[int, float]] = deque(maxlen=window)
        self.requests = 0
        self.errors = 0
        self.rejected = 0
        self._lock = threading.Lock()

    def record(self, seconds: float, completion_tokens: int) -> None:
        with self._lock:
            self.requests += 1
            self._lat.append(seconds)
            self._tok.append((completion_tokens, seconds))

    def error(self) -> None:
        with self._lock:
            self.errors += 1

    def reject(self) -> None:
        with self._lock:
            self.rejected += 1

    def snapshot(self) -> dict:
        with self._lock:
            lat = list(self._lat)
            tok = list(self._tok)
        total_t = sum(s for _, s in tok)
        return {
            "requests": self.requests, "errors": self.errors, "rejected": self.rejected,
            "latency_p50_s": round(percentile(lat, 0.50), 4),
            "latency_p95_s": round(percentile(lat, 0.95), 4),
            "latency_p99_s": round(percentile(lat, 0.99), 4),
            "tokens_per_s": round(sum(n for n, _ in tok) / total_t, 2) if total_t else 0.0,
        }

    def prometheus(self) -> str:
        s = self.snapshot()
        lines = []
        for k, v in s.items():
            lines += [f"# TYPE secmcp_{k} gauge", f"secmcp_{k} {v}"]
        return "\n".join(lines) + "\n"
