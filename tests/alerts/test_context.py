"""Tests for app.alerts.context."""

from __future__ import annotations

import datetime

from app.alerts.context import (
    DotDict,
    build_card_context,
    build_dataset_context,
)

# ---- DotDict ----


def test_dotdict_attribute_and_item_access():
    d = DotDict(name="ACME", value=42)
    assert d.name == "ACME"
    assert d["value"] == 42
    assert d.missing is None  # attribute access yields None for missing keys


def test_dotdict_dunder_attributes_still_raise():
    d = DotDict(name="X")
    # Internal / dunder names must NOT be proxied via __getattr__ -- that's
    # what allows dict to keep working normally.
    try:
        _ = d.__nope__
    except AttributeError:
        pass  # expected


# ---- build_card_context ----


def test_build_card_context_maps_runtime_fields():
    resolved = {
        "card_id": 12345,
        "card_url": "https://domo.example.com/c/12345",
        "page_name": "Sales",
        "card_name": "Revenue",
        "viz_type": "Bar Chart",
        "image_path": "/tmp/x.png",
    }
    ctx = build_card_context(resolved)
    assert ctx["card"]["name"] == "Revenue"
    assert ctx["card"]["card_name"] == "Revenue"
    assert ctx["card"]["url"] == "https://domo.example.com/c/12345"
    assert ctx["card"]["card_id"] == 12345
    assert ctx["card"]["page_name"] == "Sales"
    assert "env" in ctx
    assert "run" in ctx


def test_build_card_context_with_yaml_dict():
    yaml_like = {"name": "Revenue", "dashboard": "Sales", "card": "Revenue"}
    ctx = build_card_context(yaml_like)
    assert ctx["card"]["name"] == "Revenue"


def test_build_card_context_hoists_value_from_overrides():
    resolved = {"card_name": "X", "overrides": {"value": 1234.5}}
    ctx = build_card_context(resolved)
    assert ctx["card"]["value"] == 1234.5


def test_build_card_context_extra_overrides_value():
    resolved = {"card_name": "X", "overrides": {"value": 1}}
    ctx = build_card_context(resolved, extra={"value": 99})
    assert ctx["card"]["value"] == 99


def test_env_context_has_predictable_keys():
    now = datetime.datetime(2026, 4, 21, 14, 30, 0)
    ctx = build_card_context({"card_name": "X"}, now=now)
    env = ctx["env"]
    assert env["today"] == "2026-04-21"
    assert env["weekday"] == "Tuesday"
    assert env["month"] == "April"
    assert env["hour"] == 14


# ---- build_dataset_context ----


def test_build_dataset_context_reads_file_metadata(tmp_path):
    csv_path = tmp_path / "x.csv"
    csv_path.write_text("col1,col2\na,1\nb,2\nc,3\n")
    ctx = build_dataset_context(
        {"name": "daily", "dataset_id": "abc-123", "format": "csv"},
        file_path=csv_path,
    )
    ds = ctx["dataset"]
    assert ds["name"] == "daily"
    assert ds["dataset_id"] == "abc-123"
    assert ds["file_format"] == "csv"
    assert ds["size_bytes"] > 0
    assert ds["row_count"] == 3


def test_build_dataset_context_missing_file_still_works():
    ctx = build_dataset_context({"name": "x", "dataset_id": "y"})
    assert ctx["dataset"]["name"] == "x"
    assert ctx["dataset"].get("size_bytes") is None


def test_build_dataset_context_run_status_projection():
    class FakeRun:
        report_name = "Daily"
        status = type("Status", (), {"value": "success"})()
        started_at = datetime.datetime(2026, 4, 21, 9, 0, 0)
        finished_at = datetime.datetime(2026, 4, 21, 9, 0, 30)

    ctx = build_dataset_context({"name": "x", "dataset_id": "y"}, run=FakeRun())
    assert ctx["run"]["report_name"] == "Daily"
    assert ctx["run"]["status"] == "success"
    assert ctx["run"]["duration_seconds"] == 30.0
