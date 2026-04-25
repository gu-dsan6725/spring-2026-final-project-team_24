# Observability (HTTP monitoring)

Runtime probes and optional **Prometheus** metrics for the FastAPI app. No separate collector process is bundled; scrape `/metrics` with Prometheus or compatible tools.

## Endpoints

| Path | When | Response |
|---|---|---|
| `GET /health` | Always | `{"status": "ok"}` — liveness (process up) |
| `GET /ready` | Always | `{"status": "ok"}` — readiness placeholder (extend later with DB checks) |
| `GET /metrics` | Only if enabled | Prometheus text exposition format |

## Configuration

Set in repo root `.env` (see [`app/config.py`](../app/config.py)):

| Variable | Default | Meaning |
|---|---|---|
| `PROMETHEUS_METRICS_ENABLED` | `false` | When `true`, registers `/metrics` and instruments HTTP handlers |
| `PROMETHEUS_METRICS_PATH` | `/metrics` | Path for the scrape endpoint |

**Restart** the API process after changing these variables.

## Implementation

| File | Role |
|---|---|
| [`app/monitoring.py`](../app/monitoring.py) | Attaches `/health`, `/ready`; wires [`prometheus-fastapi-instrumentator`](https://github.com/trallnag/prometheus-fastapi-instrumentator) when enabled. The metrics route is excluded from request histograms to avoid self-scrape noise. |
| [`app/main.py`](../app/main.py) | Calls `attach_health_routes` then `configure_prometheus` after the v1 router is mounted. |
| [`tests/test_monitoring.py`](../tests/test_monitoring.py) | Asserts health/ready; builds a minimal app with metrics enabled to assert `/metrics` returns Prometheus body. |

Dependency: `prometheus-fastapi-instrumentator` in `requirements.txt`.

## Verify locally

```bash
# Automated
pytest tests/test_monitoring.py -v

# Manual (with PROMETHEUS_METRICS_ENABLED=true and server running)
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/metrics | head -20
```

With metrics **disabled**, `GET /metrics` returns **404** (`{"detail":"Not Found"}`).

## Prometheus scrape (example)

```yaml
scrape_configs:
  - job_name: knowledge-api
    static_configs:
      - targets: ["host.docker.internal:8000"]  # adjust for your deploy
    metrics_path: /metrics
```

## Future extensions

- **Readiness**: ping Postgres/Mongo in `/ready` before returning 200.
- **Business metrics**: counters/histograms for LLM calls (latency, tokens) via `prometheus_client` in provider or pipeline code.
- **Tracing**: OpenTelemetry export alongside or instead of Prometheus-only views.
