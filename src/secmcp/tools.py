"""Herramientas del agente. Todo es local y ficticio: no hay red real.
send_report y http_post escriben en un 'buzón' en memoria que hace de vía de salida,
para poder medir si algo se filtró."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .policy import ToolSpec

SPECS = {
    "search_docs": ToolSpec("search_docs", returns_untrusted=True),
    "read_private_note": ToolSpec("read_private_note", reads_private=True),
    "send_report": ToolSpec("send_report", sink=True, destination_arg="to"),
    "http_post": ToolSpec("http_post", sink=True, destination_arg="url"),
}


@dataclass
class Outbox:
    """Lo que salió del sistema. Una prueba de exfiltración mira si algo sensible llegó acá."""
    sent: list[dict] = field(default_factory=list)


@dataclass
class Toolbox:
    docs_dir: Path
    private_dir: Path
    outbox: Outbox = field(default_factory=Outbox)

    def search_docs(self, query: str, k: int = 2) -> str:
        words = {w for w in query.lower().split() if len(w) > 2}
        scored = []
        for f in sorted(self.docs_dir.glob("*.md")):
            text = f.read_text(encoding="utf-8")
            score = sum(1 for w in words if w in text.lower())
            if score:
                scored.append((score, f.name, text))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return "\n\n".join(f"[{name}]\n{text}" for _, name, text in scored[:k]) or "(sin resultados)"

    def read_private_note(self, name: str) -> str:
        f = (self.private_dir / name).resolve()
        if self.private_dir.resolve() not in f.parents:
            raise PermissionError("ruta fuera del directorio privado")
        return f.read_text(encoding="utf-8")

    def send_report(self, to: str, body: str) -> str:
        self.outbox.sent.append({"tool": "send_report", "to": to, "body": body})
        return f"enviado a {to}"

    def http_post(self, url: str, body: str) -> str:
        self.outbox.sent.append({"tool": "http_post", "to": url, "body": body})
        return f"POST {url} ok"

    def call(self, name: str, args: dict) -> str:
        fn = getattr(self, name)
        return fn(**args)
