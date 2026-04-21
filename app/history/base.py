"""Base data classes + abstract backend for run history.

A "run" is one invocation of :meth:`DomoBase.execute_service`. Every run
produces exactly one :class:`RunRecord`, plus zero-or-more
:class:`CardOutcome` and :class:`DestinationOutcome` rows that detail what
happened to each card / destination during that run.
"""

from __future__ import annotations

import datetime as _dt
import enum
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class RunStatus(str, enum.Enum):
    """Terminal status for a run."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    RUNNING = "running"

    def is_terminal(self) -> bool:
        return self != RunStatus.RUNNING


@dataclass
class CardOutcome:
    """Per-card detail recorded during a run."""

    card_name: str
    card_id: int | None = None
    page_name: str | None = None
    image_path: str | None = None
    sent: bool = False
    error: str | None = None
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class DestinationOutcome:
    """Per-destination detail recorded during a run."""

    destination_label: str
    destination_type: str
    cards_attempted: int = 0
    cards_sent: int = 0
    cards_skipped: int = 0
    error: str | None = None


def _utcnow() -> _dt.datetime:
    """Naive-UTC ``datetime`` -- compatible with SQLite text storage."""

    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


@dataclass
class RunRecord:
    """One execution of a report."""

    report_name: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: _dt.datetime = field(default_factory=_utcnow)
    finished_at: _dt.datetime | None = None
    status: RunStatus = RunStatus.RUNNING
    error: str | None = None
    log_excerpt: str | None = None
    cards: list[CardOutcome] = field(default_factory=list)
    destinations: list[DestinationOutcome] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    # ---- duration helpers ----

    def duration_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    # ---- mutators ----

    def mark_finished(self, status: RunStatus, error: str | None = None) -> None:
        self.finished_at = _utcnow()
        self.status = status
        if error:
            self.error = error[:5000]


class HistoryBackend(ABC):
    """Persistent store for :class:`RunRecord` objects."""

    @abstractmethod
    def record_run(self, run: RunRecord) -> None:
        """Persist (or upsert) a single run."""

    @abstractmethod
    def get_runs(
        self,
        report_name: str | None = None,
        limit: int = 50,
    ) -> list[RunRecord]:
        """Return up to ``limit`` runs, newest first."""

    @abstractmethod
    def get_run(self, run_id: str) -> RunRecord | None:
        """Fetch a single run, or return ``None`` if it doesn't exist."""

    def cleanup(self, older_than: _dt.timedelta) -> int:
        """Delete runs older than ``older_than``. Returns rows removed.

        Default: no-op for backends that don't support deletion.
        """

        return 0

    def last_value(self, report_name: str, card_name: str) -> float | None:
        """Return the last successfully-sent numeric value for a card.

        Used by Wave 10 alerts to compute deltas. Default: ``None`` so
        backends that don't track values gracefully degrade.
        """

        return None
