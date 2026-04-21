"""Tests for YAML discovery, parsing, and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.configuration.report_loader import (
    ReportConfigError,
    YamlReport,
    discover_yaml_files,
    load_yaml_reports,
    parse_report_file,
    validate_all,
)


def _write_yaml(tmp_path: Path, name: str, payload: dict) -> Path:
    file_path = tmp_path / f"{name}.yaml"
    with file_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False)
    return file_path


def _valid_payload(name: str = "test_report") -> dict:
    return {
        "name": name,
        "metadata_dataset_file_name": f"{name}_metadata",
        "cards": [{"dashboard": "D", "card": "C", "viz_type": "Single Value"}],
        "destinations": [{"type": "slack", "channel_name": "test"}],
    }


def test_parses_minimum_valid_report(tmp_path):
    file_path = _write_yaml(tmp_path, "minimal", _valid_payload("minimal"))
    spec = parse_report_file(file_path)

    assert spec.name == "minimal"
    assert spec.metadata_dataset_file_name == "minimal_metadata"
    assert len(spec.cards) == 1
    assert len(spec.destinations) == 1
    assert spec.schedule is None


def test_parses_schedule_field(tmp_path):
    payload = _valid_payload()
    payload["schedule"] = "0 9 * * *"
    file_path = _write_yaml(tmp_path, "scheduled", payload)

    spec = parse_report_file(file_path)
    assert spec.schedule == "0 9 * * *"


def test_missing_top_level_key_raises(tmp_path):
    payload = _valid_payload()
    del payload["destinations"]
    file_path = _write_yaml(tmp_path, "broken", payload)

    with pytest.raises(ReportConfigError, match="missing required keys"):
        parse_report_file(file_path)


def test_card_missing_required_keys_raises(tmp_path):
    payload = _valid_payload()
    payload["cards"][0] = {"dashboard": "X"}  # missing card + viz_type
    file_path = _write_yaml(tmp_path, "bad_card", payload)

    with pytest.raises(ReportConfigError, match="cards\\[0\\]"):
        parse_report_file(file_path)


def test_destination_missing_type_raises(tmp_path):
    payload = _valid_payload()
    payload["destinations"][0] = {"channel_name": "x"}
    file_path = _write_yaml(tmp_path, "bad_dest", payload)

    with pytest.raises(ReportConfigError, match="destinations\\[0\\]"):
        parse_report_file(file_path)


def test_empty_cards_and_no_datasets_raises(tmp_path):
    payload = _valid_payload()
    payload["cards"] = []
    file_path = _write_yaml(tmp_path, "empty_cards", payload)

    with pytest.raises(ReportConfigError, match="at least one of 'cards'"):
        parse_report_file(file_path)


def test_discover_yaml_files_picks_up_yaml_and_yml(tmp_path):
    _write_yaml(tmp_path, "a", _valid_payload("a"))
    yml_path = tmp_path / "b.yml"
    with yml_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(_valid_payload("b"), fh)
    (tmp_path / "ignore.txt").write_text("not yaml")

    found = discover_yaml_files(tmp_path)
    assert len(found) == 2
    assert {p.name for p in found} == {"a.yaml", "b.yml"}


def test_load_yaml_reports_returns_yaml_report_instances(tmp_path):
    _write_yaml(tmp_path, "a", _valid_payload("a"))
    reports = load_yaml_reports(tmp_path)
    assert len(reports) == 1
    assert isinstance(reports[0], YamlReport)
    assert reports[0].name == "a"


def test_validate_all_separates_valid_from_errors(tmp_path):
    _write_yaml(tmp_path, "good", _valid_payload("good"))
    bad_payload = _valid_payload("bad")
    del bad_payload["destinations"]
    _write_yaml(tmp_path, "bad", bad_payload)

    valid, errors = validate_all(tmp_path)
    assert len(valid) == 1
    assert valid[0].name == "good"
    assert len(errors) == 1
    assert "bad" in errors[0]


def test_yaml_report_passes_through_card_overrides(tmp_path):
    payload = _valid_payload()
    payload["cards"][0]["crop"] = [0, 0, 100, 100]
    payload["cards"][0]["add_caption"] = True
    file_path = _write_yaml(tmp_path, "with_overrides", payload)

    spec = parse_report_file(file_path)
    report = YamlReport(spec)
    cards = report.list_of_cards()

    assert cards[0][0] == "D"
    assert cards[0][1] == "C"
    assert cards[0][2] == "Single Value"
    assert cards[0][3] == {"crop": [0, 0, 100, 100], "add_caption": True}
