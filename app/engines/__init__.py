"""Pluggable Domo engines.

The "engine" is the thing that actually talks to Domo. Two implementations
ship with the project:

    * :mod:`app.engines.rest` -- native HTTPS via the Domo REST API.
      Default for v2 because it has zero runtime dependencies (no JRE).
    * :mod:`app.engines.jar`  -- shells out to ``domoUtil.jar`` (legacy).

Pick one at runtime by setting ``DOMO_ENGINE`` (``rest`` | ``jar`` | ``auto``).
Both engines implement the same :class:`~app.engines.base.DomoEngine` ABC so
that everything downstream (services, destinations, web UI) is engine-agnostic.
"""

from app.engines.base import (
    CardImageRequest,
    CardSummary,
    DomoEngine,
    DomoEngineError,
)
from app.engines.registry import (
    available_engines,
    get_engine,
    register_engine,
    reset_engine_cache,
)

__all__ = [
    "CardImageRequest",
    "CardSummary",
    "DomoEngine",
    "DomoEngineError",
    "available_engines",
    "get_engine",
    "register_engine",
    "reset_engine_cache",
]
