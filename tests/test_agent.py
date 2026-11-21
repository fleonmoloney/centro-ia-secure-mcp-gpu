from secmcp.agent import run_agent
from secmcp.llm import ScriptedLLM, parse_action


def test_parse_action_tolerante():
    assert parse_action('texto {"final": "ok"} más')["final"] == "ok"
    assert parse_action("sin json") is None
    assert parse_action("{roto") is None


def test_agente_responde(guard):
    llm = ScriptedLLM(['{"tool": "search_docs", "args": {"query": "viáticos tope"}}', '{"final": "3.000"}'])
    run = run_agent(llm, guard, "¿tope?")
    assert run.final == "3.000" and run.steps[0]["ok"]


def test_tope_de_pasos(guard):
    llm = ScriptedLLM(['{"tool": "search_docs", "args": {"query": "viáticos"}}'])
    assert run_agent(llm, guard, "x", max_steps=3).stopped_by == "max_steps"


def test_salida_invalida_corta(guard):
    assert run_agent(ScriptedLLM(["no sé"]), guard, "x").stopped_by == "invalid_output"
