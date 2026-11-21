import json
import math

from secmcp import quality
from secmcp.quality import classify, compare_md, load_prompts, ppl_from_nll, score, wilson


def test_wilson_limites_y_centro():
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and 0.7 < lo < 0.75
    lo, hi = wilson(12, 24)
    assert lo < 0.5 < hi


def test_classify_acciones():
    assert classify('{"final": "hola"}') == "final"
    assert classify('texto {"tool": "search_docs", "args": {"query": "x"}} fin') == "search_docs"
    assert classify('{"tool": "borrar_todo", "args": {}}') is None   # herramienta inexistente
    assert classify("no es json") is None
    assert classify('{"otra": 1}') is None


def test_score_cuenta_validas_y_esperadas():
    rows = [{"expected": "final", "got": "final"}, {"expected": "search_docs", "got": "final"},
            {"expected": "send_report", "got": None}, {"expected": "final", "got": "final"}]
    s = score(rows)
    assert s["n"] == 4 and s["valid"]["k"] == 3 and s["expected"]["k"] == 2
    assert s["expected"]["lo"] < 0.5 < s["expected"]["hi"]


def test_ppl_from_nll():
    assert math.isclose(ppl_from_nll(0.0, 10), 1.0)
    assert math.isclose(ppl_from_nll(math.log(5) * 10, 10), 5.0)


def test_prompts_del_repo_son_validos():
    ps = load_prompts()
    assert len(ps) == 24 and len({p["id"] for p in ps}) == 24
    assert {p["expected"] for p in ps} <= quality.TOOLS | {"final"}


def test_compare_md_tabla():
    def res(q, v):
        m = {"k": 1, "rate": v, "lo": 0.1, "hi": 0.9}
        return {"quant": q, "gpu_mem_mb": 1, "ppl_en": {"ppl": 9.5}, "ppl_es": None,
                "agent": {"n": 24, "valid": m, "expected": m}}
    md = compare_md(res("fp16", 0.9), res("4 bits", 0.8))
    assert "| Medida | fp16 | 4 bits |" in md and "9.5" in md and "—" in md
    json.dumps(res("a", 1))


def test_compare_md_avisa_si_falta_la_perplejidad_en_ingles():
    m = {"k": 1, "rate": 0.5, "lo": 0.1, "hi": 0.9}
    r = {"quant": "fp16", "gpu_mem_mb": 1, "ppl_en": None, "ppl_en_error": "ConnectionError: x",
         "ppl_es": {"ppl": 22.0}, "agent": {"n": 24, "valid": m, "expected": m}}
    assert "no disponible: ConnectionError" in compare_md(r, {**r, "quant": "4 bits"})
