"""/healthz + /metrics should be reachable without a session."""

from __future__ import annotations


def test_healthz_returns_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_metrics_returns_text(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    # Either the prometheus exposition format or our no-op fallback.
    assert resp.text is not None
    ct = resp.headers["content-type"]
    assert "text/plain" in ct or "application/openmetrics-text" in ct
