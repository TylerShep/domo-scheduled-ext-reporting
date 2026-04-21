"""Tests for the YAML report scaffolding helper."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.utils import project_updates_util as updates


@pytest.fixture
def temp_reports_dir(tmp_path, monkeypatch):
    """Redirect ``_REPORTS_DIR`` at module level for the duration of a test."""

    monkeypatch.setattr(updates, "_REPORTS_DIR", tmp_path)
    return tmp_path


def test_scaffold_creates_yaml_with_expected_shape(temp_reports_dir: Path):
    out = updates.scaffold_yaml_report("My Cool Report")

    assert out.exists()
    assert out.name == "my_cool_report.yaml"

    with out.open() as fh:
        data = yaml.safe_load(fh)
    assert data["name"] == "my_cool_report"
    assert data["cards"]
    assert data["destinations"]
    assert data["destinations"][0]["type"] == "slack"


def test_scaffold_refuses_to_overwrite_by_default(temp_reports_dir: Path):
    updates.scaffold_yaml_report("dup")
    with pytest.raises(FileExistsError):
        updates.scaffold_yaml_report("dup")


def test_scaffold_overwrites_when_requested(temp_reports_dir: Path):
    updates.scaffold_yaml_report("dup")
    out = updates.scaffold_yaml_report("dup", overwrite=True)
    assert out.exists()


def test_add_card_appends_to_existing_report(temp_reports_dir: Path):
    updates.scaffold_yaml_report("kpis")
    updates.add_card_to_report("kpis", "New Dash", "New Card", "Bar")

    with (temp_reports_dir / "kpis.yaml").open() as fh:
        data = yaml.safe_load(fh)
    assert any(c["card"] == "New Card" for c in data["cards"])


def test_add_card_to_missing_report_raises(temp_reports_dir: Path):
    with pytest.raises(FileNotFoundError):
        updates.add_card_to_report("nope", "d", "c", "Bar")
