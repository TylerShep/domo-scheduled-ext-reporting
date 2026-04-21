"""No-op history backend.

Use ``RUN_HISTORY_BACKEND=null`` to disable history entirely. Useful for
ephemeral / one-shot workloads where storing every run would be overkill.
"""

from __future__ import annotations

from app.history.base import HistoryBackend, RunRecord


class NullHistoryBackend(HistoryBackend):
    """Drops every record on the floor. ``get_*`` always returns empty."""

    def record_run(self, run: RunRecord) -> None:
        return None

    def get_runs(
        self,
        report_name: str | None = None,
        limit: int = 50,
    ) -> list[RunRecord]:
        return []

    def get_run(self, run_id: str) -> RunRecord | None:
        return None
