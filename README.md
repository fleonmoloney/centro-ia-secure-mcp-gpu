# secmcp — MCP seguro, defensas contra inyección y exfiltración, y servicio de modelos con GPU

Prototipo de referencia que junta cinco cosas que suelen verse por separado: un **servidor MCP**, una **política de flujo** contra inyección de instrucciones y exfiltración, un **servicio de modelos con GPU**, **CI/CD con contenedores** e **infraestructura como código**. Se puede ejecutar gratis en Colab o Kaggle (GPU T4).

Es un prototipo de arquitectura, no un producto. Lo que se verificó y lo que no está abajo, sin adornos.

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
pytest -q                             # 36 pruebas, sin red, sin GPU, sin claves
python -m secmcp.evals --gate         # compuerta de evals adversariales

# servicio con backend simulado
BACKEND=mock uvicorn secmcp.serving.app:app_factory --factory --port 8000
python -m secmcp.serving.bench -n 20 -c 4

# servidor MCP por stdio (por ejemplo, desde un cliente MCP)
secmcp-server
```
Con GPU gratuita: abrí `notebooks/colab_gpu.ipynb` en Colab (GPU T4) o Kaggle. Con Docker: `docker compose up serving-cpu`, o `docker compose --profile gpu up serving-gpu` en un host con NVIDIA Container Toolkit.

## Resultados en GPU (Colab, Tesla T4 de 15 GB, 21/11/2026)
Modelo `Qwen/Qwen2.5-1.5B-Instruct` con `transformers`, 20 pedidos por corrida, `max_tokens=64`, `temperature=0`. Una o dos corridas por configuración: orientan, no son un benchmark de referencia. La salida completa está en el notebook ejecutado.

| Configuración | Memoria GPU tras cargar | p50 | p95 | p99 | tokens/s |
|---|---|---|---|---|---|
| fp16, 1 pedido a la vez (1.ª corrida) | 2945 MB | 0,876 s | 1,123 s | 1,172 s | 29,7 |
| fp16, 4 en paralelo (1.ª corrida) | 2945 MB | 3,759 s | 9,043 s | 9,118 s | 23,1 |
| 4 bits (bitsandbytes), 1 a la vez | 1158 MB | 2,047 s | 2,627 s | 2,684 s | 15,4 |
| fp16, 1 a la vez (2.ª corrida) | 3010 MB tras los pedidos | 0,866 s | 1,179 s | 1,186 s | 29,0 |
| fp16, 4 en paralelo (2.ª corrida) | idem | 3,388 s | 3,959 s | 4,039 s | 30,8 |
| fp16, 8 en paralelo (2.ª corrida) | idem | 6,944 s | 7,698 s | 7,797 s | 28,8 |

Lectura:
- **La cuantización a 4 bits ahorra ~61 % de memoria** (2945 → 1158 MB) **pero es ~2,3 veces más lenta** en este modelo (p50 2,047 s contra 0,876 s). Con un modelo de 1,5 B que entra de sobra en la T4, no conviene; sirve cuando el modelo no cabe en fp16. No se midió si cambia la calidad de las respuestas.
- **La concurrencia no aumenta el rendimiento:** con 1, 4 y 8 pedidos en paralelo el total queda plano (~29-31 tokens/s) y la latencia crece casi linealmente (p50 0,87 → 3,4 → 6,9 s), porque el servicio serializa la GPU con un semáforo y no hace batching continuo. La primera corrida con 4 en paralelo dio 23,1 tokens/s y p95 de 9 s; la segunda, 30,8 y 4,0 s. La diferencia entre corridas muestra la variabilidad (posible efecto de calentamiento, no verificado). Para carga real, vLLM o TGI.

### Un modelo real ante el documento envenenado (`secmcp.demo`, una corrida)
- **Sin defensa**, el modelo de 1,5 B obedeció la inyección: buscó las novedades, leyó la nota privada y llamó a `http_post` y `send_report`; hubo fuga (el canario salió).
- **Con Guard**, el documento quedó marcado y la corrida terminó sin fuga, **pero por `invalid_output`** (el modelo no emitió una acción válida tras el documento), no porque la política bloqueara un intento del modelo. Esta corrida no demuestra el bloqueo con un modelo real; ese bloqueo está demostrado en la compuerta determinista de evals, con un modelo guionado que obedece siempre.
- Con una herramienta inexistente (`calendar_novelties`), el Guard la rechazó con `default-deny`.
- Es una corrida con un modelo chico: no mide la tasa de obediencia ni la robustez de ningún modelo.

## Qué se verificó y qué no
**Verificado:**
- 36 pruebas y `ruff`: política, escáneres, Guard, agente, servicio, métricas y servidor MCP con un cliente en memoria; también pasan en Colab.
- Compuerta de evals, incluida la mutación que la hace fallar: sin defensa 6/7 fugas, con Guard 0/7, tareas legítimas 3/3.
- `secmcp-server` por stdio con el cliente de la SDK de MCP: lista las cuatro herramientas y bloquea una salida a un destino no permitido.
- **GPU (T4):** `TransformersBackend` en fp16 y en 4 bits, carga, memoria, latencia y rendimiento (tabla de arriba), 0 errores en las corridas medidas.
- **CI en GitHub** (todos los jobs verdes): pruebas en Python 3.10 y 3.12, `ruff`, compuerta de evals, construcción de la imagen CPU, prueba de humo del contenedor, escaneo con Trivy (sin hallazgos HIGH/CRITICAL corregibles), `terraform fmt`, `init` y `validate`, y construcción de la imagen GPU.
- El servicio con uvicorn y el benchmark por HTTP, con el backend simulado y con el modelo real.

**No verificado:**
- **Terraform `plan`/`apply`:** solo se validó la sintaxis y la configuración. La familia de imagen de Deep Learning VM y la disponibilidad de la GPU en la zona hay que verificarlas. No hay GPU gratuita en la nube por IaC: aplicar cuesta dinero.
- **vLLM:** la celda opcional no produjo una medición confiable en la corrida (el puerto 8000 seguía ocupado por el servidor anterior); no hay cifras de vLLM.
- **La imagen GPU ejecutada con GPU:** se construye en CI, pero no se corrió el contenedor con la GPU ni se escaneó con Trivy.
- **Calidad del modelo en 4 bits** y **robustez de modelos reales ante la inyección:** el demo es una corrida con un modelo chico.
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
tests/        36 pruebas (pytest)
infra/        terraform (GCP, VM spot con GPU)
notebooks/    colab_gpu.ipynb
docs/         threat_model.md · serving.md
.github/      CI
```

## Autor
Fernando León Moloney — Ingeniero en Sistemas. Licencia MIT.
