"""SQLite-backed run history (the default).

Schema lives in :mod:`app.history.sqlite._SCHEMA`. The DB file is created
on first use (default path: ``app/state/runs.db``, override with
``RUN_HISTORY_DB_PATH``). All queries go through parametrized SQL.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from app.configuration.settings import get_env
from app.history.base import (
    CardOutcome,
    DestinationOutcome,
    HistoryBackend,
    RunRecord,
    RunStatus,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    report_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    error TEXT,
    log_excerpt TEXT,
    extras_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_report_started
    ON runs(report_name, started_at DESC);

CREATE TABLE IF NOT EXISTS run_cards (
    run_id TEXT NOT NULL,
    card_name TEXT NOT NULL,
    card_id INTEGER,
    page_name TEXT,
    image_path TEXT,
    sent INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    value REAL,
    skipped INTEGER NOT NULL DEFAULT 0,
    skip_reason TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_cards_run_id ON run_cards(run_id);
CREATE INDEX IF NOT EXISTS idx_run_cards_value
    ON run_cards(card_name, sent, value);

CREATE TABLE IF NOT EXISTS run_destinations (
    run_id TEXT NOT NULL,
    destination_label TEXT NOT NULL,
    destination_type TEXT NOT NULL,
    cards_attempted INTEGER DEFAULT 0,
    cards_sent INTEGER DEFAULT 0,
    cards_skipped INTEGER DEFAULT 0,
    error TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_destinations_run_id
    ON run_destinations(run_id);
"""


#: ``(table, column, type, default)`` tuples for additive migrations
#: applied on top of :data:`_SCHEMA` so users upgrading from v1 don't have
#: to nuke their history DB.
_MIGRATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("run_cards", "skipped", "INTEGER", "0"),
    ("run_cards", "skip_reason", "TEXT", "NULL"),
    ("run_destinations", "cards_skipped", "INTEGER", "0"),
)


class SqliteHistoryBackend(HistoryBackend):
    """File-backed SQLite implementation -- safe for single-process use."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        path = Path(db_path) if db_path else _default_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = threading.Lock()
        self._init_schema()

    @property
    def path(self) -> Path:
        return self._path

    # ---- HistoryBackend ----

    def record_run(self, run: RunRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(id, report_name, started_at, finished_at, status,
                                 error, log_excerpt, extras_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    finished_at = excluded.finished_at,
                    status = excluded.status,
                    error = excluded.error,
                    log_excerpt = excluded.log_excerpt,
                    extras_json = excluded.extras_json
                """,
                (
                    run.id,
                    run.report_name,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat() if run.finished_at else None,
                    run.status.value,
                    run.error,
                    run.log_excerpt,
                    json.dumps(run.extras) if run.extras else None,
                ),
            )
            conn.execute("DELETE FROM run_cards WHERE run_id = ?", (run.id,))
            conn.execute("DELETE FROM run_destinations WHERE run_id = ?", (run.id,))
            for card in run.cards:
                conn.execute(
                    """
                    INSERT INTO run_cards(run_id, card_name, card_id, page_name,
                                          image_path, sent, error, value,
                                          skipped, skip_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.id,
                        card.card_name,
                        card.card_id,
                        card.page_name,
                        card.image_path,
                        1 if card.sent else 0,
                        card.error,
                        run.extras.get(f"value::{card.card_name}"),
                        1 if card.skipped else 0,
                        card.skip_reason,
                    ),
                )
            for dest in run.destinations:
                conn.execute(
                    """
                    INSERT INTO run_destinations(run_id, destination_label,
                                                 destination_type, cards_attempted,
                                                 cards_sent, cards_skipped, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.id,
                        dest.destination_label,
                        dest.destination_type,
                        dest.cards_attempted,
                        dest.cards_sent,
                        dest.cards_skipped,
                        dest.error,
                    ),
                )
            conn.commit()

    def get_runs(
        self,
        report_name: str | None = None,
        limit: int = 50,
    ) -> list[RunRecord]:
        with self._connect() as conn:
            if report_name:
                cursor = conn.execute(
                    """
                    SELECT * FROM runs
                    WHERE report_name = ?
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (report_name, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                )
            rows = cursor.fetchall()
            return [self._hydrate(conn, row) for row in rows]

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            return self._hydrate(conn, row)

    def cleanup(self, older_than: _dt.timedelta) -> int:
        from app.history.base import _utcnow

        cutoff = (_utcnow() - older_than).isoformat()
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM runs WHERE started_at < ?", (cutoff,))
            conn.commit()
            return cursor.rowcount or 0

    def last_value(self, report_name: str, card_name: str) -> float | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT rc.value FROM run_cards rc
                JOIN runs r ON r.id = rc.run_id
                WHERE r.report_name = ?
                  AND rc.card_name = ?
                  AND rc.sent = 1
                  AND rc.value IS NOT NULL
                ORDER BY r.started_at DESC
                LIMIT 1
                """,
                (report_name, card_name),
            ).fetchone()
            return float(row["value"]) if row else None

    # ---- internals ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)
            for table, column, coltype, default in _MIGRATIONS:
                self._ensure_column(conn, table, column, coltype, default)
            conn.commit()

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        table: str,
        column: str,
        coltype: str,
        default: str,
    ) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column in existing:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype} DEFAULT {default}")

    def _hydrate(self, conn: sqlite3.Connection, row: sqlite3.Row) -> RunRecord:
        cards = [
            CardOutcome(
                card_name=r["card_name"],
                card_id=r["card_id"],
                page_name=r["page_name"],
                image_path=r["image_path"],
                sent=bool(r["sent"]),
                error=r["error"],
                skipped=bool(_row_get(r, "skipped")),
                skip_reason=_row_get(r, "skip_reason"),
            )
            for r in conn.execute(
                "SELECT * FROM run_cards WHERE run_id = ? ORDER BY rowid",
                (row["id"],),
            ).fetchall()
        ]
        destinations = [
            DestinationOutcome(
                destination_label=r["destination_label"],
                destination_type=r["destination_type"],
                cards_attempted=r["cards_attempted"],
                cards_sent=r["cards_sent"],
                cards_skipped=_row_get(r, "cards_skipped") or 0,
                error=r["error"],
            )
            for r in conn.execute(
                "SELECT * FROM run_destinations WHERE run_id = ? ORDER BY rowid",
                (row["id"],),
            ).fetchall()
        ]
        extras = json.loads(row["extras_json"]) if row["extras_json"] else {}
        return RunRecord(
            id=row["id"],
            report_name=row["report_name"],
            started_at=_dt.datetime.fromisoformat(row["started_at"]),
            finished_at=(
                _dt.datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None
            ),
            status=RunStatus(row["status"]),
            error=row["error"],
            log_excerpt=row["log_excerpt"],
            cards=cards,
            destinations=destinations,
            extras=extras,
        )


def _default_db_path() -> Path:
    """Return the default SQLite path (``app/state/runs.db``)."""

    override = get_env("RUN_HISTORY_DB_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "state" / "runs.db"


def _row_get(row: sqlite3.Row, key: str) -> Any:
    """Tolerant row lookup -- returns ``None`` for legacy rows missing a column."""

    try:
        return row[key]
    except (IndexError, KeyError):
        return None
