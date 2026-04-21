"""Tests for the history backend registry + ``record`` context manager."""

from __future__ import annotations

import pytest

from app.history import (
    CardOutcome,
    RunStatus,
    available_backends,
    get_backend,
    record,
    reset_backend_cache,
)
from app.history.null import NullHistoryBackend
from app.history.sqlite import SqliteHistoryBackend


@pytest.fixture(autouse=True)
def _reset():
    reset_backend_cache()
    yield
    reset_backend_cache()


def test_default_backend_is_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_HISTORY_BACKEND", "sqlite")
    monkeypatch.setenv("RUN_HISTORY_DB_PATH", str(tmp_path / "runs.db"))
    backend = get_backend()
    assert isinstance(backend, SqliteHistoryBackend)


def test_null_backend_when_requested(monkeypatch):
    monkeypatch.setenv("RUN_HISTORY_BACKEND", "null")
    backend = get_backend()
    assert isinstance(backend, NullHistoryBackend)


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("RUN_HISTORY_BACKEND", "wat")
    with pytest.raises(ValueError, match="Unknown RUN_HISTORY_BACKEND"):
        get_backend()


def test_postgres_advertised_even_if_uninstalled():
    assert "postgres" in available_backends()


def test_record_marks_success_when_no_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_HISTORY_DB_PATH", str(tmp_path / "runs.db"))
    monkeypatch.setenv("RUN_HISTORY_BACKEND", "sqlite")

    with record("alpha") as run:
        run.cards.append(CardOutcome(card_name="A", sent=True))

    backend = get_backend()
    runs = backend.get_runs(report_name="alpha")
    assert len(runs) == 1
    assert runs[0].status == RunStatus.SUCCESS


def test_record_marks_partial_when_some_failed(monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_HISTORY_DB_PATH", str(tmp_path / "runs.db"))
    monkeypatch.setenv("RUN_HISTORY_BACKEND", "sqlite")

    with record("alpha") as run:
        run.cards.append(CardOutcome(card_name="A", sent=True))
        run.cards.append(CardOutcome(card_name="B", sent=False, error="boom"))

    runs = get_backend().get_runs(report_name="alpha")
    assert runs[0].status == RunStatus.PARTIAL


def test_record_marks_failed_when_all_failed(monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_HISTORY_DB_PATH", str(tmp_path / "runs.db"))
    monkeypatch.setenv("RUN_HISTORY_BACKEND", "sqlite")

    with record("alpha") as run:
        run.cards.append(CardOutcome(card_name="A", sent=False, error="boom"))

    runs = get_backend().get_runs(report_name="alpha")
    assert runs[0].status == RunStatus.FAILED


def test_record_captures_exception_and_reraises(monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_HISTORY_DB_PATH", str(tmp_path / "runs.db"))
    monkeypatch.setenv("RUN_HISTORY_BACKEND", "sqlite")

    with pytest.raises(RuntimeError):
        with record("alpha"):
            raise RuntimeError("kaboom")

    runs = get_backend().get_runs(report_name="alpha")
    assert runs[0].status == RunStatus.FAILED
    assert "kaboom" in runs[0].error
    assert runs[0].log_excerpt is not None
