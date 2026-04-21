"""Run history backends.

Every report execution emits a :class:`RunRecord` to the configured
backend. The web UI, alert evaluator, and ``--doctor`` command all read
from this same store.

Backends:
    * :class:`~app.history.sqlite.SqliteHistoryBackend` -- default.
    * :class:`~app.history.postgres.PostgresHistoryBackend` -- optional
      (`pip install ".[postgres]"`).
    * :class:`~app.history.null.NullHistoryBackend` -- silently drops
      everything; pick this if you really don't care.
"""

from app.history.base import (
    CardOutcome,
    DestinationOutcome,
    HistoryBackend,
    RunRecord,
    RunStatus,
)
from app.history.registry import (
    available_backends,
    get_backend,
    record,
    register_backend,
    reset_backend_cache,
)

__all__ = [
    "CardOutcome",
    "DestinationOutcome",
    "HistoryBackend",
    "RunRecord",
    "RunStatus",
    "available_backends",
    "get_backend",
    "record",
    "register_backend",
    "reset_backend_cache",
]
