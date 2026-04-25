"""HTTP observability: liveness/readiness and optional Prometheus metrics."""

from __future__ import annotations

import re

from fastapi import FastAPI

from app.config import settings


def attach_health_routes(app: FastAPI) -> None:
    @app.get("/health", tags=["monitoring"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["monitoring"])
    async def ready() -> dict[str, str]:
        return {"status": "ok"}


def configure_prometheus(app: FastAPI) -> None:
    if not settings.PROMETHEUS_METRICS_ENABLED:
        return

    from prometheus_fastapi_instrumentator import Instrumentator

    path = settings.PROMETHEUS_METRICS_PATH
    skip_metrics_path = f"^{re.escape(path)}$"

    Instrumentator(excluded_handlers=[skip_metrics_path]).instrument(app).expose(
        app,
        endpoint=path,
        include_in_schema=False,
    )
