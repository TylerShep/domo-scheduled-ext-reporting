"""Tests for :class:`NullHistoryBackend`."""

from __future__ import annotations

from app.history.base import RunRecord, RunStatus
from app.history.null import NullHistoryBackend


def _run() -> RunRecord:
    return RunRecord(
        id="run-abc",
        report_name="demo",
        status=RunStatus.SUCCESS,
        cards=[],
        destinations=[],
    )


def test_record_run_returns_none():
    backend = NullHistoryBackend()
    assert backend.record_run(_run()) is None


def test_get_runs_returns_empty_list():
    backend = NullHistoryBackend()
    assert backend.get_runs() == []
    assert backend.get_runs(report_name="demo", limit=10) == []


def test_get_run_returns_none():
    backend = NullHistoryBackend()
    assert backend.get_run("anything") is None
