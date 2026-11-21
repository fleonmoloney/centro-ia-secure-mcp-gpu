from fastapi.testclient import TestClient

from secmcp.serving.app import create_app
from secmcp.serving.backends import MockBackend
from secmcp.serving.metrics import Metrics, percentile

BODY = {"messages": [{"role": "user", "content": "hola"}], "max_tokens": 16}


def client(**kw):
    return TestClient(create_app(MockBackend(), **kw))


def test_health_y_ready():
    c = client()
    assert c.get("/healthz").json()["status"] == "ok"
    assert c.get("/readyz").json()["status"] == "ready"


def test_readyz_503_mientras_carga():
    # TestClient sin "with" no ejecuta el lifespan: el modelo no se carga y el servicio no está listo.
    c = TestClient(create_app(None))
    assert c.get("/healthz").status_code == 200
    assert c.get("/readyz").status_code == 503
    assert c.post("/v1/chat/completions", json=BODY).status_code == 503


def test_chat_compatible_openai():
    r = client().post("/v1/chat/completions", json=BODY)
    j = r.json()
    assert r.status_code == 200 and j["choices"][0]["message"]["role"] == "assistant"
    assert j["usage"]["total_tokens"] > 0


def test_api_key():
    c = client(api_key="secreta")
    assert c.post("/v1/chat/completions", json=BODY).status_code == 401
    ok = c.post("/v1/chat/completions", json=BODY, headers={"Authorization": "Bearer secreta"})
    assert ok.status_code == 200


def test_entrada_demasiado_larga():
    big = {"messages": [{"role": "user", "content": "x" * 20000}]}
    assert client().post("/v1/chat/completions", json=big).status_code == 413


def test_rol_invalido():
    bad = {"messages": [{"role": "root", "content": "x"}]}
    assert client().post("/v1/chat/completions", json=bad).status_code == 422


def test_metricas():
    c = client()
    c.post("/v1/chat/completions", json=BODY)
    assert "secmcp_requests 1" in c.get("/metrics").text


def test_percentiles():
    assert percentile([1, 2, 3, 4, 100], 0.5) == 3
    assert percentile([], 0.99) == 0.0
    m = Metrics()
    for i in range(10):
        m.record(0.1 * (i + 1), 10)
    assert m.snapshot()["latency_p99_s"] >= m.snapshot()["latency_p50_s"]


def test_error_de_generacion_se_registra_y_no_filtra_detalle(caplog):
    class Roto:
        name = "roto"
        def info(self): return {}
        def generate(self, *a): raise RuntimeError("detalle-interno-secreto")
    c = TestClient(create_app(backend=Roto(), api_key=""))
    with caplog.at_level("ERROR", logger="secmcp.serving"):
        r = c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hola"}]})
    assert r.status_code == 500
    assert "detalle-interno-secreto" not in r.text
    assert "detalle-interno-secreto" in caplog.text


def test_transformers_generate_tokeniza_aparte_y_pasa_mascara():
    import contextlib
    from types import SimpleNamespace

    from secmcp.serving.backends import TransformersBackend

    class Enc(dict):
        def to(self, _): return self
    class Ids(list):
        shape = (1, 3)
    class Out:
        def __getitem__(self, k): return SimpleNamespace(shape=(2,), tolist=lambda: [7, 8])
    seen = {}
    class Tok:
        eos_token_id = 0
        def apply_chat_template(self, m, add_generation_prompt, tokenize):
            assert tokenize is False
            return "PROMPT"
        def __call__(self, text, return_tensors):
            assert text == "PROMPT"
            return Enc(input_ids=Ids(), attention_mask=[1])
        def decode(self, ids, skip_special_tokens): return "ok"
    class Model:
        device = "cpu"
        def generate(self, **kw):
            seen.update(kw)
            return Out()
    b = TransformersBackend.__new__(TransformersBackend)
    b.tok, b.model = Tok(), Model()
    b.torch = SimpleNamespace(inference_mode=contextlib.nullcontext)
    g = b.generate([{"role": "user", "content": "x"}], 16, 0.0)
    assert g.text == "ok" and g.prompt_tokens == 3 and g.completion_tokens == 2
    assert "attention_mask" in seen and seen["do_sample"] is False and "temperature" not in seen
