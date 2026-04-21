"""Discover and load YAML report definitions from ``config/reports/``.

A YAML report is converted to a :class:`YamlReport` -- a generic
:class:`~app.services.base.DomoBase` subclass driven entirely by the YAML
contents. This means most users never need to touch Python.

YAML schema (all keys at the root of the file)::

    name: daily_kpis                     # required, used as registry key
    metadata_dataset_file_name: foo      # required, base name for the CSV
    cards:                               # required, >=1 entry
      - dashboard: "Dashboard Name"      # required
        card: "Card Name"                # required
        viz_type: "Single Value"         # required (see image_util.PRESETS)
        crop: [l, u, r, b]               # optional override
        resize: [w, h]                   # optional override
        add_caption: true                # optional
        caption_text: "..."              # optional, defaults to card name
    destinations:                        # required, >=1 entry
      - type: slack
        channel_name: "your-channel"
      - type: teams
        auth_mode: graph
        team_name: "Sales"
        channel_name: "Daily KPIs"
    schedule: "0 14 * * *"               # optional, used by the scheduler
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from app.destinations.base import Destination
from app.destinations.registry import build_destination
from app.services.base import DomoBase
from app.utils.logger import get_logger

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_REPORTS_DIR = _REPO_ROOT / "config" / "reports"


class ReportConfigError(ValueError):
    """Raised when a YAML report file fails validation."""


@dataclass
class ReportSpec:
    """Validated YAML payload for one report."""

    name: str
    metadata_dataset_file_name: str
    cards: list[dict[str, Any]]
    destinations: list[dict[str, Any]]
    schedule: str | None = None
    source_path: Path | None = None


class YamlReport(DomoBase):
    """Generic :class:`DomoBase` subclass driven by a :class:`ReportSpec`."""

    def __init__(self, spec: ReportSpec) -> None:
        self.spec = spec
        self.name = spec.name

    def file_name(self) -> str:
        return self.spec.metadata_dataset_file_name

    def list_of_cards(self) -> list[list[Any]]:
        out: list[list[Any]] = []
        for card in self.spec.cards:
            row: list[Any] = [card["dashboard"], card["card"], card.get("viz_type", "")]
            overrides = {
                k: v
                for k, v in card.items()
                if k in {"crop", "resize", "add_caption", "caption_text"}
            }
            if overrides:
                row.append(overrides)
            out.append(row)
        return out

    def list_of_destinations(self) -> list[dict[str, Any]]:
        return list(self.spec.destinations)

    def build_destinations(self) -> list[Destination]:
        return [build_destination(spec) for spec in self.list_of_destinations()]


# ---------------------------------------------------------------------------
# Discovery + validation
# ---------------------------------------------------------------------------

def discover_yaml_files(reports_dir: Path | None = None) -> list[Path]:
    """Return every ``*.yaml`` / ``*.yml`` file under ``reports_dir``."""

    base = reports_dir or _DEFAULT_REPORTS_DIR
    if not base.exists():
        return []
    return sorted(p for p in base.iterdir() if p.suffix.lower() in {".yaml", ".yml"})


def parse_report_file(path: Path) -> ReportSpec:
    """Parse and validate one YAML report file."""

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ReportConfigError(f"{path}: expected a mapping at the root, got {type(data).__name__}")
    return _validate(data, path)


def load_yaml_reports(reports_dir: Path | None = None) -> list[YamlReport]:
    """Discover, parse, and instantiate every YAML report in one pass."""

    reports: list[YamlReport] = []
    for path in discover_yaml_files(reports_dir):
        try:
            spec = parse_report_file(path)
        except ReportConfigError as exc:
            logger.error("Skipping invalid YAML report %s: %s", path, exc)
            continue
        reports.append(YamlReport(spec))
    return reports


def validate_all(reports_dir: Path | None = None) -> tuple[list[ReportSpec], list[str]]:
    """Parse every YAML file, returning ``(valid_specs, error_messages)``."""

    valid: list[ReportSpec] = []
    errors: list[str] = []
    for path in discover_yaml_files(reports_dir):
        try:
            valid.append(parse_report_file(path))
        except ReportConfigError as exc:
            errors.append(f"{path}: {exc}")
    return valid, errors


# ---------------------------------------------------------------------------
# Internal validation
# ---------------------------------------------------------------------------

_REQUIRED_TOP_LEVEL = {"name", "metadata_dataset_file_name", "cards", "destinations"}
_REQUIRED_CARD_KEYS = {"dashboard", "card", "viz_type"}


def _validate(data: dict[str, Any], path: Path) -> ReportSpec:
    missing = _REQUIRED_TOP_LEVEL - data.keys()
    if missing:
        raise ReportConfigError(f"missing required keys: {sorted(missing)}")

    name = str(data["name"]).strip()
    if not name:
        raise ReportConfigError("'name' must be a non-empty string")

    cards = _coerce_list(data["cards"], "cards", path)
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise ReportConfigError(f"cards[{index}] must be a mapping, got {type(card).__name__}")
        missing_card = _REQUIRED_CARD_KEYS - card.keys()
        if missing_card:
            raise ReportConfigError(
                f"cards[{index}] missing required keys: {sorted(missing_card)}"
            )

    destinations = _coerce_list(data["destinations"], "destinations", path)
    for index, dest in enumerate(destinations):
        if not isinstance(dest, dict):
            raise ReportConfigError(
                f"destinations[{index}] must be a mapping, got {type(dest).__name__}"
            )
        if "type" not in dest:
            raise ReportConfigError(f"destinations[{index}] missing required key: 'type'")

    schedule = data.get("schedule")
    if schedule is not None and not isinstance(schedule, str):
        raise ReportConfigError("'schedule' must be a cron-style string")

    return ReportSpec(
        name=name,
        metadata_dataset_file_name=str(data["metadata_dataset_file_name"]),
        cards=cards,
        destinations=destinations,
        schedule=schedule,
        source_path=path,
    )


def _coerce_list(value: Any, name: str, path: Path) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ReportConfigError(f"'{name}' must be a non-empty list")
    return list(value)


def reports_dir_default() -> Path:
    return _DEFAULT_REPORTS_DIR


# Convenience for callers that want both YAML reports and Python subclasses.
def all_yaml_reports() -> Iterable[YamlReport]:
    return load_yaml_reports()
