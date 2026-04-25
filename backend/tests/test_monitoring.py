"""Liveness and optional Prometheus wiring."""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app
from app.monitoring import attach_health_routes, configure_prometheus


def test_health_and_ready() -> None:
    with TestClient(app) as client:
        h = client.get("/health")
        assert h.status_code == 200
        assert h.json() == {"status": "ok"}
        r = client.get("/ready")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_prometheus_metrics_when_enabled() -> None:
    mini = FastAPI()
    attach_health_routes(mini)

    mock = MagicMock()
    mock.PROMETHEUS_METRICS_ENABLED = True
    mock.PROMETHEUS_METRICS_PATH = "/metrics"

    with patch("app.monitoring.settings", mock):
        configure_prometheus(mini)

    with TestClient(mini) as client:
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert b"http" in resp.content.lower() or b"python" in resp.content.lower()
