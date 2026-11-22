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
pytest -q                             # 43 pruebas, sin red, sin GPU, sin claves
python -m secmcp.evals --gate         # compuerta de evals adversariales

# servicio con backend simulado
BACKEND=mock uvicorn secmcp.serving.app:app_factory --factory --port 8000
python -m secmcp.serving.bench -n 20 -c 4

# servidor MCP por stdio (por ejemplo, desde un cliente MCP)
secmcp-server
```
En **Windows (cmd)**: activar con `.venv\Scripts\activate.bat`, y la variable de entorno se define aparte:
```
set BACKEND=mock
uvicorn secmcp.serving.app:app_factory --factory --port 8000
```
(en PowerShell: `$env:BACKEND="mock"`).
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
- **La cuantización a 4 bits ahorra ~61 % de memoria** (2945 → 1158 MB) **pero es ~2,3 veces más lenta** en este modelo (p50 2,047 s contra 0,876 s). Con un modelo de 1,5 B que entra de sobra en la T4, no conviene; sirve cuando el modelo no cabe en fp16. La calidad se midió aparte (sección siguiente).
- **La concurrencia no aumenta el rendimiento:** con 1, 4 y 8 pedidos en paralelo el total queda plano (~29-31 tokens/s) y la latencia crece casi linealmente (p50 0,87 → 3,4 → 6,9 s), porque el servicio serializa la GPU con un semáforo y no hace batching continuo. La primera corrida con 4 en paralelo dio 23,1 tokens/s y p95 de 9 s; la segunda, 30,8 y 4,0 s. La diferencia entre corridas muestra la variabilidad (posible efecto de calentamiento, no verificado). Para carga real, vLLM o TGI.

### Calidad: fp16 contra 4 bits (`secmcp.quality`, 24 pedidos, una corrida)
Mismo modelo y misma T4; el modelo se carga en el propio proceso. Muestras chicas: sirven como indicio, no como prueba.

| Medida | fp16 | 4 bits |
|---|---|---|
| Memoria GPU tras cargar | 2945 MB | 1158 MB |
| Perplejidad, español (documentos del repo; un solo bloque de texto) | 22,175 | 24,081 |
| Perplejidad, inglés (wikitext-2) | no obtenida | no obtenida |
| Acción JSON válida (n=24), % [IC 95 %] | 83 % [64–93] | 79 % [60–91] |
| Acción esperada, % [IC 95 %] | 71 % [51–85] | 75 % [55–88] |

Lectura:
- En perplejidad en español, 4 bits sube ~9 % (22,2 → 24,1): la degradación esperable de la cuantización, medida sobre un texto muy corto.
- En comportamiento como agente **no se detecta diferencia**: las dos columnas difieren en un solo pedido de 24 (20 contra 19 válidas; 17 contra 18 con la acción esperada), con intervalos de unos ±15 puntos que se superponen casi por completo. Con esta muestra no se puede afirmar que 4 bits sea igual ni que sea peor; solo que la diferencia, si existe, no se ve con 24 pedidos.
- Aun en fp16, **~17 % de las respuestas no es una acción válida** (4 de 24): es la razón de los `invalid_output` del demo y un límite de este modelo chico para actuar como agente.
- La perplejidad en inglés no se obtuvo: la carga de wikitext-2 falló sin aviso en esa corrida (el script ya registra el motivo). Los pedidos y las acciones esperadas los escribió el autor.

### vLLM contra transformers (misma T4, mismo modelo y prompt, 20 pedidos, `max_tokens=64`)
vLLM 0.34.0 con `--dtype half --max-model-len 4096`, servidor de la API compatible con OpenAI. Una corrida por configuración.

| Pedidos en paralelo | transformers p50 | vLLM p50 | transformers tokens/s | vLLM tokens/s |
|---|---|---|---|---|
| 1 | 0,866 s | 0,604 s | 29,0 | 62,3 |
| 4 | 3,388 s | 0,739 s | 30,8 | 200,7 |
| 8 | 6,944 s | 0,891 s | 28,8 | 305,5 |

Lectura:
- Con 1 pedido, vLLM ya es ~2 veces más rápido; con 8 en paralelo, el rendimiento es ~10 veces mayor y la latencia p50 ~8 veces menor. Con transformers la latencia crece casi linealmente con la concurrencia; con vLLM casi no se mueve, por el batching continuo.
- Es una comparación entre **servidores completos** (batching continuo, atención paginada, grafos CUDA), no solo entre bibliotecas de inferencia.
- Qué no dice: no se comparó la calidad de las respuestas; vLLM reserva por defecto gran parte de la memoria de la GPU para la caché, así que su consumo de memoria no es comparable con el de la tabla anterior (no se midió); son corridas cortas (20 pedidos, el de 8 en paralelo dura ~2,5 s) y de una sola vez. Las cifras de la T4 gratuita varían con la carga de la sesión.
- Instalar vLLM en Colab dejó conflictos de dependencias (entre otros, subió `mcp` a 2.x, incompatible con `mcp<2` de este repo): conviene hacerlo en una sesión aparte y reiniciar el entorno después.

### Un modelo real ante el documento envenenado (`secmcp.demo`, una corrida)
- **Sin defensa**, el modelo de 1,5 B obedeció la inyección: buscó las novedades, leyó la nota privada y llamó a `http_post` y `send_report`; hubo fuga (el canario salió).
- **Con Guard**, el documento quedó marcado y la corrida terminó sin fuga, **pero por `invalid_output`** (el modelo no emitió una acción válida tras el documento), no porque la política bloqueara un intento del modelo. Esta corrida no demuestra el bloqueo con un modelo real; ese bloqueo está demostrado en la compuerta determinista de evals, con un modelo guionado que obedece siempre.
- Con una herramienta inexistente (`calendar_novelties`), el Guard la rechazó con `default-deny`.
- Es una corrida con un modelo chico: no mide la tasa de obediencia ni la robustez de ningún modelo.

## Qué se verificó y qué no
**Verificado:**
- 43 pruebas y `ruff` (en CI): política, escáneres, Guard, agente, servicio, métricas, calidad y servidor MCP con un cliente en memoria. En Colab pasaron 36 el 20/11/2026, antes de agregar las de `secmcp.quality`.
- Compuerta de evals, incluida la mutación que la hace fallar: sin defensa 6/7 fugas, con Guard 0/7, tareas legítimas 3/3.
- `secmcp-server` por stdio con el cliente de la SDK de MCP: lista las cuatro herramientas y bloquea una salida a un destino no permitido.
- **`secmcp-server` con MCP Inspector** (cliente de referencia de MCP, v2.16, Windows, 22/11/2026): descubre las cuatro herramientas; `search_docs` devuelve la política; `send_report` se bloquea a un destino fuera de la lista blanca y ante un canario en el cuerpo; `read_private_note` rechaza un recorrido de rutas; y en una sesión que leyó contenido no confiable y luego una nota privada, `send_report` a un destino permitido con un cuerpo inocente se bloquea con `BLOQUEADO (lethal-trifecta): la sesión tiene datos privados y contenido no confiable`.
- **GPU (T4):** `TransformersBackend` en fp16 y en 4 bits, carga, memoria, latencia y rendimiento (tabla de arriba), 0 errores en las corridas medidas.
- **Calidad en 4 bits** (perplejidad en español y comportamiento como agente sobre 24 pedidos): sin diferencia detectable en el agente; muestras chicas (tabla de arriba).
- **Terraform `plan`** contra GCP real (21/11/2026, proyecto de prueba, credenciales reales): `Plan: 3 to add, 0 to change, 0 to destroy` (cuenta de servicio, regla de firewall y VM spot con T4). No se aplicó; `plan` no comprueba cuotas ni disponibilidad.
- **Windows** (cmd, entorno virtual de Python): las 43 pruebas pasan, y el servicio con backend simulado (`/healthz`, `/readyz`) y el benchmark por HTTP contra él (20 pedidos, 4 en paralelo: p50 0,049 s; cifras del backend simulado, no de un modelo).
- **vLLM en la T4:** arranca y sirve el mismo modelo; benchmark con 1, 4 y 8 pedidos en paralelo contra el servicio de transformers (una corrida cada uno).
- **CI en GitHub** (todos los jobs verdes): pruebas en Python 3.10 y 3.12, `ruff`, compuerta de evals, construcción de la imagen CPU, prueba de humo del contenedor, escaneo con Trivy (sin hallazgos HIGH/CRITICAL corregibles), `terraform fmt`, `init` y `validate`, y construcción de la imagen GPU.
- El servicio con uvicorn y el benchmark por HTTP, con el backend simulado y con el modelo real.

**No verificado:**
- **Terraform `apply`:** no se ejecutó. Cuesta dinero (no hay GPU gratuita en la nube) y es lo que detectaría los problemas que `plan` no ve: cuota de GPU, disponibilidad de la T4 en la zona y vigencia de la familia de imagen de Deep Learning VM (`common-cu124-ubuntu-2204`). Tampoco se verificó el script de arranque de la VM ni que el contenedor GPU corra en ella.
- **La imagen GPU ejecutada con GPU:** se construye en CI, pero no se corrió el contenedor con la GPU ni se escaneó con Trivy.
- **Calidad en 4 bits a mayor escala** (perplejidad en inglés no obtenida; pocos pedidos) y **robustez de modelos reales ante la inyección:** el demo es una corrida con un modelo chico.
- **Un asistente de producto** contra `secmcp-server`: se probó con la SDK de MCP y con MCP Inspector, no con un asistente real que decida solo qué herramientas llamar.

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
tests/        43 pruebas (pytest)
infra/        terraform (GCP, VM spot con GPU)
notebooks/    colab_gpu.ipynb
docs/         threat_model.md · serving.md
.github/      CI
```

## Autor
Fernando León Moloney — Ingeniero en Sistemas. Licencia MIT.
