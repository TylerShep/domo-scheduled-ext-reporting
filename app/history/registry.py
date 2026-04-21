"""Backend factory + context-manager helper.

Use :func:`record` to wrap a report execution. The context manager:

    1. Creates a :class:`RunRecord` in ``RUNNING`` state.
    2. Yields it so the caller can append cards/destinations.
    3. Persists the final record on ``__exit__`` with the right status,
       even if the body raised.

Example::

    from app.history import record, CardOutcome

    with record("daily_kpis") as run:
        run.cards.append(CardOutcome(card_name="Revenue", sent=True))
        ...
"""

from __future__ import annotations

import contextlib
import traceback
from collections.abc import Callable, Iterator

from app.configuration.settings import get_env
from app.history.base import HistoryBackend, RunRecord, RunStatus
from app.history.null import NullHistoryBackend
from app.history.sqlite import SqliteHistoryBackend
from app.utils.logger import get_logger

logger = get_logger(__name__)


BackendFactory = Callable[[], HistoryBackend]


_FACTORIES: dict[str, BackendFactory] = {
    "sqlite": SqliteHistoryBackend,
    "null": NullHistoryBackend,
}

_cached_backend: HistoryBackend | None = None


def register_backend(key: str, factory: BackendFactory) -> None:
    _FACTORIES[key.lower()] = factory


def available_backends() -> list[str]:
    keys = set(_FACTORIES.keys())
    keys.add("postgres")  # always advertised even if not installed
    return sorted(keys)


def reset_backend_cache() -> None:
    """Drop the cached singleton (mostly for tests)."""

    global _cached_backend
    _cached_backend = None


def get_backend() -> HistoryBackend:
    global _cached_backend
    if _cached_backend is not None:
        return _cached_backend

    requested = (get_env("RUN_HISTORY_BACKEND", default="sqlite") or "sqlite").lower()

    if requested == "postgres":
        from app.history.postgres import PostgresHistoryBackend

        dsn = get_env("RUN_HISTORY_POSTGRES_DSN", required=True)
        backend: HistoryBackend = PostgresHistoryBackend(dsn)
    else:
        factory = _FACTORIES.get(requested)
        if factory is None:
            known = available_backends()
            raise ValueError(f"Unknown RUN_HISTORY_BACKEND={requested!r}; expected one of {known}")
        backend = factory()

    logger.info("Run history backend: %s", backend.__class__.__name__)
    _cached_backend = backend
    return backend


@contextlib.contextmanager
def record(report_name: str) -> Iterator[RunRecord]:
    """Wrap a report execution and persist the resulting :class:`RunRecord`."""

    backend = get_backend()
    run = RunRecord(report_name=report_name)
    backend.record_run(run)
    try:
        yield run
    except Exception as exc:
        run.mark_finished(RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
        run.log_excerpt = traceback.format_exc()[-4000:]
        backend.record_run(run)
        raise

    if run.status == RunStatus.RUNNING:
        # Caller didn't set a terminal status; infer from card/destination data.
        run.mark_finished(_infer_status(run))
    backend.record_run(run)


def _infer_status(run: RunRecord) -> RunStatus:
    if not run.cards and not run.destinations:
        return RunStatus.SKIPPED
    failures = sum(1 for c in run.cards if c.error)
    successes = sum(1 for c in run.cards if c.sent)
    if failures == 0:
        return RunStatus.SUCCESS
    if successes == 0:
        return RunStatus.FAILED
    return RunStatus.PARTIAL
