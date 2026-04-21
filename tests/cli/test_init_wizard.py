"""Tests for `app.cli.init_wizard`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.cli.init_wizard import InitWizardError, run_init_wizard


def _auto_default_prompter(prompt: str, default: str | None = None) -> str:
    """Prompter that always accepts the default (never hits real stdin)."""

    return default or "x"


def test_slack_happy_path(tmp_path: Path):
    path = run_init_wizard(
        answers={
            "name": "Daily Revenue",
            "metadata_dataset_file_name": "daily_meta",
            "page": "Sales",
            "card": "Revenue",
            "viz_type": "Bar Chart",
            "destination_type": "slack",
            "channel_name": "data-drops",
        },
        prompter=_auto_default_prompter,
        output_dir=tmp_path,
    )
    data = yaml.safe_load(path.read_text())
    assert data["name"] == "Daily Revenue"
    assert data["metadata_dataset_file_name"] == "daily_meta"
    assert data["cards"][0]["dashboard"] == "Sales"
    assert data["cards"][0]["card"] == "Revenue"
    assert data["destinations"][0]["type"] == "slack"
    assert data["destinations"][0]["channel_name"] == "data-drops"


def test_teams_webhook_happy_path(tmp_path: Path):
    path = run_init_wizard(
        answers={
            "name": "Team Weekly",
            "metadata_dataset_file_name": "weekly",
            "page": "Ops",
            "card": "SLA",
            "viz_type": "KPI",
            "destination_type": "teams",
            "auth_mode": "webhook",
            "webhook_url_env": "TEAMS_WEBHOOK_URL",
        },
        prompter=_auto_default_prompter,
        output_dir=tmp_path,
    )
    data = yaml.safe_load(path.read_text())
    dest = data["destinations"][0]
    assert dest["type"] == "teams"
    assert dest["auth_mode"] == "webhook"
    assert dest["webhook_url_env"] == "TEAMS_WEBHOOK_URL"


def test_teams_graph_happy_path(tmp_path: Path):
    path = run_init_wizard(
        answers={
            "name": "Graph Weekly",
            "page": "Ops",
            "card": "SLA",
            "viz_type": "KPI",
            "destination_type": "teams",
            "auth_mode": "graph",
            "team_id": "abc",
            "channel_id": "xyz",
        },
        prompter=_auto_default_prompter,
        output_dir=tmp_path,
    )
    data = yaml.safe_load(path.read_text())
    dest = data["destinations"][0]
    assert dest["team_id"] == "abc"
    assert dest["channel_id"] == "xyz"


def test_email_happy_path(tmp_path: Path):
    path = run_init_wizard(
        answers={
            "name": "Email Daily",
            "page": "Sales",
            "card": "Revenue",
            "viz_type": "Bar",
            "destination_type": "email",
            "to": "a@example.com, b@example.com",
            "subject_template": "Hi {{ today }}",
        },
        prompter=_auto_default_prompter,
        output_dir=tmp_path,
    )
    data = yaml.safe_load(path.read_text())
    dest = data["destinations"][0]
    assert dest["to"] == ["a@example.com", "b@example.com"]
    assert "today" in dest["subject_template"]


def test_file_target(tmp_path: Path):
    path = run_init_wizard(
        answers={
            "name": "Files",
            "page": "Sales",
            "card": "Revenue",
            "viz_type": "Bar",
            "destination_type": "file",
            "file_target": "local",
        },
        prompter=_auto_default_prompter,
        output_dir=tmp_path,
    )
    data = yaml.safe_load(path.read_text())
    dest = data["destinations"][0]
    assert dest["type"] == "file"
    assert dest["target"] == "local"


def test_unsupported_destination_raises(tmp_path: Path):
    with pytest.raises(InitWizardError, match="Unsupported"):
        run_init_wizard(
            answers={
                "name": "X",
                "page": "P",
                "card": "C",
                "viz_type": "V",
                "destination_type": "carrier-pigeon",
            },
            prompter=_auto_default_prompter,
            output_dir=tmp_path,
        )


def test_refuses_to_overwrite_by_default(tmp_path: Path):
    first = run_init_wizard(
        answers={
            "name": "Dup",
            "page": "P",
            "card": "C",
            "viz_type": "V",
            "destination_type": "slack",
            "channel_name": "x",
        },
        prompter=_auto_default_prompter,
        output_dir=tmp_path,
    )
    assert first.exists()
    with pytest.raises(InitWizardError, match="already exists"):
        run_init_wizard(
            answers={
                "name": "Dup",
                "page": "P",
                "card": "C",
                "viz_type": "V",
                "destination_type": "slack",
                "channel_name": "y",
            },
            prompter=_auto_default_prompter,
            output_dir=tmp_path,
        )


def test_overwrite_true_replaces_file(tmp_path: Path):
    first = run_init_wizard(
        answers={
            "name": "Dup",
            "page": "P",
            "card": "C",
            "viz_type": "V",
            "destination_type": "slack",
            "channel_name": "x",
        },
        prompter=_auto_default_prompter,
        output_dir=tmp_path,
    )
    run_init_wizard(
        answers={
            "name": "Dup",
            "page": "P",
            "card": "C",
            "viz_type": "V",
            "destination_type": "slack",
            "channel_name": "y",
        },
        prompter=_auto_default_prompter,
        output_dir=tmp_path,
        overwrite=True,
    )
    data = yaml.safe_load(first.read_text())
    assert data["destinations"][0]["channel_name"] == "y"


def test_empty_name_raises(tmp_path: Path):
    with pytest.raises(InitWizardError, match="report name"):
        run_init_wizard(
            answers={
                "name": "",
                "page": "P",
                "card": "C",
                "viz_type": "V",
                "destination_type": "slack",
                "channel_name": "x",
            },
            prompter=_auto_default_prompter,
            output_dir=tmp_path,
        )


def test_custom_prompter_called_for_missing_answers(tmp_path: Path):
    prompt_log: list[tuple[str, str | None]] = []

    def prompter(prompt: str, default: str | None = None) -> str:
        prompt_log.append((prompt, default))
        return default or "dummy"

    path = run_init_wizard(
        answers={},
        prompter=prompter,
        output_dir=tmp_path,
    )
    # Some of the prompts should have fired.
    assert len(prompt_log) >= 4
    assert path.exists()


def test_generated_yaml_passes_validation(tmp_path: Path):
    """The YAML the wizard produces should round-trip through the report loader."""

    path = run_init_wizard(
        answers={
            "name": "Daily Revenue",
            "metadata_dataset_file_name": "daily_meta",
            "page": "Sales",
            "card": "Revenue",
            "viz_type": "Bar Chart",
            "destination_type": "slack",
            "channel_name": "data-drops",
        },
        prompter=_auto_default_prompter,
        output_dir=tmp_path,
    )
    from app.configuration.report_loader import parse_report_file

    spec = parse_report_file(path)
    assert spec.name == "Daily Revenue"
    assert spec.cards[0]["card"] == "Revenue"
    assert spec.destinations[0]["type"] == "slack"
