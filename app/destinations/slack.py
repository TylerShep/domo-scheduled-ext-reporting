"""Slack destination.

Ports the original ``slack_util.py`` channel-resolution loop and
``files_upload_v2`` post into the :class:`Destination` interface.

Required env: ``SLACK_BOT_USER_TOKEN``.
Slack scopes needed: ``channels:read``, ``groups:read``, ``chat:write``,
``files:write``.
"""

from __future__ import annotations

import ssl
from typing import Any

import certifi
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.configuration.settings import get_env
from app.destinations.base import Destination, DestinationContext
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
        **kwargs: Any,
    ) -> None:
        super().__init__(channel_name=channel_name, token_env=token_env, **kwargs)
        self.channel_name = channel_name
        self._token_env = token_env
        self._client: WebClient | None = None
        self._channel_id: str | None = None

    # ---- lifecycle ----

    def prepare(self) -> None:
        token = get_env(self._token_env, required=True)
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        self._client = WebClient(token=token, ssl=ssl_context)
        self._channel_id = self._resolve_channel_id(self.channel_name)
        logger.info("Slack #%s resolved to channel ID %s", self.channel_name, self._channel_id)

    # ---- send ----

    def send_image(self, ctx: DestinationContext) -> None:
        if self._client is None or self._channel_id is None:
            self.prepare()

        assert self._client is not None and self._channel_id is not None

        try:
            response = self._client.files_upload_v2(
                file=ctx.image_path,
                channel=self._channel_id,
                title=ctx.card_url,
                initial_comment=ctx.card_name,
            )
            assert response["file"]
            logger.info("Sent %s to Slack #%s", ctx.card_name, self.channel_name)
        except SlackApiError as exc:
            error = exc.response.get("error", "unknown")
            logger.error("Slack upload failed for %s: %s", ctx.card_name, error)
            raise

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
                    logger.debug(
                        "Found Slack channel %s after %d API call(s)", channel_name, calls
                    )
                    return channel["id"]
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        raise SlackApiError(
            f"Could not find Slack channel #{channel_name} after {calls} API call(s). "
            f"Make sure the bot is invited to the channel.",
            response={"ok": False, "error": "channel_not_found"},
        )
