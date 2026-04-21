"""Tests for the richer Teams Graph + MessageCard payload shapes (Wave 8)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.destinations.base import DestinationContext
from app.destinations.teams import (
    TeamsDestinationError,
    TeamsGraphDestination,
    TeamsWebhookDestination,
)

# ---- helpers ----


def _make_ctx(tmp_path, name: str = "Revenue") -> DestinationContext:
    path = tmp_path / f"{name}.png"
    path.write_bytes(b"\x89PNG fake bytes")
    return DestinationContext(
        image_path=str(path),
        card_name=name,
        card_url=f"https://domo.example.com/card/{name}",
        page_name="Sales",
    )


def _fake_uploaded(name: str = "Revenue") -> dict:
    return {
        "eTag": f'"abc-{name}-eTag,1"',
        "webUrl": f"https://sharepoint/{name}.png",
        "name": f"{name}.png",
    }


# ---- Graph: batch_mode validation ----


def test_graph_unknown_batch_mode_raises():
    with pytest.raises(TeamsDestinationError, match="batch_mode"):
        TeamsGraphDestination(team_name="T", channel_name="C", batch_mode="stream")


def test_graph_defaults_to_single_carousel():
    dest = TeamsGraphDestination(team_name="T", channel_name="C")
    assert dest.batch_mode == "single_carousel"


# ---- Graph: per_message posts once per card (legacy behaviour) ----


def test_graph_per_message_posts_individually(tmp_path):
    dest = TeamsGraphDestination(team_name="T", channel_name="C", batch_mode="per_message")
    dest._access_token = "tok"
    dest._team_id = "team123"
    dest._channel_id = "chan123"

    with (
        patch.object(dest, "_upload_to_channel_files", return_value=_fake_uploaded("A")),
        patch.object(dest, "_post_message") as post,
    ):
        dest.send_image(_make_ctx(tmp_path, "A"))
        dest.send_image(_make_ctx(tmp_path, "B"))
    assert post.call_count == 2
    # teardown must be a no-op here
    dest.teardown()
    assert post.call_count == 2


# ---- Graph: single_carousel buffers then posts once ----


def test_graph_single_carousel_posts_one_message(tmp_path):
    dest = TeamsGraphDestination(team_name="T", channel_name="C")
    dest._access_token = "tok"
    dest._team_id = "team123"
    dest._channel_id = "chan123"

    call_n = {"i": 0}

    def _fake_upload(team_id, channel_id, file_path, content_type="image/png"):
        call_n["i"] += 1
        return _fake_uploaded(f"C{call_n['i']}")

    with (
        patch.object(dest, "_upload_to_channel_files", side_effect=_fake_upload),
        patch.object(dest, "_post_message") as post,
    ):
        dest.send_image(_make_ctx(tmp_path, "A"))
        dest.send_image(_make_ctx(tmp_path, "B"))
        post.assert_not_called()
        dest.teardown()

    assert post.call_count == 1
    url, payload = post.call_args.args
    assert url.endswith("/messages")
    assert len(payload["attachments"]) == 2


# ---- Graph: payload contents ----


def test_graph_carousel_payload_has_summary_and_mentions(tmp_path):
    dest = TeamsGraphDestination(
        team_name="T",
        channel_name="C",
        summary_template="KPIs for {{ today }} ({{ count }} cards)",
        mentions=[
            {"id": "user-123", "display_name": "Priya Patel"},
        ],
    )
    dest._access_token = "tok"
    dest._team_id = "team123"
    dest._channel_id = "chan123"

    with (
        patch.object(
            dest,
            "_upload_to_channel_files",
            side_effect=[_fake_uploaded("A"), _fake_uploaded("B")],
        ),
        patch.object(dest, "_post_message") as post,
    ):
        dest.send_image(_make_ctx(tmp_path, "A"))
        dest.send_image(_make_ctx(tmp_path, "B"))
        dest.teardown()

    payload = post.call_args.args[1]
    body_html = payload["body"]["content"]
    # Summary should include our template text.
    assert "KPIs for" in body_html
    assert "2 cards" in body_html
    # Mention markup + payload must both be present.
    assert '<at id="0">Priya Patel</at>' in body_html
    assert payload["mentions"][0]["mentionText"] == "Priya Patel"
    assert payload["mentions"][0]["mentioned"]["user"]["id"] == "user-123"


def test_graph_carousel_ignores_incomplete_mentions(tmp_path):
    dest = TeamsGraphDestination(
        team_name="T",
        channel_name="C",
        mentions=[
            {"id": "", "display_name": "Nobody"},
            {"id": "valid-id", "display_name": "Valid User"},
        ],
    )
    dest._access_token = "tok"
    dest._team_id = "team123"
    dest._channel_id = "chan123"

    with (
        patch.object(dest, "_upload_to_channel_files", return_value=_fake_uploaded("A")),
        patch.object(dest, "_post_message") as post,
    ):
        dest.send_image(_make_ctx(tmp_path, "A"))
        dest.teardown()
    payload = post.call_args.args[1]
    assert len(payload["mentions"]) == 1
    assert payload["mentions"][0]["mentionText"] == "Valid User"


def test_graph_carousel_has_one_attachment_block_per_card(tmp_path):
    dest = TeamsGraphDestination(team_name="T", channel_name="C")
    dest._access_token = "tok"
    dest._team_id = "team123"
    dest._channel_id = "chan123"

    with (
        patch.object(
            dest,
            "_upload_to_channel_files",
            side_effect=[_fake_uploaded("A"), _fake_uploaded("B"), _fake_uploaded("C")],
        ),
        patch.object(dest, "_post_message") as post,
    ):
        dest.send_image(_make_ctx(tmp_path, "A"))
        dest.send_image(_make_ctx(tmp_path, "B"))
        dest.send_image(_make_ctx(tmp_path, "C"))
        dest.teardown()
    body = post.call_args.args[1]["body"]["content"]
    assert body.count("<attachment") == 3


# ---- Webhook: payload_format validation ----


def test_webhook_unknown_payload_format_raises():
    with pytest.raises(TeamsDestinationError, match="payload_format"):
        TeamsWebhookDestination(webhook_url="https://x", payload_format="slack")


def test_webhook_adaptive_posts_once_per_card(tmp_path):
    dest = TeamsWebhookDestination(webhook_url="https://example.com/w")
    with patch("app.destinations.teams.requests.post") as post:
        post.return_value = MagicMock(status_code=200)
        dest.send_image(_make_ctx(tmp_path, "A"))
        dest.send_image(_make_ctx(tmp_path, "B"))
    assert post.call_count == 2


# ---- Webhook: message_card mode buffers then posts once ----


def test_webhook_message_card_posts_once(tmp_path):
    dest = TeamsWebhookDestination(
        webhook_url="https://example.com/w",
        payload_format="message_card",
        title="Daily Ops",
        facts=[{"name": "Owner", "value": "Data Team"}],
    )
    with patch("app.destinations.teams.requests.post") as post:
        post.return_value = MagicMock(status_code=200)
        dest.send_image(_make_ctx(tmp_path, "A"))
        dest.send_image(_make_ctx(tmp_path, "B"))
        post.assert_not_called()
        dest.teardown()

    assert post.call_count == 1
    payload = post.call_args.kwargs["json"]
    assert payload["@type"] == "MessageCard"
    assert payload["title"] == "Daily Ops"
    assert len(payload["sections"]) == 2
    assert payload["sections"][0]["facts"] == [{"name": "Owner", "value": "Data Team"}]


def test_webhook_message_card_sections_contain_images(tmp_path):
    dest = TeamsWebhookDestination(
        webhook_url="https://example.com/w",
        payload_format="message_card",
    )
    with patch("app.destinations.teams.requests.post") as post:
        post.return_value = MagicMock(status_code=200)
        dest.send_image(_make_ctx(tmp_path, "Orders"))
        dest.teardown()
    section = post.call_args.kwargs["json"]["sections"][0]
    assert section["activityTitle"] == "**Orders**"
    assert section["images"][0]["image"].startswith("data:image/png;base64,")
    assert section["potentialAction"][0]["@type"] == "OpenUri"


def test_webhook_message_card_summary_template(tmp_path):
    dest = TeamsWebhookDestination(
        webhook_url="https://example.com/w",
        payload_format="message_card",
        summary_template="{{ count }} insights",
    )
    with patch("app.destinations.teams.requests.post") as post:
        post.return_value = MagicMock(status_code=200)
        dest.send_image(_make_ctx(tmp_path, "A"))
        dest.send_image(_make_ctx(tmp_path, "B"))
        dest.teardown()
    payload = post.call_args.kwargs["json"]
    assert payload["summary"] == "2 insights"


def test_webhook_message_card_teardown_noop_when_empty(tmp_path):
    dest = TeamsWebhookDestination(
        webhook_url="https://example.com/w",
        payload_format="message_card",
    )
    with patch("app.destinations.teams.requests.post") as post:
        dest.teardown()
    post.assert_not_called()


def test_webhook_adaptive_mode_teardown_does_not_post(tmp_path):
    dest = TeamsWebhookDestination(webhook_url="https://example.com/w")
    with patch("app.destinations.teams.requests.post") as post:
        post.return_value = MagicMock(status_code=200)
        dest.send_image(_make_ctx(tmp_path, "A"))
        assert post.call_count == 1
        dest.teardown()
        assert post.call_count == 1
