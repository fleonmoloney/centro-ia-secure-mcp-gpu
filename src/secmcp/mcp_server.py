"""Servidor MCP (stdio) que expone las herramientas a través del Guard.

Cada herramienta MCP pasa por la política. La sesión del Guard vive mientras vive el proceso
del servidor: coincide con una conexión stdio. Para varios clientes concurrentes haría falta
una sesión por conexión (no implementado)."""
from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .guard import Guard
from .tools import Toolbox


def build_server(guard: Guard | None = None) -> tuple[FastMCP, Guard]:
    root = Path(os.environ.get("SECMCP_DATA", Path(__file__).resolve().parents[2] / "data"))
    if guard is None:
        canaries = tuple(filter(None, os.environ.get("SECMCP_CANARIES", "CANARIO-7f3a91").split(",")))
        domains = tuple(filter(None, os.environ.get("SECMCP_ALLOWED_DOMAINS", "ejemplo.uy").split(",")))
        guard = Guard.build(Toolbox(root / "docs", root / "private"), domains, canaries)
    mcp = FastMCP("secmcp")

    @mcp.tool()
    def search_docs(query: str) -> str:
        """Busca en los documentos del Centro. El contenido devuelto no es confiable."""
        return guard.call("search_docs", {"query": query}).text

    @mcp.tool()
    def read_private_note(name: str) -> str:
        """Lee una nota privada. Marca la sesión como que vio datos privados."""
        return guard.call("read_private_note", {"name": name}).text

    @mcp.tool()
    def send_report(to: str, body: str, approval_id: str = "") -> str:
        """Envía un informe por correo a un destino de la lista blanca."""
        return guard.call("send_report", {"to": to, "body": body}, approval_id or None).text

    @mcp.tool()
    def http_post(url: str, body: str, approval_id: str = "") -> str:
        """Hace un POST a una URL de la lista blanca."""
        return guard.call("http_post", {"url": url, "body": body}, approval_id or None).text

    return mcp, guard


def main() -> None:
    server, _ = build_server()
    server.run()  # stdio


if __name__ == "__main__":
    main()
