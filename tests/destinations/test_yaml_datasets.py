"""Tests for the ``datasets:`` YAML key."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.configuration.report_loader import (
    ReportConfigError,
    YamlReport,
    parse_report_file,
)


def _write_yaml(tmp_path: Path, name: str, payload: dict) -> Path:
    file_path = tmp_path / f"{name}.yaml"
    with file_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False)
    return file_path


def _minimal_payload() -> dict:
    return {
        "name": "r",
        "metadata_dataset_file_name": "r_metadata",
        "cards": [{"dashboard": "D", "card": "C", "viz_type": "Single Value"}],
        "destinations": [{"type": "file", "target": "local"}],
    }


def test_dataset_only_report_is_valid(tmp_path):
    """Backwards-compat: if cards is missing but datasets is present, it loads."""

    payload = _minimal_payload()
    payload.pop("cards")
    payload["datasets"] = [{"name": "X", "dataset_id": "abc", "format": "csv"}]
    report = parse_report_file(_write_yaml(tmp_path, "r", payload))
    assert report.cards == []
    assert report.datasets == [{"name": "X", "dataset_id": "abc", "format": "csv"}]


def test_datasets_and_cards_coexist(tmp_path):
    payload = _minimal_payload()
    payload["datasets"] = [{"name": "X", "dataset_id": "abc"}]
    spec = parse_report_file(_write_yaml(tmp_path, "r", payload))
    assert len(spec.cards) == 1
    assert len(spec.datasets) == 1


def test_dataset_missing_name_raises(tmp_path):
    payload = _minimal_payload()
    payload["datasets"] = [{"dataset_id": "abc"}]
    with pytest.raises(ReportConfigError, match="datasets\\[0\\]"):
        parse_report_file(_write_yaml(tmp_path, "bad", payload))


def test_dataset_unsupported_format_raises(tmp_path):
    payload = _minimal_payload()
    payload["datasets"] = [{"name": "X", "dataset_id": "abc", "format": "parquet"}]
    with pytest.raises(ReportConfigError, match="datasets\\[0\\].format"):
        parse_report_file(_write_yaml(tmp_path, "bad", payload))


def test_report_without_cards_or_datasets_raises(tmp_path):
    payload = _minimal_payload()
    payload.pop("cards")
    with pytest.raises(ReportConfigError, match="at least one of 'cards'"):
        parse_report_file(_write_yaml(tmp_path, "bad", payload))


def test_yaml_report_exposes_list_of_datasets(tmp_path):
    payload = _minimal_payload()
    payload["datasets"] = [{"name": "X", "dataset_id": "abc"}]
    spec = parse_report_file(_write_yaml(tmp_path, "r", payload))
    report = YamlReport(spec)
    assert report.list_of_datasets() == [{"name": "X", "dataset_id": "abc"}]
