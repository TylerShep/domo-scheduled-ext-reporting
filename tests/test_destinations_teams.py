"""Tests for the Microsoft Teams destinations (registry, factory, webhook)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.destinations.base import DestinationContext
from app.destinations.registry import build_destination, known_destination_types
from app.destinations.teams import (
    TeamsDestinationError,
    TeamsGraphDestination,
    TeamsWebhookDestination,
    make_teams_destination,
)


def test_factory_returns_graph_for_graph_auth_mode():
    dest = make_teams_destination(
        auth_mode="graph",
        team_name="Sales",
        channel_name="Daily KPIs",
    )
    assert isinstance(dest, TeamsGraphDestination)


def test_factory_returns_webhook_for_webhook_auth_mode():
    dest = make_teams_destination(
        auth_mode="webhook",
        webhook_url_env="TEAMS_WEBHOOK_URL",
    )
    assert isinstance(dest, TeamsWebhookDestination)


def test_factory_unknown_auth_mode_raises():
    with pytest.raises(TeamsDestinationError, match="Unknown Teams auth_mode"):
        make_teams_destination(auth_mode="bogus")


def test_graph_requires_team_identifier():
    with pytest.raises(TeamsDestinationError):
        TeamsGraphDestination(channel_name="x")


def test_graph_requires_channel_identifier():
    with pytest.raises(TeamsDestinationError):
        TeamsGraphDestination(team_name="x")


def test_webhook_requires_url_or_env():
    with pytest.raises(TeamsDestinationError):
        TeamsWebhookDestination()


def test_webhook_send_image_posts_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://example.com/webhook")
    image = tmp_path / "card.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)

    dest = TeamsWebhookDestination(webhook_url_env="TEAMS_WEBHOOK_URL")

    fake_response = MagicMock(status_code=200)
    with patch("app.destinations.teams.requests.post", return_value=fake_response) as post:
        dest.send_image(
            DestinationContext(
                image_path=str(image),
                card_name="Weekly Revenue",
                card_url="https://example.com/card",
                page_name="Operations",
            )
        )

    post.assert_called_once()
    _, kwargs = post.call_args
    payload = kwargs["json"]
    assert payload["type"] == "message"
    body = payload["attachments"][0]["content"]["body"]
    assert body[0]["text"] == "Weekly Revenue"
    assert body[1]["url"].startswith("data:image/png;base64,")


def test_webhook_non_200_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://example.com/webhook")
    image = tmp_path / "card.png"
    image.write_bytes(b"PNGFAKE")

    dest = TeamsWebhookDestination(webhook_url_env="TEAMS_WEBHOOK_URL")

    fake_response = MagicMock(status_code=500, text="server error")
    with patch("app.destinations.teams.requests.post", return_value=fake_response):
        with pytest.raises(TeamsDestinationError, match="500"):
            dest.send_image(
                DestinationContext(
                    image_path=str(image),
                    card_name="x",
                    card_url="https://x",
                    page_name="p",
                )
            )


def test_registry_includes_known_types():
    assert "slack" in known_destination_types()
    assert "teams" in known_destination_types()


def test_build_destination_routes_to_teams_factory(monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://example.com/webhook")
    spec = {"type": "teams", "auth_mode": "webhook", "webhook_url_env": "TEAMS_WEBHOOK_URL"}
    dest = build_destination(spec)
    assert isinstance(dest, TeamsWebhookDestination)


def test_build_destination_unknown_type_raises():
    with pytest.raises(KeyError, match="Unknown destination type"):
        build_destination({"type": "carrier_pigeon"})
