"""Tests for the Slack destination's channel resolution + send loop."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.destinations.base import DestinationContext
from app.destinations.slack import SlackDestination


@pytest.fixture
def fake_token(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_USER_TOKEN", "xoxb-fake")


def test_resolves_channel_id_on_first_page(fake_token):
    dest = SlackDestination(channel_name="daily-kpis")

    fake_client = MagicMock()
    fake_client.conversations_list.return_value = {
        "channels": [{"id": "C123", "name": "daily-kpis"}, {"id": "C999", "name": "other"}],
        "response_metadata": {"next_cursor": ""},
    }

    with patch("app.destinations.slack.WebClient", return_value=fake_client):
        dest.prepare()

    assert dest._channel_id == "C123"
    fake_client.conversations_list.assert_called_once()


def test_pages_through_until_channel_found(fake_token):
    dest = SlackDestination(channel_name="needle")

    fake_client = MagicMock()
    fake_client.conversations_list.side_effect = [
        {
            "channels": [{"id": "C1", "name": "haystack-1"}],
            "response_metadata": {"next_cursor": "abc"},
        },
        {
            "channels": [{"id": "C2", "name": "needle"}],
            "response_metadata": {"next_cursor": ""},
        },
    ]

    with patch("app.destinations.slack.WebClient", return_value=fake_client):
        dest.prepare()

    assert dest._channel_id == "C2"
    assert fake_client.conversations_list.call_count == 2


def test_send_image_calls_files_upload_v2(fake_token, tmp_path):
    image = tmp_path / "card.png"
    image.write_bytes(b"\x89PNG fake")

    dest = SlackDestination(channel_name="daily-kpis")

    fake_client = MagicMock()
    fake_client.conversations_list.return_value = {
        "channels": [{"id": "C123", "name": "daily-kpis"}],
        "response_metadata": {"next_cursor": ""},
    }
    fake_client.files_upload_v2.return_value = {"file": {"id": "F1"}}

    with patch("app.destinations.slack.WebClient", return_value=fake_client):
        dest.prepare()
        dest.send_image(
            DestinationContext(
                image_path=str(image),
                card_name="Daily Revenue",
                card_url="https://example.com/card",
                page_name="Sales Overview",
            )
        )

    args, kwargs = fake_client.files_upload_v2.call_args
    assert kwargs["channel"] == "C123"
    assert kwargs["file"] == str(image)
    assert kwargs["title"] == "https://example.com/card"
    assert kwargs["initial_comment"] == "Daily Revenue"


def test_missing_token_env_raises_on_prepare(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_USER_TOKEN", raising=False)
    dest = SlackDestination(channel_name="x")

    with pytest.raises(Exception):
        dest.prepare()
