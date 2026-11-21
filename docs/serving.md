# Servicio de modelos

## Lo que hay
`secmcp.serving.app`: API compatible con OpenAI (`/v1/chat/completions`), `/healthz` (liveness), `/readyz` (el modelo cargó),
`/metrics` (formato Prometheus), `/v1/info` (GPU, memoria, p50/p95/p99, tokens por segundo).
Backends: `mock` (CI) y `transformers` (fp16 o 4 bits con bitsandbytes).

## Decisiones
| Decisión | Motivo |
|---|---|
| Liveness distinto de readiness | La carga del modelo tarda; el orquestador no debe enviar tráfico antes |
| Un semáforo serializa el acceso a la GPU | Un solo proceso de generación por GPU; evita agotar memoria |
| Tope de `max_tokens` y de tamaño de entrada | Acota costo y latencia por pedido |
| Clave de API opcional con comparación en tiempo constante | Mínimo de control de acceso; no reemplaza TLS ni un gateway |
| Cuantización de 4 bits como opción | Cabe en GPU chicas; cambia calidad: hay que medirla en la tarea propia |
| Errores sin detalle al cliente | No exponer trazas ni rutas |

## Límites
- **Sin batching continuo**: cada pedido ocupa la GPU en serie. Con concurrencia, la latencia sube linealmente. Para carga real se usa vLLM o TGI (el notebook trae el paso opcional); la API es la misma.
- **Métricas en memoria** de un proceso.
- **Sin TLS ni límite por cliente**: va detrás de un gateway o de un túnel.
- Las cifras de latencia del README son de una corrida en una GPU concreta.

## Estimar el costo
Costo por millón de tokens ≈ (costo por hora de la GPU) / (tokens por segundo × 3600) × 1.000.000, con los tokens por segundo medidos con
`secmcp-bench` y la utilización real esperada. Con la T4 gratuita de Colab el costo es cero y la disponibilidad no está garantizada.
