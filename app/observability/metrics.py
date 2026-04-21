"""Prometheus collectors with a graceful no-op fallback.

If ``prometheus_client`` isn't installed, every helper becomes a no-op so
the rest of the code never has to branch on availability.
"""

from __future__ import annotations

from typing import Any

try:
    from prometheus_client import (  # type: ignore[import-untyped]
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Histogram,
        generate_latest,
    )

    METRICS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised in environments without the dep
    METRICS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain"

    class _NoopMetric:
        def labels(self, *args: Any, **kwargs: Any) -> _NoopMetric:
            return self

        def inc(self, *args: Any, **kwargs: Any) -> None:
            return None

        def observe(self, *args: Any, **kwargs: Any) -> None:
            return None

    Counter = Histogram = _NoopMetric  # type: ignore[assignment]
    CollectorRegistry = object  # type: ignore[assignment]

    def generate_latest(_registry: Any = None) -> bytes:
        return b""


# A dedicated registry so tests can introspect / reset.
REGISTRY = CollectorRegistry() if METRICS_AVAILABLE else None  # type: ignore[call-arg]


if METRICS_AVAILABLE:
    REPORT_RUNS = Counter(
        "report_runs_total",
        "Number of report runs by status.",
        labelnames=("report_name", "status"),
        registry=REGISTRY,
    )
    REPORT_DURATION = Histogram(
        "report_duration_seconds",
        "End-to-end duration of a report execution.",
        labelnames=("report_name",),
        registry=REGISTRY,
    )
    CARDS_SENT = Counter(
        "cards_sent_total",
        "Number of card-image sends by destination and outcome.",
        labelnames=("destination", "status"),
        registry=REGISTRY,
    )
else:
    REPORT_RUNS = Counter()
    REPORT_DURATION = Histogram()
    CARDS_SENT = Counter()


def record_run_status(report_name: str, status: str) -> None:
    REPORT_RUNS.labels(report_name=report_name, status=status).inc()


def observe_run_duration(report_name: str, duration_seconds: float) -> None:
    REPORT_DURATION.labels(report_name=report_name).observe(duration_seconds)


def observe_card_send(destination: str, success: bool) -> None:
    CARDS_SENT.labels(destination=destination, status="success" if success else "failure").inc()


def render_text() -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for an HTTP exposition endpoint."""

    if not METRICS_AVAILABLE:
        return b"# prometheus_client not installed\n", "text/plain"
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
