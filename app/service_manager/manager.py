"""Registry that maps report keys -> :class:`DomoBase` instances.

Reports come from two sources:
    * YAML files in ``config/reports/`` (loaded via :mod:`app.configuration.report_loader`)
    * Python subclasses of :class:`DomoBase` registered programmatically

YAML reports get registered automatically the first time the manager is
initialized. Python subclasses can be added by passing them to
:meth:`ServiceManager.register` (see ``app/services/examples/`` for usage).
"""

from __future__ import annotations

from collections.abc import Iterable

from app.configuration.report_loader import load_yaml_reports
from app.service_manager.exceptions import ServiceManagerException
from app.services.base import DomoBase
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ServiceManager:
    _registry: dict[str, list[DomoBase]] = {}
    _initialized: bool = False

    # ---- registration ----

    @classmethod
    def register(cls, key: str, report: DomoBase) -> None:
        """Register a single report under ``key``."""

        cls._registry.setdefault(key, []).append(report)

    @classmethod
    def register_many(cls, reports: Iterable[DomoBase]) -> None:
        for report in reports:
            cls.register(report.name or report.__class__.__name__, report)

    @classmethod
    def reset(cls) -> None:
        """Clear the registry. Mostly used by tests."""

        cls._registry.clear()
        cls._initialized = False

    # ---- bootstrap ----

    @classmethod
    def _ensure_initialized(cls) -> None:
        if cls._initialized:
            return
        # Load YAML reports.
        cls.register_many(load_yaml_reports())

        # Load any built-in example Python subclasses. The import is wrapped
        # so missing optional examples don't crash the registry.
        try:
            from app.services.examples import register_examples

            register_examples(cls)
        except Exception:
            logger.debug("No Python example reports to register.", exc_info=True)

        cls._initialized = True
        logger.info(
            "ServiceManager initialized with %d report(s): %s",
            len(cls._registry),
            sorted(cls._registry.keys()),
        )

    # ---- accessors ----

    @classmethod
    def get_sync_names(cls) -> list[str]:
        cls._ensure_initialized()
        return sorted(cls._registry.keys())

    @classmethod
    def get_reports(cls, key: str) -> list[DomoBase]:
        cls._ensure_initialized()
        if key not in cls._registry:
            known = sorted(cls._registry.keys())
            raise ServiceManagerException(f"No report registered under {key!r}. Known: {known}")
        return list(cls._registry[key])

    @classmethod
    def all_reports(cls) -> dict[str, list[DomoBase]]:
        cls._ensure_initialized()
        return {k: list(v) for k, v in cls._registry.items()}

    # ---- execution ----

    @classmethod
    def execute(cls, sync_key: str) -> None:
        for report in cls.get_reports(sync_key):
            try:
                report.execute_service()
            except Exception as exc:
                raise ServiceManagerException(f"Report {sync_key!r} failed: {exc}") from exc

    @classmethod
    def execute_all(cls) -> None:
        for key in cls.get_sync_names():
            try:
                cls.execute(key)
            except ServiceManagerException:
                logger.exception("Continuing past failure in %s", key)
