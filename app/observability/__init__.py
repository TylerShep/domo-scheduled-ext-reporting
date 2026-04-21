"""Observability primitives.

Prometheus metrics and an optional standalone exporter. All collectors
are wrapped behind a small adapter so the rest of the codebase can call
``record_run_status(...)`` etc. without conditionally importing
``prometheus_client``.
"""

from app.observability.metrics import (
    METRICS_AVAILABLE,
    observe_card_send,
    observe_run_duration,
    record_run_status,
    render_text,
)
from app.observability.server import start_metrics_server

__all__ = [
    "METRICS_AVAILABLE",
    "observe_card_send",
    "observe_run_duration",
    "record_run_status",
    "render_text",
    "start_metrics_server",
]
