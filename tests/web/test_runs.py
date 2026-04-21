"""Runs view tests.

We seed the SQLite history backend with two synthetic runs and hit the
``/runs`` and ``/runs/{id}`` endpoints as an authenticated user.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.history import (
    CardOutcome,
    DestinationOutcome,
    RunRecord,
)
from app.history.registry import get_backend, reset_backend_cache


@pytest.fixture
def seeded_backend(tmp_path, monkeypatch):
    db_path = tmp_path / "web.db"
    monkeypatch.setenv("RUN_HISTORY_BACKEND", "sqlite")
    monkeypatch.setenv("RUN_HISTORY_DB_PATH", str(db_path))
    reset_backend_cache()
    backend = get_backend()

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    from app.history.base import RunStatus

    backend.record_run(
        RunRecord(
            id="run-1",
            report_name="daily-kpis",
            started_at=now - dt.timedelta(minutes=10),
            finished_at=now - dt.timedelta(minutes=9, seconds=5),
            status=RunStatus.SUCCESS,
            cards=[
                CardOutcome(card_name="KPI A", sent=True),
                CardOutcome(card_name="KPI B", skipped=True, skip_reason="send_when:false"),
            ],
            destinations=[
                DestinationOutcome(
                    destination_label="slack(#demo)",
                    destination_type="slack",
                    cards_attempted=2,
                    cards_sent=1,
                    cards_skipped=1,
                )
            ],
        )
    )
    backend.record_run(
        RunRecord(
            id="run-2",
            report_name="weekly-sales",
            started_at=now - dt.timedelta(minutes=2),
            finished_at=None,
            status=RunStatus.FAILED,
            error="boom",
            cards=[CardOutcome(card_name="Sales", error="boom")],
            destinations=[
                DestinationOutcome(
                    destination_label="teams(Sales)",
                    destination_type="teams",
                    cards_attempted=1,
                    error="boom",
                )
            ],
        )
    )
    yield backend
    reset_backend_cache()


def test_list_runs_renders(auth_client, seeded_backend):
    resp = auth_client.get("/runs")
    assert resp.status_code == 200
    html = resp.text
    assert "daily-kpis" in html
    assert "weekly-sales" in html


def test_filter_by_report(auth_client, seeded_backend):
    resp = auth_client.get("/runs?report=daily-kpis")
    assert resp.status_code == 200
    assert "daily-kpis" in resp.text
    assert "weekly-sales" not in resp.text


def test_show_run_renders_cards(auth_client, seeded_backend):
    resp = auth_client.get("/runs/run-1")
    assert resp.status_code == 200
    html = resp.text
    assert "KPI A" in html
    assert "KPI B" in html


def test_show_run_missing_is_404(auth_client, seeded_backend):
    resp = auth_client.get("/runs/does-not-exist")
    assert resp.status_code == 404
