"""Slack destination.

Ports the original ``slack_util.py`` channel-resolution loop and
``files_upload_v2`` post into the :class:`Destination` interface, plus
three optional polish features:

    * ``thread``          -- thread every card under the first upload (or
      under a supplied ``ts`` / Slack message permalink).
    * ``react_on_send``   -- add the listed reactions to every uploaded
      message (useful for triage workflows).
    * ``schedule_at``     -- schedule a text-only announcement for a
      future time via ``chat.scheduleMessage`` (Slack doesn't support
      scheduling file uploads directly; the card file is uploaded right
      away and the scheduled message links to it).

Required env: ``SLACK_BOT_USER_TOKEN``.
Slack scopes needed: ``channels:read``, ``groups:read``, ``chat:write``,
``files:write``, ``reactions:write`` (for ``react_on_send``).
"""

from __future__ import annotations

import ssl
from typing import Any

import certifi
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.configuration.settings import get_env
from app.destinations.base import DatasetContext, Destination, DestinationContext
from app.destinations.context import card_context, dataset_context
from app.templating import render_safe
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SlackDestination(Destination):
    """Send card images as files to a Slack channel."""

    key = "slack"
    label = "Slack"

    def __init__(
        self,
        channel_name: str,
        token_env: str = "SLACK_BOT_USER_TOKEN",
        comment_template: str | None = None,
        dataset_comment_template: str | None = None,
        thread: str | None = None,
        react_on_send: list[str] | None = None,
        schedule_at: str | int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            channel_name=channel_name,
            token_env=token_env,
            comment_template=comment_template,
            dataset_comment_template=dataset_comment_template,
            thread=thread,
            react_on_send=list(react_on_send or []),
            schedule_at=schedule_at,
            **kwargs,
        )
        self.channel_name = channel_name
        self._token_env = token_env
        self.comment_template = comment_template
        self.dataset_comment_template = dataset_comment_template

        self.thread_config = thread
        self.react_on_send = list(react_on_send or [])
        self.schedule_at = schedule_at

        # Resolved at first upload when ``thread == "first_card"``.
        self._thread_ts: str | None = None
        if thread and thread != "first_card":
            # Literal ts provided in YAML.
            self._thread_ts = str(thread)

        self._client: WebClient | None = None
        self._channel_id: str | None = None

    # ---- lifecycle ----

    def prepare(self) -> None:
        if self._is_dry_run():
            logger.info("[dry-run] %s: skipping Slack channel resolution.", self.describe())
            return
        token = get_env(self._token_env, required=True)
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        self._client = WebClient(token=token, ssl=ssl_context)
        self._channel_id = self._resolve_channel_id(self.channel_name)
        logger.info("Slack #%s resolved to channel ID %s", self.channel_name, self._channel_id)

    # ---- send ----

    def send_image(self, ctx: DestinationContext) -> None:
        if self._is_dry_run():
            self._log_dry_run_send(
                kind="image",
                target=f"#{self.channel_name}",
                detail=f"{ctx.card_name} ({ctx.image_path})",
            )
            return

        if self._client is None or self._channel_id is None:
            self.prepare()

        assert self._client is not None and self._channel_id is not None

        comment = self._render_comment(ctx)
        upload_kwargs: dict[str, Any] = {
            "file": ctx.image_path,
            "channel": self._channel_id,
            "title": ctx.card_url,
            "initial_comment": comment,
        }
        if self._thread_ts:
            upload_kwargs["thread_ts"] = self._thread_ts

        try:
            response = self._client.files_upload_v2(**upload_kwargs)
            assert response["file"]
            logger.info("Sent %s to Slack #%s", ctx.card_name, self.channel_name)
        except SlackApiError as exc:
            error = exc.response.get("error", "unknown")
            logger.error("Slack upload failed for %s: %s", ctx.card_name, error)
            raise

        # Capture ts from the first upload for thread: "first_card".
        self._maybe_capture_first_thread_ts(response)

        # Optional: add reactions.
        self._apply_reactions(response)

        # Optional: schedule a text announcement (runs once per send).
        self._maybe_schedule_announcement(ctx)

    def send_dataset(self, ctx: DatasetContext) -> None:
        if self._is_dry_run():
            self._log_dry_run_send(
                kind="dataset",
                target=f"#{self.channel_name}",
                detail=f"{ctx.dataset_name} ({ctx.file_path})",
            )
            return

        if self._client is None or self._channel_id is None:
            self.prepare()
        assert self._client is not None and self._channel_id is not None

        comment = self._render_dataset_comment(ctx)
        try:
            response = self._client.files_upload_v2(
                file=ctx.file_path,
                channel=self._channel_id,
                title=ctx.dataset_name,
                initial_comment=comment,
            )
            assert response["file"]
            logger.info("Uploaded dataset %s to Slack #%s", ctx.dataset_name, self.channel_name)
        except SlackApiError as exc:
            error = exc.response.get("error", "unknown")
            logger.error("Slack dataset upload failed for %s: %s", ctx.dataset_name, error)
            raise

    # ---- thread / reaction / schedule helpers ----

    def _maybe_capture_first_thread_ts(self, upload_response: Any) -> None:
        """When thread='first_card', snapshot the first upload's ``ts``.

        Slack's ``files_upload_v2`` returns a ``files`` list; each entry
        includes a ``shares`` map with the message ts. We grab the first
        available one.
        """

        if self.thread_config != "first_card" or self._thread_ts:
            return
        ts = _extract_ts_from_upload(upload_response)
        if ts:
            self._thread_ts = ts
            logger.debug(
                "Slack thread anchor captured: ts=%s channel=%s",
                ts,
                self.channel_name,
            )

    def _apply_reactions(self, upload_response: Any) -> None:
        if not self.react_on_send or self._client is None:
            return
        ts = _extract_ts_from_upload(upload_response)
        if not ts or self._channel_id is None:
            logger.warning("Could not resolve message ts from Slack upload; skipping reactions.")
            return
        for emoji in self.react_on_send:
            emoji_name = emoji.strip(":")
            if not emoji_name:
                continue
            try:
                self._client.reactions_add(
                    channel=self._channel_id,
                    name=emoji_name,
                    timestamp=ts,
                )
            except SlackApiError as exc:
                error = exc.response.get("error", "unknown")
                if error == "already_reacted":
                    continue
                logger.warning("Slack reactions_add failed for :%s: %s", emoji_name, error)

    def _maybe_schedule_announcement(self, ctx: DestinationContext) -> None:
        if not self.schedule_at or self._client is None or self._channel_id is None:
            return
        post_at = _normalize_schedule_at(self.schedule_at)
        if post_at is None:
            logger.warning(
                "Slack schedule_at=%r could not be parsed; skipping scheduled message.",
                self.schedule_at,
            )
            return
        body = self._render_comment(ctx) or ctx.card_name
        try:
            self._client.chat_scheduleMessage(
                channel=self._channel_id,
                post_at=post_at,
                text=f"{body}\n{ctx.card_url}",
                thread_ts=self._thread_ts,
            )
            logger.info("Scheduled Slack message for %s at %s", ctx.card_name, post_at)
        except SlackApiError as exc:
            error = exc.response.get("error", "unknown")
            logger.warning("Slack chat_scheduleMessage failed: %s", error)

    # ---- templating ----

    def _render_comment(self, ctx: DestinationContext) -> str:
        if not self.comment_template:
            return ctx.card_name
        return render_safe(
            self.comment_template,
            card_context(ctx),
            fallback=ctx.card_name,
        )

    def _render_dataset_comment(self, ctx: DatasetContext) -> str:
        default = f"Dataset: {ctx.dataset_name}"
        if not self.dataset_comment_template:
            return default
        return render_safe(
            self.dataset_comment_template,
            dataset_context(ctx),
            fallback=default,
        )

    # ---- internals ----

    def _resolve_channel_id(self, channel_name: str) -> str:
        """Page through ``conversations.list`` looking for ``channel_name``.

        Mirrors the loop from the original ``slack_util.get_slack_channel_id``.
        """

        assert self._client is not None
        cursor: str | None = None
        calls = 0
        while True:
            calls += 1
            kwargs: dict[str, Any] = {"exclude_archived": True, "limit": 1000}
            if cursor:
                kwargs["cursor"] = cursor
            response = self._client.conversations_list(**kwargs)
            for channel in response.get("channels", []):
                if channel.get("name") == channel_name:
                    logger.debug("Found Slack channel %s after %d API call(s)", channel_name, calls)
                    return channel["id"]
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        raise SlackApiError(
            f"Could not find Slack channel #{channel_name} after {calls} API call(s). "
            f"Make sure the bot is invited to the channel.",
            response={"ok": False, "error": "channel_not_found"},
        )


def _extract_ts_from_upload(response: Any) -> str | None:
    """Best-effort fish for a message ``ts`` out of ``files_upload_v2``'s response.

    Shape varies across slack_sdk versions -- we check the usual places.
    """

    try:
        files = response.get("files") or []
    except AttributeError:
        return None
    if not files:
        return None
    first = files[0]
    shares = first.get("shares") or {}
    for channel_map in (shares.get("public") or {}, shares.get("private") or {}):
        for _chan, entries in channel_map.items():
            if entries and isinstance(entries, list):
                ts = entries[0].get("ts")
                if ts:
                    return str(ts)
    # Fallback: some API shapes include a top-level "ts".
    ts = first.get("ts") or response.get("ts")
    return str(ts) if ts else None


def _normalize_schedule_at(value: str | int | float) -> int | None:
    """Coerce a ``schedule_at`` value into a Unix timestamp (seconds).

    Accepts an ``int`` / ``float`` (already an epoch time) or ISO-8601
    string (``"2026-04-21T14:00:00Z"`` or ``"2026-04-21 14:00:00"``).
    Returns ``None`` on parse failure.
    """

    import datetime as _dt

    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        normalized = text.replace("Z", "+00:00")
        dt = _dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return int(dt.timestamp())
