from pathlib import Path

from secmcp import evals

ROOT = Path(__file__).resolve().parents[1]


def test_gate_de_evals_pasa():
    res = evals.evaluate(evals.load_cases(ROOT / "evals" / "attacks.jsonl"), ROOT / "data")
    assert evals.gate(res) == []


def test_sin_defensa_los_ataques_son_reales():
    res = evals.evaluate(evals.load_cases(ROOT / "evals" / "attacks.jsonl"), ROOT / "data")
    assert evals.summarize(res)["unguarded"]["leaks"] >= 5


def test_la_compuerta_detecta_una_defensa_rota(monkeypatch):
    # Mutación: una política que permite todo debe hacer fallar la compuerta.
    from secmcp.policy import Decision, Policy, Verdict
    monkeypatch.setattr(Policy, "check", lambda self, s, n, a, approval_id=None: Decision(Verdict.ALLOW, "roto", "x"))
    res = evals.evaluate(evals.load_cases(ROOT / "evals" / "attacks.jsonl"), ROOT / "data")
    assert evals.gate(res) != []
