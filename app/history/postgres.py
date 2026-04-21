"""Postgres-backed run history (optional).

Install with ``pip install ".[postgres]"`` to pull in ``psycopg[binary]``.
Set ``RUN_HISTORY_BACKEND=postgres`` and ``RUN_HISTORY_POSTGRES_DSN`` to
enable.

Schema mirrors :mod:`app.history.sqlite`. Same logical model, slight
differences in datatypes (``TIMESTAMPTZ`` vs ``TEXT`` for timestamps).
"""

from __future__ import annotations

import datetime as _dt
import json
import threading
from typing import Any

from app.history.base import (
    CardOutcome,
    DestinationOutcome,
    HistoryBackend,
    RunRecord,
    RunStatus,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PostgresHistoryBackendError(RuntimeError):
    """Raised when psycopg isn't installed or the DSN is invalid."""


_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        report_name TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ,
        status TEXT NOT NULL,
        error TEXT,
        log_excerpt TEXT,
        extras JSONB
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_runs_report_started ON runs(report_name, started_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS run_cards (
        run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        card_name TEXT NOT NULL,
        card_id BIGINT,
        page_name TEXT,
        image_path TEXT,
        sent BOOLEAN NOT NULL DEFAULT FALSE,
        error TEXT,
        value DOUBLE PRECISION,
        skipped BOOLEAN NOT NULL DEFAULT FALSE,
        skip_reason TEXT
    )
    """,
    "ALTER TABLE run_cards ADD COLUMN IF NOT EXISTS skipped BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE run_cards ADD COLUMN IF NOT EXISTS skip_reason TEXT",
    "CREATE INDEX IF NOT EXISTS idx_run_cards_run_id ON run_cards(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_run_cards_value ON run_cards(card_name, sent, value)",
    """
    CREATE TABLE IF NOT EXISTS run_destinations (
        run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        destination_label TEXT NOT NULL,
        destination_type TEXT NOT NULL,
        cards_attempted INT DEFAULT 0,
        cards_sent INT DEFAULT 0,
        cards_skipped INT DEFAULT 0,
        error TEXT
    )
    """,
    "ALTER TABLE run_destinations ADD COLUMN IF NOT EXISTS cards_skipped INT DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS idx_run_destinations_run_id ON run_destinations(run_id)",
)


class PostgresHistoryBackend(HistoryBackend):
    """psycopg3-based history backend."""

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # noqa: F401  -- import guard
        except ImportError as exc:
            raise PostgresHistoryBackendError(
                "psycopg is not installed. Run "
                '`pip install "domo-scheduled-ext-reporting[postgres]"`'
            ) from exc
        if not dsn:
            raise PostgresHistoryBackendError(
                "RUN_HISTORY_POSTGRES_DSN is required when RUN_HISTORY_BACKEND=postgres"
            )
        self._dsn = dsn
        self._lock = threading.Lock()
        self._init_schema()

    # ---- HistoryBackend ----

    def record_run(self, run: RunRecord) -> None:
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO runs(id, report_name, started_at, finished_at, status,
                                 error, log_excerpt, extras)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    finished_at = EXCLUDED.finished_at,
                    status = EXCLUDED.status,
                    error = EXCLUDED.error,
                    log_excerpt = EXCLUDED.log_excerpt,
                    extras = EXCLUDED.extras
                """,
                (
                    run.id,
                    run.report_name,
                    run.started_at,
                    run.finished_at,
                    run.status.value,
                    run.error,
                    run.log_excerpt,
                    json.dumps(run.extras) if run.extras else None,
                ),
            )
            cur.execute("DELETE FROM run_cards WHERE run_id = %s", (run.id,))
            cur.execute("DELETE FROM run_destinations WHERE run_id = %s", (run.id,))
            for card in run.cards:
                cur.execute(
                    """
                    INSERT INTO run_cards(run_id, card_name, card_id, page_name,
                                          image_path, sent, error, value,
                                          skipped, skip_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run.id,
                        card.card_name,
                        card.card_id,
                        card.page_name,
                        card.image_path,
                        card.sent,
                        card.error,
                        run.extras.get(f"value::{card.card_name}"),
                        card.skipped,
                        card.skip_reason,
                    ),
                )
            for dest in run.destinations:
                cur.execute(
                    """
                    INSERT INTO run_destinations(run_id, destination_label,
                                                 destination_type, cards_attempted,
                                                 cards_sent, cards_skipped, error)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
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
        with self._connect() as conn, conn.cursor() as cur:
            if report_name:
                cur.execute(
                    "SELECT * FROM runs WHERE report_name = %s "
                    "ORDER BY started_at DESC LIMIT %s",
                    (report_name, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM runs ORDER BY started_at DESC LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall()
            cols = [c.name for c in cur.description] if cur.description else []
            return [self._hydrate(conn, dict(zip(cols, row))) for row in rows]

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM runs WHERE id = %s", (run_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description] if cur.description else []
            return self._hydrate(conn, dict(zip(cols, row)))

    def cleanup(self, older_than: _dt.timedelta) -> int:
        from app.history.base import _utcnow

        cutoff = _utcnow() - older_than
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM runs WHERE started_at < %s", (cutoff,))
            removed = cur.rowcount or 0
            conn.commit()
            return removed

    def last_value(self, report_name: str, card_name: str) -> float | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT rc.value FROM run_cards rc
                JOIN runs r ON r.id = rc.run_id
                WHERE r.report_name = %s
                  AND rc.card_name = %s
                  AND rc.sent = TRUE
                  AND rc.value IS NOT NULL
                ORDER BY r.started_at DESC
                LIMIT 1
                """,
                (report_name, card_name),
            )
            row = cur.fetchone()
            return float(row[0]) if row else None

    # ---- internals ----

    def _connect(self) -> Any:
        import psycopg

        return psycopg.connect(self._dsn)

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            for stmt in _SCHEMA_STATEMENTS:
                cur.execute(stmt)
            conn.commit()

    def _hydrate(self, conn: Any, row: dict[str, Any]) -> RunRecord:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM run_cards WHERE run_id = %s", (row["id"],))
            card_rows = cur.fetchall()
            card_cols = [c.name for c in cur.description] if cur.description else []
            cur.execute("SELECT * FROM run_destinations WHERE run_id = %s", (row["id"],))
            dest_rows = cur.fetchall()
            dest_cols = [c.name for c in cur.description] if cur.description else []

        cards = [
            CardOutcome(
                card_name=d["card_name"],
                card_id=d.get("card_id"),
                page_name=d.get("page_name"),
                image_path=d.get("image_path"),
                sent=bool(d.get("sent")),
                error=d.get("error"),
                skipped=bool(d.get("skipped")),
                skip_reason=d.get("skip_reason"),
            )
            for d in (dict(zip(card_cols, r)) for r in card_rows)
        ]
        destinations = [
            DestinationOutcome(
                destination_label=d["destination_label"],
                destination_type=d["destination_type"],
                cards_attempted=d.get("cards_attempted") or 0,
                cards_sent=d.get("cards_sent") or 0,
                cards_skipped=d.get("cards_skipped") or 0,
                error=d.get("error"),
            )
            for d in (dict(zip(dest_cols, r)) for r in dest_rows)
        ]
        extras = row.get("extras") or {}
        if isinstance(extras, str):
            extras = json.loads(extras)
        return RunRecord(
            id=row["id"],
            report_name=row["report_name"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            status=RunStatus(row["status"]),
            error=row.get("error"),
            log_excerpt=row.get("log_excerpt"),
            cards=cards,
            destinations=destinations,
            extras=extras,
        )
