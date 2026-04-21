"""Tiny test-factory helpers.

These functions return sensible default fixtures so individual tests don't
have to re-type the same 15-line YAML block. Every factory accepts ``**kwargs``
to override specific fields.

The philosophy: keep these dumb and boring. They return primitive
:class:`dict` / :class:`list` objects -- never live :class:`Destination` or
:class:`Engine` instances -- so tests stay decoupled from the runtime.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any

# ---------------------------------------------------------------- engine rows


def card_yaml(
    dashboard: str = "Dashboard",
    card: str = "Example Card",
    viz_type: str = "Single Value",
    **overrides: Any,
) -> dict[str, Any]:
    """Return a single ``cards:`` entry in YAML-dict form."""

    payload: dict[str, Any] = {
        "dashboard": dashboard,
        "card": card,
        "viz_type": viz_type,
    }
    payload.update(overrides)
    return payload


def dataset_yaml(
    name: str = "daily_rollup",
    dataset_id: str = "abc-123",
    file_format: str = "csv",
    **overrides: Any,
) -> dict[str, Any]:
    """Return a ``datasets:`` entry."""

    payload: dict[str, Any] = {
        "name": name,
        "dataset_id": dataset_id,
        "format": file_format,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------- destinations


def slack_destination(
    channel_name: str = "#general",
    token_env: str = "SLACK_BOT_USER_TOKEN",
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "slack",
        "channel_name": channel_name,
        "token_env": token_env,
    }
    payload.update(overrides)
    return payload


def teams_destination(
    auth_mode: str = "graph",
    team_name: str = "Sales",
    channel_name: str = "Daily KPIs",
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "teams",
        "auth_mode": auth_mode,
        "team_name": team_name,
        "channel_name": channel_name,
    }
    payload.update(overrides)
    return payload


def email_destination(
    to_addrs: list[str] | None = None,
    subject_template: str = "Daily Report",
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "email",
        "to_addrs": to_addrs or ["ops@example.com"],
        "subject_template": subject_template,
    }
    payload.update(overrides)
    return payload


def file_destination(
    output_dir: str = "/tmp",
    target: str = "local",
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "file",
        "output_dir": output_dir,
        "target": target,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------- reports


def report_yaml(
    name: str = "example_report",
    metadata_dataset_file_name: str = "example_file",
    cards: list[dict[str, Any]] | None = None,
    destinations: list[dict[str, Any]] | None = None,
    datasets: list[dict[str, Any]] | None = None,
    schedule: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Return a minimal-but-valid YAML-dict report.

    The caller can override any top-level key via kwargs.
    """

    payload: dict[str, Any] = {
        "name": name,
        "metadata_dataset_file_name": metadata_dataset_file_name,
    }
    if cards is None and datasets is None:
        cards = [card_yaml()]
    if cards is not None:
        payload["cards"] = cards
    if datasets is not None:
        payload["datasets"] = datasets
    if destinations is None:
        destinations = [slack_destination()]
    payload["destinations"] = destinations
    if schedule:
        payload["schedule"] = schedule
    payload.update(overrides)
    return payload


# --------------------------------------------------------------- history rows


def card_outcome(**overrides: Any):
    """Return a :class:`CardOutcome` with sensible defaults."""

    from app.history import CardOutcome

    payload: dict[str, Any] = {"card_name": "Sample Card", "sent": True}
    payload.update(overrides)
    return CardOutcome(**payload)


def destination_outcome(**overrides: Any):
    """Return a :class:`DestinationOutcome` with sensible defaults."""

    from app.history import DestinationOutcome

    payload: dict[str, Any] = {
        "destination_label": "slack(#demo)",
        "destination_type": "slack",
        "cards_attempted": 1,
        "cards_sent": 1,
    }
    payload.update(overrides)
    return DestinationOutcome(**payload)


def run_record(**overrides: Any):
    """Return a :class:`RunRecord` with sensible defaults."""

    from app.history import CardOutcome, DestinationOutcome, RunRecord
    from app.history.base import RunStatus

    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    payload: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "report_name": "example_report",
        "started_at": now,
        "finished_at": now + _dt.timedelta(seconds=2),
        "status": RunStatus.SUCCESS,
        "cards": [CardOutcome(card_name="Sample", sent=True)],
        "destinations": [
            DestinationOutcome(
                destination_label="slack(#demo)",
                destination_type="slack",
                cards_attempted=1,
                cards_sent=1,
            )
        ],
    }
    payload.update(overrides)
    return RunRecord(**payload)
