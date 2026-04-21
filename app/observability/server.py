"""Optional standalone Prometheus exposition server.

Use when you don't have the web UI running but still want a /metrics
endpoint. The web UI (Wave 13) mounts the same metrics under its own
``/metrics`` route.
"""

from __future__ import annotations

from app.utils.logger import get_logger

logger = get_logger(__name__)


def start_metrics_server(port: int) -> None:
    """Start an HTTP server exposing the global registry at ``/``.

    No-ops with a warning if ``prometheus_client`` isn't installed.
    """

    try:
        from prometheus_client import start_http_server  # type: ignore[import-untyped]
    except ImportError:
        logger.warning(
            "prometheus_client is not installed; metrics server disabled. "
            'Install with `pip install "domo-scheduled-ext-reporting[metrics]"`.'
        )
        return

    from app.observability.metrics import REGISTRY

    start_http_server(port, registry=REGISTRY)
    logger.info("Prometheus metrics server listening on :%d", port)
