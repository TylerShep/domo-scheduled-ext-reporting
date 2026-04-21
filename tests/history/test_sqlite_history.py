"""Tests for the SQLite history backend."""

from __future__ import annotations

import datetime as _dt

from app.history import (
    CardOutcome,
    DestinationOutcome,
    RunRecord,
    RunStatus,
)
from app.history.sqlite import SqliteHistoryBackend


def _backend(tmp_path):
    return SqliteHistoryBackend(db_path=tmp_path / "runs.db")


def test_record_and_get_round_trip(tmp_path):
    backend = _backend(tmp_path)
    run = RunRecord(report_name="daily")
    run.cards.append(CardOutcome(card_name="Revenue", card_id=1, sent=True))
    run.destinations.append(
        DestinationOutcome(destination_label="slack(#x)", destination_type="slack", cards_sent=1)
    )
    run.mark_finished(RunStatus.SUCCESS)
    backend.record_run(run)

    fetched = backend.get_run(run.id)
    assert fetched is not None
    assert fetched.report_name == "daily"
    assert fetched.status == RunStatus.SUCCESS
    assert len(fetched.cards) == 1
    assert fetched.cards[0].card_name == "Revenue"
    assert len(fetched.destinations) == 1
    assert fetched.destinations[0].cards_sent == 1


def test_record_run_is_idempotent_per_id(tmp_path):
    backend = _backend(tmp_path)
    run = RunRecord(report_name="daily")
    backend.record_run(run)

    run.cards.append(CardOutcome(card_name="A", sent=True))
    run.mark_finished(RunStatus.SUCCESS)
    backend.record_run(run)

    runs = backend.get_runs()
    assert len(runs) == 1
    assert runs[0].status == RunStatus.SUCCESS
    assert len(runs[0].cards) == 1


def test_get_runs_filters_by_report(tmp_path):
    backend = _backend(tmp_path)
    a = RunRecord(report_name="alpha")
    a.mark_finished(RunStatus.SUCCESS)
    b = RunRecord(report_name="beta")
    b.mark_finished(RunStatus.SUCCESS)
    backend.record_run(a)
    backend.record_run(b)

    alpha = backend.get_runs(report_name="alpha")
    assert len(alpha) == 1
    assert alpha[0].report_name == "alpha"


def test_get_runs_returns_newest_first(tmp_path):
    backend = _backend(tmp_path)
    older = RunRecord(report_name="x")
    older.started_at = _dt.datetime(2024, 1, 1)
    older.mark_finished(RunStatus.SUCCESS)
    newer = RunRecord(report_name="x")
    newer.started_at = _dt.datetime(2025, 1, 1)
    newer.mark_finished(RunStatus.SUCCESS)
    backend.record_run(older)
    backend.record_run(newer)

    runs = backend.get_runs(report_name="x")
    assert runs[0].id == newer.id
    assert runs[1].id == older.id


def test_cleanup_deletes_old_rows(tmp_path):
    from app.history.base import _utcnow

    backend = _backend(tmp_path)
    old = RunRecord(report_name="x")
    old.started_at = _utcnow() - _dt.timedelta(days=30)
    old.mark_finished(RunStatus.SUCCESS)
    backend.record_run(old)
    new = RunRecord(report_name="x")
    new.mark_finished(RunStatus.SUCCESS)
    backend.record_run(new)

    removed = backend.cleanup(_dt.timedelta(days=1))
    assert removed == 1
    assert backend.get_run(old.id) is None
    assert backend.get_run(new.id) is not None


def test_last_value_returns_most_recent_sent(tmp_path):
    backend = _backend(tmp_path)
    one = RunRecord(report_name="x", extras={"value::Revenue": 100.0})
    one.cards.append(CardOutcome(card_name="Revenue", sent=True))
    one.mark_finished(RunStatus.SUCCESS)
    one.started_at = _dt.datetime(2025, 1, 1)
    backend.record_run(one)

    two = RunRecord(report_name="x", extras={"value::Revenue": 110.0})
    two.cards.append(CardOutcome(card_name="Revenue", sent=True))
    two.mark_finished(RunStatus.SUCCESS)
    two.started_at = _dt.datetime(2025, 6, 1)
    backend.record_run(two)

    assert backend.last_value("x", "Revenue") == 110.0


def test_schema_creates_indexes(tmp_path):
    backend = _backend(tmp_path)
    with backend._connect() as conn:
        names = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
    assert "idx_runs_report_started" in names
    assert "idx_run_cards_run_id" in names
