"""Tests for RuntimeFlags + --dry-run / --preview behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.destinations.base import DatasetContext, DestinationContext
from app.destinations.email import EmailDestination
from app.destinations.file import FileDestination
from app.destinations.slack import SlackDestination
from app.destinations.teams import (
    TeamsGraphDestination,
    TeamsWebhookDestination,
)
from app.runtime import (
    RuntimeFlags,
    get_flags,
    is_dry_run,
    is_preview_enabled,
    preview_dir,
    reset_flags,
    set_flags,
    update_flags,
)


@pytest.fixture(autouse=True)
def _reset_runtime_flags():
    reset_flags()
    yield
    reset_flags()


# ---- runtime flags ----


def test_get_flags_default():
    flags = get_flags()
    assert isinstance(flags, RuntimeFlags)
    assert flags.dry_run is False
    assert flags.preview is False
    assert flags.preview_path == "state/preview"


def test_set_flags_replaces():
    set_flags(RuntimeFlags(dry_run=True, preview=True, preview_path="/tmp/x"))
    flags = get_flags()
    assert flags.dry_run is True
    assert flags.preview is True
    assert flags.preview_path == "/tmp/x"


def test_update_flags_partial():
    update_flags(dry_run=True)
    assert get_flags().dry_run is True
    assert get_flags().preview is False


def test_is_dry_run_respects_override():
    assert is_dry_run() is False
    assert is_dry_run(True) is True
    update_flags(dry_run=True)
    assert is_dry_run() is True
    assert is_dry_run(False) is True


def test_is_preview_enabled_tracks_flag():
    assert is_preview_enabled() is False
    update_flags(preview=True)
    assert is_preview_enabled() is True


def test_preview_dir_is_absolute():
    update_flags(preview_path="state/preview")
    assert Path(preview_dir()).is_absolute()


# ---- CLI parser ----


def test_cli_has_dry_run_and_preview():
    from app.configuration.arg_parser.arg_parser_config import configure_arg_parser

    parser = configure_arg_parser()
    args = parser.parse_args(["--validate", "--dry-run", "--preview", "--preview-path", "/tmp/p"])
    assert args.dry_run is True
    assert args.preview is True
    assert args.preview_path == "/tmp/p"


def test_cli_dry_run_defaults_off():
    from app.configuration.arg_parser.arg_parser_config import configure_arg_parser

    parser = configure_arg_parser()
    args = parser.parse_args(["--validate"])
    assert args.dry_run is False
    assert args.preview is False


# ---- Slack destination dry-run ----


def test_slack_dry_run_short_circuits_send(tmp_path):
    update_flags(dry_run=True)
    image = tmp_path / "card.png"
    image.write_bytes(b"fake")
    dest = SlackDestination(channel_name="data")
    with patch("app.destinations.slack.WebClient") as client_cls:
        dest.send_image(
            DestinationContext(
                image_path=str(image),
                card_name="Revenue",
                card_url="https://x",
                page_name="P",
            )
        )
    client_cls.assert_not_called()


def test_slack_dry_run_skips_prepare_channel_lookup():
    update_flags(dry_run=True)
    dest = SlackDestination(channel_name="anywhere")
    with patch("app.destinations.slack.WebClient") as client_cls:
        dest.prepare()
    client_cls.assert_not_called()


def test_slack_per_instance_dry_run_wins_even_globally_off(tmp_path):
    image = tmp_path / "c.png"
    image.write_bytes(b"x")
    dest = SlackDestination(channel_name="d", dry_run=True)
    with patch("app.destinations.slack.WebClient") as client_cls:
        dest.send_image(DestinationContext(str(image), "Rev", "https://x", "Page"))
    client_cls.assert_not_called()


def test_slack_dataset_dry_run(tmp_path):
    update_flags(dry_run=True)
    path = tmp_path / "a.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    dest = SlackDestination(channel_name="data")
    with patch("app.destinations.slack.WebClient") as client_cls:
        dest.send_dataset(
            DatasetContext(
                file_path=str(path),
                dataset_name="Orders",
                dataset_id="abc",
                file_format="csv",
            )
        )
    client_cls.assert_not_called()


# ---- Teams Graph destination dry-run ----


def test_teams_graph_dry_run_short_circuits_send(tmp_path):
    update_flags(dry_run=True)
    image = tmp_path / "x.png"
    image.write_bytes(b"x")
    dest = TeamsGraphDestination(team_name="T", channel_name="C")
    with patch("app.destinations.teams.requests") as reqs:
        dest.send_image(DestinationContext(str(image), "Rev", "https://x", "Page"))
    reqs.assert_not_called()


def test_teams_graph_dry_run_skips_prepare():
    update_flags(dry_run=True)
    dest = TeamsGraphDestination(team_name="T", channel_name="C")
    with patch("app.destinations.teams.msal") as msal_mod:
        dest.prepare()
    msal_mod.ConfidentialClientApplication.assert_not_called()


# ---- Teams Webhook destination dry-run ----


def test_teams_webhook_dry_run_short_circuits_send(tmp_path, monkeypatch):
    update_flags(dry_run=True)
    image = tmp_path / "x.png"
    image.write_bytes(b"x")
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://never.example.com")
    dest = TeamsWebhookDestination(webhook_url_env="TEAMS_WEBHOOK_URL")
    with patch("app.destinations.teams.requests.post") as post:
        dest.send_image(DestinationContext(str(image), "Rev", "https://x", "Page"))
    post.assert_not_called()


# ---- Email destination dry-run ----


def test_email_dry_run_builds_nothing(tmp_path):
    update_flags(dry_run=True)
    dest = EmailDestination(to_addrs=["a@b.c"], from_addr="b@b.c")
    dest.prepare()
    image = tmp_path / "card.png"
    image.write_bytes(b"x")
    dest.send_image(DestinationContext(str(image), "Rev", "https://x", "Page"))
    with patch("app.destinations.email.smtplib.SMTP") as smtp:
        dest.teardown()
    smtp.assert_not_called()


# ---- File destination dry-run ----


def test_file_destination_dry_run_local(tmp_path):
    update_flags(dry_run=True)
    ds = tmp_path / "orders.csv"
    ds.write_text("a,b\n1,2\n", encoding="utf-8")
    out = tmp_path / "sink"
    dest = FileDestination(target="local", output_dir=str(out))
    dest.prepare()
    dest.send_dataset(
        DatasetContext(
            file_path=str(ds),
            dataset_name="Orders",
            dataset_id="abc",
            file_format="csv",
        )
    )
    # Nothing should have been copied into the sink directory.
    assert not out.exists() or not any(out.iterdir())


def test_file_destination_dry_run_skips_sub_destination(tmp_path):
    update_flags(dry_run=True)
    ds = tmp_path / "d.csv"
    ds.write_text("a\n1\n", encoding="utf-8")
    dest = FileDestination(
        target="slack",
        sub_destination_spec={"type": "slack", "channel_name": "data"},
    )
    with patch("app.destinations.slack.WebClient") as client_cls:
        dest.prepare()
        dest.send_dataset(DatasetContext(str(ds), "Orders", "abc", "csv"))
    client_cls.assert_not_called()


# ---- Preview folder ----


def test_preview_copies_card_image(tmp_path, monkeypatch):
    """When preview is on, the service base copies the edited image into the
    preview folder. We invoke the helper directly for focused coverage."""

    from app.services.base import _maybe_copy_to_preview

    update_flags(preview=True, preview_path=str(tmp_path))
    img = tmp_path / "orig.png"
    img.write_bytes(b"fake")

    _maybe_copy_to_preview(str(img), "My Report", "Cool Card")

    preview_root = Path(preview_dir())
    copies = list(preview_root.rglob("*.png"))
    assert copies, f"Expected a copy under {preview_root}"
    # clean_filename strips non-alnum and prepends YYYYMMDD.
    assert any("myreport" in str(c).lower() for c in copies)


def test_preview_noop_when_disabled(tmp_path):
    from app.services.base import _maybe_copy_to_preview

    # Flags are reset so preview is off.
    img = tmp_path / "orig.png"
    img.write_bytes(b"fake")

    _maybe_copy_to_preview(str(img), "Any", "Any")

    # Default preview_path points at "state/preview" (CWD-relative), which
    # we don't want to pollute. The helper should early-return.
    default_dir = Path("state/preview").resolve()
    copies = list(default_dir.rglob("*.png")) if default_dir.exists() else []
    assert not copies


# ---- registry wiring ----


def test_build_destination_accepts_dry_run_flag():
    from app.destinations.registry import build_destination

    dest = build_destination({"type": "slack", "channel_name": "data", "dry_run": True})
    assert dest.dry_run is True
