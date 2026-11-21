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
