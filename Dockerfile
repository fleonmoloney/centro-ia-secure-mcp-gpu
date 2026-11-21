# Imagen CPU: servicio con backend simulado + servidor MCP + evals. Es la que corre CI.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY data ./data
COPY evals ./evals
RUN pip install . && useradd --system --uid 10001 app && chown -R app /app
USER app
ENV BACKEND=mock SECMCP_DATA=/app/data
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
CMD ["uvicorn", "secmcp.serving.app:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
