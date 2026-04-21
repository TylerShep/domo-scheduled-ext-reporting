"""YAML-level send_when: integration tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.configuration.report_loader import parse_report_file


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    file_path = tmp_path / "report.yaml"
    file_path.write_text(yaml.safe_dump(data))
    return file_path


def test_send_when_on_card_survives_through_overrides(tmp_path):
    spec = parse_report_file(
        _write_yaml(
            tmp_path,
            {
                "name": "Daily",
                "metadata_dataset_file_name": "meta",
                "cards": [
                    {
                        "dashboard": "Sales",
                        "card": "Revenue",
                        "viz_type": "Bar",
                        "send_when": "card.value > 1000",
                    }
                ],
                "destinations": [{"type": "slack", "channel_name": "x"}],
            },
        )
    )
    assert spec.cards[0]["send_when"] == "card.value > 1000"


def test_send_when_on_destination_survives_through_spec(tmp_path):
    spec = parse_report_file(
        _write_yaml(
            tmp_path,
            {
                "name": "Daily",
                "metadata_dataset_file_name": "meta",
                "cards": [{"dashboard": "Sales", "card": "Revenue", "viz_type": "Bar"}],
                "destinations": [
                    {
                        "type": "slack",
                        "channel_name": "x",
                        "send_when": "card.page_name == 'Sales'",
                    }
                ],
            },
        )
    )
    dest = spec.destinations[0]
    assert dest["send_when"] == "card.page_name == 'Sales'"


def test_send_when_on_dataset_survives_through_spec(tmp_path):
    spec = parse_report_file(
        _write_yaml(
            tmp_path,
            {
                "name": "Daily",
                "metadata_dataset_file_name": "meta",
                "datasets": [
                    {
                        "name": "orders",
                        "dataset_id": "abc-123",
                        "send_when": "dataset.row_count > 0",
                    }
                ],
                "destinations": [{"type": "file", "target": "local"}],
            },
        )
    )
    assert spec.datasets[0]["send_when"] == "dataset.row_count > 0"


def test_yaml_report_preserves_send_when_on_cards(tmp_path):
    """YamlReport.list_of_cards() returns rows with overrides dicts
    containing send_when, so DomoBase._dispatch can read them."""

    from app.configuration.report_loader import YamlReport

    spec = parse_report_file(
        _write_yaml(
            tmp_path,
            {
                "name": "Daily",
                "metadata_dataset_file_name": "meta",
                "cards": [
                    {
                        "dashboard": "Sales",
                        "card": "Revenue",
                        "viz_type": "Bar",
                        "send_when": "True",
                    }
                ],
                "destinations": [{"type": "slack", "channel_name": "x"}],
            },
        )
    )
    report = YamlReport(spec)
    row = report.list_of_cards()[0]
    overrides = row[3]
    assert overrides["send_when"] == "True"
