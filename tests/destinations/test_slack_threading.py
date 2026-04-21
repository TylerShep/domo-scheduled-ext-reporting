"""Tests for Slack threading, reactions, and scheduled announcements (Wave 9)."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock

from app.destinations.base import DestinationContext
from app.destinations.slack import (
    SlackDestination,
    _extract_ts_from_upload,
    _normalize_schedule_at,
)


def _make_ctx(tmp_path, name: str = "Rev") -> DestinationContext:
    path = tmp_path / f"{name}.png"
    path.write_bytes(b"\x89PNG fake")
    return DestinationContext(
        image_path=str(path),
        card_name=name,
        card_url=f"https://domo.example.com/c/{name}",
        page_name="Sales",
    )


def _upload_response(ts: str, name: str = "Rev") -> dict:
    return {
        "file": {"id": f"F_{name}"},
        "files": [
            {
                "id": f"F_{name}",
                "shares": {"public": {"C1": [{"ts": ts}]}},
            }
        ],
    }


# ---- _extract_ts_from_upload ----


def test_extract_ts_from_public_shares():
    resp = _upload_response("1700000000.0001")
    assert _extract_ts_from_upload(resp) == "1700000000.0001"


def test_extract_ts_from_private_shares():
    resp = {"files": [{"shares": {"private": {"C2": [{"ts": "1700000123.4567"}]}}}]}
    assert _extract_ts_from_upload(resp) == "1700000123.4567"


def test_extract_ts_empty_shares_returns_none():
    assert _extract_ts_from_upload({"files": [{}]}) is None


def test_extract_ts_handles_bad_input():
    assert _extract_ts_from_upload("not a dict") is None
    assert _extract_ts_from_upload(None) is None


# ---- _normalize_schedule_at ----


def test_normalize_schedule_at_int_passthrough():
    assert _normalize_schedule_at(1700000000) == 1700000000


def test_normalize_schedule_at_numeric_string():
    assert _normalize_schedule_at("1700000000") == 1700000000


def test_normalize_schedule_at_iso_z():
    ts = _normalize_schedule_at("2030-01-01T00:00:00Z")
    # Jan 1 2030 UTC
    assert ts == int(datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc).timestamp())


def test_normalize_schedule_at_iso_naive_assumes_utc():
    ts = _normalize_schedule_at("2030-01-01 12:00:00")
    assert ts == int(datetime.datetime(2030, 1, 1, 12, tzinfo=datetime.timezone.utc).timestamp())


def test_normalize_schedule_at_invalid_returns_none():
    assert _normalize_schedule_at("totally bogus") is None
    assert _normalize_schedule_at("") is None
    assert _normalize_schedule_at(None) is None  # type: ignore[arg-type]


# ---- threading ----


def test_thread_literal_ts_applied_to_every_upload(tmp_path):
    dest = SlackDestination(channel_name="data", thread="1699999999.9999")
    client = MagicMock()
    client.files_upload_v2.return_value = _upload_response("1111.1")
    dest._client = client
    dest._channel_id = "C1"

    dest.send_image(_make_ctx(tmp_path, "A"))
    dest.send_image(_make_ctx(tmp_path, "B"))

    for call in client.files_upload_v2.call_args_list:
        assert call.kwargs["thread_ts"] == "1699999999.9999"


def test_thread_first_card_uses_first_upload_ts(tmp_path):
    dest = SlackDestination(channel_name="data", thread="first_card")
    client = MagicMock()
    client.files_upload_v2.side_effect = [
        _upload_response("1700000000.0001", "A"),
        _upload_response("1700000000.0002", "B"),
        _upload_response("1700000000.0003", "C"),
    ]
    dest._client = client
    dest._channel_id = "C1"

    dest.send_image(_make_ctx(tmp_path, "A"))
    dest.send_image(_make_ctx(tmp_path, "B"))
    dest.send_image(_make_ctx(tmp_path, "C"))

    calls = client.files_upload_v2.call_args_list
    assert "thread_ts" not in calls[0].kwargs
    assert calls[1].kwargs["thread_ts"] == "1700000000.0001"
    assert calls[2].kwargs["thread_ts"] == "1700000000.0001"


def test_thread_first_card_when_ts_missing(tmp_path):
    """If the first upload response has no ts, subsequent uploads stay flat (no throw)."""

    dest = SlackDestination(channel_name="data", thread="first_card")
    client = MagicMock()
    client.files_upload_v2.side_effect = [
        {"file": {"id": "F1"}, "files": [{}]},  # no ts
        _upload_response("1700000000.0002", "B"),
    ]
    dest._client = client
    dest._channel_id = "C1"
    dest.send_image(_make_ctx(tmp_path, "A"))
    dest.send_image(_make_ctx(tmp_path, "B"))
    # 2nd call still goes flat because first had no ts.
    assert "thread_ts" not in client.files_upload_v2.call_args_list[1].kwargs


# ---- reactions ----


def test_react_on_send_adds_reactions(tmp_path):
    dest = SlackDestination(
        channel_name="data",
        react_on_send=["eyes", ":chart_with_upwards_trend:"],
    )
    client = MagicMock()
    client.files_upload_v2.return_value = _upload_response("1700000000.0001")
    dest._client = client
    dest._channel_id = "C1"

    dest.send_image(_make_ctx(tmp_path))

    calls = client.reactions_add.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["name"] == "eyes"
    assert calls[1].kwargs["name"] == "chart_with_upwards_trend"
    for call in calls:
        assert call.kwargs["timestamp"] == "1700000000.0001"
        assert call.kwargs["channel"] == "C1"


def test_reactions_noop_when_ts_cant_be_resolved(tmp_path):
    dest = SlackDestination(channel_name="data", react_on_send=["eyes"])
    client = MagicMock()
    client.files_upload_v2.return_value = {"file": {"id": "F1"}, "files": [{}]}
    dest._client = client
    dest._channel_id = "C1"

    dest.send_image(_make_ctx(tmp_path))
    client.reactions_add.assert_not_called()


def test_reactions_swallow_already_reacted(tmp_path):
    from slack_sdk.errors import SlackApiError

    dest = SlackDestination(channel_name="data", react_on_send=["eyes"])
    client = MagicMock()
    client.files_upload_v2.return_value = _upload_response("1700000000.0001")
    client.reactions_add.side_effect = SlackApiError(
        "already reacted",
        response={"ok": False, "error": "already_reacted"},
    )
    dest._client = client
    dest._channel_id = "C1"

    dest.send_image(_make_ctx(tmp_path))
    # Should not raise.


# ---- schedule_at ----


def test_schedule_at_iso_calls_chat_schedule_message(tmp_path):
    dest = SlackDestination(channel_name="data", schedule_at="2030-01-01T00:00:00Z")
    client = MagicMock()
    client.files_upload_v2.return_value = _upload_response("1700000000.0001")
    dest._client = client
    dest._channel_id = "C1"

    dest.send_image(_make_ctx(tmp_path))

    client.chat_scheduleMessage.assert_called_once()
    kwargs = client.chat_scheduleMessage.call_args.kwargs
    assert kwargs["channel"] == "C1"
    assert kwargs["post_at"] == int(
        datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
    )


def test_schedule_at_epoch_int(tmp_path):
    dest = SlackDestination(channel_name="data", schedule_at=1999999999)
    client = MagicMock()
    client.files_upload_v2.return_value = _upload_response("1700000000.0001")
    dest._client = client
    dest._channel_id = "C1"
    dest.send_image(_make_ctx(tmp_path))
    assert client.chat_scheduleMessage.call_args.kwargs["post_at"] == 1999999999


def test_schedule_at_unparseable_value_logs_and_skips(tmp_path, caplog):
    dest = SlackDestination(channel_name="data", schedule_at="tomorrow")
    client = MagicMock()
    client.files_upload_v2.return_value = _upload_response("1700000000.0001")
    dest._client = client
    dest._channel_id = "C1"

    with caplog.at_level("WARNING"):
        dest.send_image(_make_ctx(tmp_path))

    client.chat_scheduleMessage.assert_not_called()
    assert any("schedule_at" in r.message for r in caplog.records)


def test_schedule_at_respects_thread_anchor(tmp_path):
    dest = SlackDestination(
        channel_name="data",
        schedule_at="2030-01-01T00:00:00Z",
        thread="first_card",
    )
    client = MagicMock()
    client.files_upload_v2.side_effect = [
        _upload_response("1700000000.0001", "A"),
        _upload_response("1700000000.0002", "B"),
    ]
    dest._client = client
    dest._channel_id = "C1"

    dest.send_image(_make_ctx(tmp_path, "A"))
    dest.send_image(_make_ctx(tmp_path, "B"))

    # Second send should schedule as a threaded reply.
    kwargs = client.chat_scheduleMessage.call_args_list[1].kwargs
    assert kwargs["thread_ts"] == "1700000000.0001"


# ---- registry wiring ----


def test_registry_accepts_thread_and_reactions():
    from app.destinations.registry import build_destination

    dest = build_destination(
        {
            "type": "slack",
            "channel_name": "x",
            "thread": "first_card",
            "react_on_send": ["eyes"],
        }
    )
    assert isinstance(dest, SlackDestination)
    assert dest.thread_config == "first_card"
    assert dest.react_on_send == ["eyes"]
