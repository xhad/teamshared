# Queue & capture observability (Stage 4.3)

## Metrics (`GET /metrics`)

| Metric | Labels | Meaning |
|--------|--------|---------|
| `teamshared_queue_depth` | `stream=distill\|curate` | Pending jobs in Redis lists |
| `teamshared_queue_dead_letter_depth` | `stream=distill\|curate` | Poison/failed jobs |
| `teamshared_queue_pending_depth` | `stream=curate` | Subjects debounced before curation |
| `teamshared_capture_recorded_total` | `capability`, `source` | Turns recorded |
| `teamshared_job_signature_invalid_total` | `queue` | HMAC rejections (4.1) |

Gauges refresh on every `/metrics` scrape and on a background poll
(`TEAMSHARED_OBSERVABILITY_POLL_SECONDS`, default 30).

## Health (`GET /health`)

The response includes a `queues` object with depths and an `alerts` array.
Overall `status` becomes `degraded` when:

- Any dead-letter queue is non-empty, or
- Distill/curate depth ≥ `TEAMSHARED_QUEUE_DEPTH_CRITICAL_THRESHOLD` (default 500)

Warnings (depth ≥ warn threshold, default 100) set `components.queues` to `warning`
without degrading overall status unless another component is unhealthy.

## Prometheus alerts

Copy rules from [`../prometheus/teamshared-alerts.yml`](../prometheus/teamshared-alerts.yml)
into your Prometheus config. Tune thresholds to match
`TEAMSHARED_QUEUE_DEPTH_WARN_THRESHOLD` / `CRITICAL_THRESHOLD`.

## Triage

1. **Distill backlog** — confirm distiller container (`teamshared worker`), Redis
   heartbeat key, Ollama/LLM errors in logs.
2. **Dead letter** — inspect JSON entries in `working:distill:dead` / `working:curate:dead`.
3. **Signature invalid** — rotate/sync `TEAMSHARED_JOB_SIGNING_SECRET` on server + workers.
