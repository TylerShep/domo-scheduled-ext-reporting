"""Build the variable namespace exposed to ``send_when:`` expressions.

We deliberately keep the exposed surface *small* and predictable so reports
are portable:

* ``card``      -- ``DotDict`` with keys (``name``, ``url``, ``page_name``,
  ``viz_type``, ``card_id``, ``value`` if the card reports a summary value).
* ``dataset``   -- ``DotDict`` with (``name``, ``dataset_id``,
  ``file_path``, ``file_format``, ``row_count`` / ``size_bytes`` when cheap
  to compute).
* ``run``       -- Current :class:`~app.history.RunRecord` projected to
  ``DotDict`` with (``status``, ``started_at``, ``duration_seconds``,
  ``report_name``).
* ``env``       -- ``DotDict`` with (``today``, ``now``, ``weekday``,
  ``month``).  Useful for "only send on Mondays"-style guards.

The only object type an expression sees is plain ``str``/``int``/``float``
/``list``/``dict`` + ``DotDict`` so there's nothing for a malicious (or
accidental) expression to traverse into.
"""

from __future__ import annotations

import datetime as _dt
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class DotDict(dict):
    """Minimal dict subclass that supports attribute access.

    ``card.name`` works the same as ``card["name"]``.  Missing keys return
    ``None`` instead of raising, which matches what a user writing an
    expression usually wants -- ``card.foo == "bar"`` should just be
    ``False`` when ``card.foo`` isn't set.
    """

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            raise AttributeError(key)
        return self.get(key)

    def __setattr__(self, key: str, value: Any) -> None:  # pragma: no cover
        self[key] = value


def _env_context(now: _dt.datetime | None = None) -> DotDict:
    now = now or _dt.datetime.now()
    return DotDict(
        today=now.date().isoformat(),
        now=now.isoformat(timespec="seconds"),
        weekday=now.strftime("%A"),
        month=now.strftime("%B"),
        hour=now.hour,
        iso_week=now.isocalendar().week,
    )


def _run_context(run: Any) -> DotDict:
    if run is None:
        return DotDict(report_name=None, status=None, duration_seconds=None)
    status = getattr(run, "status", None)
    if hasattr(status, "value"):
        status = status.value  # RunStatus enum
    started = getattr(run, "started_at", None)
    finished = getattr(run, "finished_at", None)
    duration = None
    if started is not None and finished is not None:
        try:
            duration = (finished - started).total_seconds()
        except Exception:  # pragma: no cover
            duration = None
    return DotDict(
        report_name=getattr(run, "report_name", None),
        status=status,
        started_at=started.isoformat() if started else None,
        finished_at=finished.isoformat() if finished else None,
        duration_seconds=duration,
    )


def build_card_context(
    card_item: Mapping[str, Any],
    run: Any = None,
    *,
    extra: Mapping[str, Any] | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Assemble variables for a card-level ``send_when`` expression.

    Args:
        card_item: A resolved card dict (from ``_resolve_cards``) -- we
            support both that shape and the raw YAML dict for flexibility.
        run: Current :class:`RunRecord`, or ``None``.
        extra: Anything the caller wants to merge into the ``card`` namespace
            (e.g., a computed summary value).
        now: Override for the current time (used in tests).
    """

    raw = dict(card_item or {})
    # Some callers pass the raw YAML dict (with ``card_name`` under ``name``)
    # while others pass the runtime-resolved dict (``card_name``).  Normalize.
    name = raw.get("card_name") or raw.get("name") or raw.get("card")
    card_ns = DotDict(
        name=name,
        card_name=name,
        url=raw.get("card_url") or raw.get("url"),
        page_name=raw.get("page_name"),
        viz_type=raw.get("viz_type"),
        card_id=raw.get("card_id"),
        image_path=raw.get("image_path"),
    )
    if extra:
        card_ns.update(extra)
    # Also surface card.value if an override or extra provided it; common
    # pattern for KPI alerts.
    if "value" not in card_ns and raw.get("overrides"):
        val = (raw.get("overrides") or {}).get("value")
        if val is not None:
            card_ns["value"] = val

    return {
        "card": card_ns,
        "run": _run_context(run),
        "env": _env_context(now),
    }


def build_dataset_context(
    dataset_spec: Mapping[str, Any],
    file_path: str | os.PathLike[str] | None = None,
    run: Any = None,
    *,
    extra: Mapping[str, Any] | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Assemble variables for a dataset-level ``send_when`` expression."""

    raw = dict(dataset_spec or {})
    ds_ns = DotDict(
        name=raw.get("name") or raw.get("dataset_id"),
        dataset_id=raw.get("dataset_id"),
        file_format=raw.get("format") or raw.get("file_format") or "csv",
        file_path=str(file_path) if file_path else raw.get("file_path"),
    )

    if file_path:
        try:
            path = Path(file_path)
            if path.exists():
                ds_ns["size_bytes"] = path.stat().st_size
                if ds_ns.file_format == "csv":
                    # Row count excludes header.
                    with path.open("rb") as fh:
                        ds_ns["row_count"] = max(0, sum(1 for _ in fh) - 1)
        except Exception:  # pragma: no cover - stat failures shouldn't break alerts
            pass

    if extra:
        ds_ns.update(extra)

    return {
        "dataset": ds_ns,
        "run": _run_context(run),
        "env": _env_context(now),
    }
