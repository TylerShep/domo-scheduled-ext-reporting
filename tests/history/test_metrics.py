"""Tests for the Prometheus metric collectors."""

from __future__ import annotations

import pytest

from app.observability import metrics


@pytest.mark.skipif(not metrics.METRICS_AVAILABLE, reason="prometheus_client is not installed")
def test_record_run_status_increments_counter():
    metrics.record_run_status("foo", "success")
    body, content_type = metrics.render_text()
    assert b"report_runs_total" in body
    assert b"foo" in body
    assert b"success" in body
    assert "openmetrics" in content_type or "text" in content_type


@pytest.mark.skipif(not metrics.METRICS_AVAILABLE, reason="prometheus_client is not installed")
def test_observe_run_duration_creates_histogram_buckets():
    metrics.observe_run_duration("foo", 0.42)
    body, _ = metrics.render_text()
    assert b"report_duration_seconds_bucket" in body


@pytest.mark.skipif(not metrics.METRICS_AVAILABLE, reason="prometheus_client is not installed")
def test_observe_card_send_records_destination_status():
    metrics.observe_card_send("slack", success=True)
    metrics.observe_card_send("teams", success=False)
    body, _ = metrics.render_text()
    assert b"cards_sent_total" in body


def test_render_text_returns_bytes_even_when_unavailable(monkeypatch):
    monkeypatch.setattr(metrics, "METRICS_AVAILABLE", False)
    body, content_type = metrics.render_text()
    assert isinstance(body, bytes)
    assert content_type.startswith("text/plain")
