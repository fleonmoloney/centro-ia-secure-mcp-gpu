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
| Cuantización de 4 bits como opción | Cabe en GPU chicas. Medido en la T4 con Qwen2.5-1.5B: −61 % de memoria, ~2,3 veces más lenta, sin diferencia detectable en el comportamiento como agente con 24 pedidos (ver README); la calidad hay que medirla en la tarea propia |
| Errores sin detalle al cliente | No exponer trazas ni rutas |

## Límites
- **Sin batching continuo**: cada pedido ocupa la GPU en serie. Con concurrencia, la latencia sube linealmente (medido en una T4: p50 0,87 → 3,4 → 6,9 s con 1, 4 y 8 pedidos en paralelo, con el rendimiento total plano en ~29 tokens/s). Para carga real se usa vLLM o TGI; la API es la misma. En la misma T4, vLLM 0.34 dio ~62, ~201 y ~306 tokens/s con 1, 4 y 8 pedidos en paralelo (una corrida; ver README).
- **Métricas en memoria** de un proceso.
- **Sin TLS ni límite por cliente**: va detrás de un gateway o de un túnel.
- Las cifras de latencia del README son de una corrida en una GPU concreta.

## Estimar el costo
Costo por millón de tokens ≈ (costo por hora de la GPU) / (tokens por segundo × 3600) × 1.000.000, con los tokens por segundo medidos con
`secmcp-bench` y la utilización real esperada. Con la T4 gratuita de Colab el costo es cero y la disponibilidad no está garantizada.

Ejemplo con las cifras medidas en la T4 (una corrida cada una): a 29 tokens/s, transformers produce ~104 mil tokens por hora; vLLM con 8 pedidos en paralelo, a ~306 tokens/s, produce ~1,1 millones. Con el mismo precio por hora de la GPU, el costo por token es unas 10 veces menor con vLLM, siempre que haya suficiente tráfico concurrente para aprovechar el batching: con un solo usuario la diferencia es de ~2 veces (62 contra 29 tokens/s).
