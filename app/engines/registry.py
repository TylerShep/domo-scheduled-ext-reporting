"""Engine factory + cache.

The active engine is selected by ``DOMO_ENGINE`` (default ``rest``).
It is built lazily on first access and cached for the process lifetime so
the OAuth token can be reused across requests.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable

from app.configuration.settings import get_env
from app.engines.base import DomoEngine, DomoEngineError
from app.engines.jar import JarEngine
from app.engines.rest import RestEngine
from app.utils.logger import get_logger

logger = get_logger(__name__)


EngineFactory = Callable[[], DomoEngine]

_FACTORIES: dict[str, EngineFactory] = {
    "rest": RestEngine,
    "jar": JarEngine,
}

_cached_engine: DomoEngine | None = None


def register_engine(key: str, factory: EngineFactory) -> None:
    """Register or override an engine implementation."""

    _FACTORIES[key.lower()] = factory


def available_engines() -> list[str]:
    return sorted(_FACTORIES.keys()) + ["auto"]


def reset_engine_cache() -> None:
    """Drop the cached singleton (mostly for tests)."""

    global _cached_engine
    _cached_engine = None


def get_engine(force_key: str | None = None) -> DomoEngine:
    """Return the active :class:`DomoEngine`.

    Resolution order:
        1. ``force_key`` argument (used by the doctor / web UI to test).
        2. ``DOMO_ENGINE`` env var.
        3. Default: ``rest``.

    The special key ``auto`` picks ``rest`` if Domo OAuth credentials are
    set, else ``jar`` if ``java`` is on PATH, else raises.
    """

    global _cached_engine
    if _cached_engine is not None and force_key is None:
        return _cached_engine

    requested = (force_key or get_env("DOMO_ENGINE", default="rest") or "rest").lower()

    if requested == "auto":
        requested = _auto_pick()

    factory = _FACTORIES.get(requested)
    if factory is None:
        known = sorted(_FACTORIES.keys())
        raise DomoEngineError(
            f"Unknown DOMO_ENGINE={requested!r}; expected one of {known + ['auto']}."
        )

    engine = factory()
    logger.info("Using Domo engine: %s", engine.describe())
    if force_key is None:
        _cached_engine = engine
    return engine


def _auto_pick() -> str:
    if get_env("DOMO_CLIENT_ID") and get_env("DOMO_CLIENT_SECRET"):
        return "rest"
    if shutil.which("java"):
        return "jar"
    raise DomoEngineError(
        "DOMO_ENGINE=auto could not pick an engine: set DOMO_CLIENT_ID + "
        "DOMO_CLIENT_SECRET for REST, or install a JRE for the JAR engine."
    )
