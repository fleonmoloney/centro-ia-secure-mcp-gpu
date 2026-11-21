# secmcp — MCP seguro, defensas contra inyección y exfiltración, y servicio de modelos con GPU

Prototipo de referencia que junta cinco cosas que suelen verse por separado: un **servidor MCP**, una **política de flujo** contra inyección de instrucciones y exfiltración, un **servicio de modelos con GPU**, **CI/CD con contenedores** e **infraestructura como código**. Se puede ejecutar gratis en Colab o Kaggle (GPU T4).

Es un prototipo de arquitectura, no un producto. Lo que se verificó y lo que no.

## Qué incluye
| Pieza | Qué hace | Código |
|---|---|---|
| Servidor MCP (stdio) | Expone `search_docs`, `read_private_note`, `send_report`, `http_post`; todas pasan por el Guard | `mcp_server.py` |
| Política de flujo | Default-deny, etiquetado de contaminación, tríada letal, lista blanca de destinos, canarios, aprobación humana con revisor | `policy.py`, `guard.py` |
| Escáneres | Heurísticas de instrucciones en datos (es/en), secretos, canarios, caracteres invisibles | `scanners.py` |
| Agente | Bucle mínimo con tope de pasos; el modelo emite JSON y el Guard decide | `agent.py`, `llm.py` |
| Evals adversariales | 10 casos con un modelo simulado que obedece la inyección; compuerta para CI | `evals.py`, `evals/attacks.jsonl` |
| Servicio de modelos | API compatible con OpenAI, readiness, métricas, clave de API; backends `mock` y `transformers` (fp16 / 4 bits) | `serving/` |
| Contenedores | Imagen CPU (la de CI) e imagen GPU (CUDA), compose con perfil `gpu` | `Dockerfile`, `Dockerfile.gpu`, `docker-compose.yml` |
| CI/CD | Lint, pruebas en 3.10 y 3.12, compuerta de evals, humo del contenedor, Trivy, publicación en GHCR, `terraform validate` | `.github/workflows/ci.yml` |
| IaC | Terraform para una VM spot con GPU T4 en GCP, con firewall restringido y cuenta de servicio mínima | `infra/terraform/` |
| Notebook | Colab/Kaggle: sirve el modelo, mide, compara fp16 y 4 bits, corre el agente | `notebooks/colab_gpu.ipynb` |

## La idea de seguridad
Un agente se vuelve explotable cuando reúne en una sesión datos privados, contenido no confiable y una vía de salida. En lugar de intentar reconocer cada ataque, la política corta esa combinación. Detalle y límites en [`docs/threat_model.md`](docs/threat_model.md).

## Resultados medidos
`python -m secmcp.evals --gate` sobre `evals/attacks.jsonl` (7 ataques y 3 tareas legítimas, escritos por el autor). El «modelo» es un guion que obedece la inyección siempre:

| Configuración | Ataques | Fugas | Tareas legítimas completadas |
|---|---|---|---|
| Sin defensa | 7 | 6 | 3/3 |
| Con Guard | 7 | 0 | 3/3 |

Qué dicen y qué no:
- Prueban que **la política** corta la exfiltración aunque el modelo obedezca, incluida la codificada en base64 que el escáner no ve.
- Los tests incluyen una mutación: una política que permite todo hace fallar la compuerta, y la compuerta exige que sin defensa haya fugas (si no, los ataques no serían reales).
- **No** prueban la robustez de ningún modelo real. Son pocos casos y los escribió quien escribió la defensa.

## Ejecutar
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                             # 34 pruebas, sin red, sin GPU, sin claves
python -m secmcp.evals --gate         # compuerta de evals adversariales

# servicio con backend simulado
BACKEND=mock uvicorn secmcp.serving.app:app_factory --factory --port 8000
python -m secmcp.serving.bench -n 20 -c 4

# servidor MCP por stdio (por ejemplo, desde un cliente MCP)
secmcp-server
```
Con GPU gratuita: abrí `notebooks/colab_gpu.ipynb` en Colab (GPU T4) o Kaggle. Con Docker: `docker compose up serving-cpu`, o `docker compose --profile gpu up serving-gpu` en un host con NVIDIA Container Toolkit.

## Qué se verificó y qué no
**Verificado** (en el entorno de desarrollo, sin GPU):
- 34 pruebas y `ruff`: política, escáneres, Guard, agente, servicio, métricas y el servidor MCP con un cliente MCP en memoria.
- Compuerta de evals, incluida la mutación que la hace fallar.
- `secmcp-server` levantado por stdio y consultado con el cliente stdio de la SDK de MCP: lista las cuatro herramientas y bloquea una salida a un destino no permitido.
- El servicio levantado con uvicorn y el benchmark por HTTP, con el backend simulado.
- Sintaxis HCL de los archivos de Terraform (con un parser, no con Terraform).

**No verificado:**
- **GPU.** `TransformersBackend`, la cuantización de 4 bits y el notebook no se ejecutaron en una GPU real. Hay que correr el notebook y pegar la salida aquí, sin editarla. Hoy no hay cifras de latencia ni de memoria de GPU.
- **Docker.** No había daemon: ni `Dockerfile` ni `Dockerfile.gpu` se construyeron.
- **Terraform.** No se ejecutó `terraform validate` ni `plan` ni `apply` (el binario no se pudo descargar). La familia de imagen de Deep Learning VM y la disponibilidad de la GPU en la zona hay que verificarlas. No hay GPU gratuita en la nube por IaC: esto cuesta dinero si se aplica.
- **CI.** El workflow nunca corrió en GitHub. Trivy puede reportar vulnerabilidades de las imágenes base y fallar el job; `terraform fmt -check` puede pedir reformatear.
- **Un modelo real ante la inyección.** `secmcp.demo` lo muestra, pero un modelo chico puede no emitir JSON válido ni obedecer el ataque; el resultado depende del modelo.
- **Un cliente MCP de producto** (por ejemplo, un asistente de escritorio) contra `secmcp-server`: solo se probó con el cliente de la SDK.

## Limitaciones conocidas
- El Guard tiene una sesión por proceso: con varios clientes concurrentes hace falta una sesión por conexión.
- Las heurísticas de inyección son una mitigación y se evaden; la barrera fuerte es la política de flujo.
- Una persona puede aprobar sin leer; la aprobación exige revisor y queda en la bitácora, nada más.
- El servicio no hace batching continuo: para carga real, vLLM o TGI (ver `docs/serving.md`).
- Sin TLS ni límite por cliente; va detrás de un gateway.
- Datos ficticios: `data/private/credenciales.txt` es un canario, no un secreto real.

## Estructura
```
src/secmcp/   scanners · policy · guard · tools · agent · llm · mcp_server · evals · demo · serving/
evals/        attacks.jsonl
tests/        34 pruebas (pytest)
infra/        terraform (GCP, VM spot con GPU)
notebooks/    colab_gpu.ipynb
docs/         threat_model.md · serving.md
.github/      CI
```

## Autor
Fernando León Moloney — Ingeniero en Sistemas. Licencia MIT.
