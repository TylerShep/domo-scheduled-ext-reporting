"""Microsoft Teams destination.

Two ``auth_mode`` strategies:

``graph`` -- Recommended. Uses the Microsoft Graph API with an Azure AD app
    registration (client-credentials flow). Uploads the image to the
    channel's SharePoint folder and posts a chatMessage that attaches it.
    Required env: ``TEAMS_TENANT_ID``, ``TEAMS_CLIENT_ID``,
    ``TEAMS_CLIENT_SECRET``.
    Required Graph application permissions:
        ChannelMessage.Send, Files.ReadWrite.All, Group.Read.All

``webhook`` -- Simple fallback. Posts an Adaptive Card to a per-channel
    Incoming Webhook URL with the image base64-inlined. No file lives in
    SharePoint, but it works without admin consent on the tenant.
    Required env: ``<webhook_url_env>`` (default: ``TEAMS_WEBHOOK_URL``).
"""

from __future__ import annotations

import base64
import json
from typing import Any

import msal
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.configuration.settings import get_env
from app.destinations.base import Destination, DestinationContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


class TeamsDestinationError(RuntimeError):
    """Raised on Teams send failures (Graph API or webhook)."""


def make_teams_destination(**config: Any) -> Destination:
    """Factory that picks the right Teams subclass based on ``auth_mode``."""

    auth_mode = config.pop("auth_mode", "graph").lower()
    if auth_mode == "graph":
        return TeamsGraphDestination(**config)
    if auth_mode == "webhook":
        return TeamsWebhookDestination(**config)
    raise TeamsDestinationError(
        f"Unknown Teams auth_mode={auth_mode!r}. Expected 'graph' or 'webhook'."
    )


# ---------------------------------------------------------------------------
# Graph API
# ---------------------------------------------------------------------------

class TeamsGraphDestination(Destination):
    """Send card images via the Microsoft Graph API (full file uploads)."""

    key = "teams"
    label = "Teams (Graph)"

    def __init__(
        self,
        team_name: str | None = None,
        team_id: str | None = None,
        channel_name: str | None = None,
        channel_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            team_name=team_name,
            team_id=team_id,
            channel_name=channel_name,
            channel_id=channel_id,
            **kwargs,
        )
        if not (team_id or team_name):
            raise TeamsDestinationError("Provide either `team_id` or `team_name`.")
        if not (channel_id or channel_name):
            raise TeamsDestinationError("Provide either `channel_id` or `channel_name`.")
        self._team_name = team_name
        self._team_id: str | None = team_id
        self._channel_name = channel_name
        self._channel_id: str | None = channel_id
        self._access_token: str | None = None

    # ---- lifecycle ----

    def prepare(self) -> None:
        self._access_token = self._acquire_token()
        if not self._team_id:
            self._team_id = self._resolve_team_id(self._team_name or "")
        if not self._channel_id:
            self._channel_id = self._resolve_channel_id(self._team_id, self._channel_name or "")
        logger.info(
            "Teams (Graph) %s/#%s resolved -> team_id=%s channel_id=%s",
            self._team_name or self._team_id,
            self._channel_name or self._channel_id,
            self._team_id,
            self._channel_id,
        )

    # ---- send ----

    @retry(
        retry=retry_if_exception_type(TeamsDestinationError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def send_image(self, ctx: DestinationContext) -> None:
        if not self._access_token or not self._team_id or not self._channel_id:
            self.prepare()
        assert self._access_token and self._team_id and self._channel_id

        item = self._upload_to_channel_files(self._team_id, self._channel_id, ctx.image_path)
        self._post_chat_message(self._team_id, self._channel_id, ctx, item)
        logger.info("Sent %s to Teams channel %s", ctx.card_name, self._channel_name)

    # ---- internals ----

    def _acquire_token(self) -> str:
        tenant_id = get_env("TEAMS_TENANT_ID", required=True)
        client_id = get_env("TEAMS_CLIENT_ID", required=True)
        client_secret = get_env("TEAMS_CLIENT_SECRET", required=True)

        app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        result = app.acquire_token_for_client(scopes=_GRAPH_SCOPE)
        if "access_token" not in result:
            raise TeamsDestinationError(
                f"Could not acquire Graph token: {result.get('error_description', result)}"
            )
        return result["access_token"]

    def _headers(self, content_type: str | None = "application/json") -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._access_token}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _resolve_team_id(self, team_name: str) -> str:
        url = f"{_GRAPH_BASE}/groups"
        params = {
            "$filter": f"displayName eq '{team_name}' and resourceProvisioningOptions/Any(x:x eq 'Team')",
            "$select": "id,displayName",
        }
        # The filter requires this header.
        headers = self._headers()
        headers["ConsistencyLevel"] = "eventual"
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code >= 400:
            raise TeamsDestinationError(
                f"Failed to resolve Teams team={team_name!r}: {response.status_code} {response.text}"
            )
        values = response.json().get("value", [])
        if not values:
            raise TeamsDestinationError(f"No Microsoft Teams team named {team_name!r} found.")
        return values[0]["id"]

    def _resolve_channel_id(self, team_id: str, channel_name: str) -> str:
        url = f"{_GRAPH_BASE}/teams/{team_id}/channels"
        params = {"$filter": f"displayName eq '{channel_name}'", "$select": "id,displayName"}
        response = requests.get(url, headers=self._headers(), params=params, timeout=30)
        if response.status_code >= 400:
            raise TeamsDestinationError(
                f"Failed to resolve Teams channel={channel_name!r}: "
                f"{response.status_code} {response.text}"
            )
        values = response.json().get("value", [])
        if not values:
            raise TeamsDestinationError(
                f"No Teams channel named {channel_name!r} in team {team_id!r}."
            )
        return values[0]["id"]

    def _upload_to_channel_files(
        self, team_id: str, channel_id: str, file_path: str
    ) -> dict[str, Any]:
        """Upload a file to the channel's ``Files`` folder via SharePoint."""

        folder_url = (
            f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/filesFolder"
        )
        folder = requests.get(folder_url, headers=self._headers(), timeout=30)
        if folder.status_code >= 400:
            raise TeamsDestinationError(
                f"Could not look up channel filesFolder: {folder.status_code} {folder.text}"
            )
        folder_data = folder.json()
        drive_id = folder_data["parentReference"]["driveId"]
        folder_path = folder_data["name"]

        with open(file_path, "rb") as fh:
            data = fh.read()
        file_name = file_path.rsplit("/", 1)[-1]

        upload_url = (
            f"{_GRAPH_BASE}/drives/{drive_id}/root:/"
            f"{folder_path}/{file_name}:/content"
        )
        response = requests.put(
            upload_url,
            headers=self._headers(content_type="image/png"),
            data=data,
            timeout=60,
        )
        if response.status_code >= 400:
            raise TeamsDestinationError(
                f"SharePoint upload failed: {response.status_code} {response.text}"
            )
        return response.json()

    def _post_chat_message(
        self,
        team_id: str,
        channel_id: str,
        ctx: DestinationContext,
        uploaded: dict[str, Any],
    ) -> None:
        url = f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages"
        attachment_id = uploaded["eTag"].strip('"').split(",")[0]
        body_html = (
            f'<p><strong>{_escape(ctx.card_name)}</strong></p>'
            f'<p><a href="{_escape(ctx.card_url)}">Open card in Domo</a></p>'
            f'<attachment id="{attachment_id}"></attachment>'
        )
        payload = {
            "body": {"contentType": "html", "content": body_html},
            "attachments": [
                {
                    "id": attachment_id,
                    "contentType": "reference",
                    "contentUrl": uploaded["webUrl"],
                    "name": uploaded["name"],
                }
            ],
        }
        response = requests.post(
            url,
            headers=self._headers(),
            data=json.dumps(payload),
            timeout=30,
        )
        if response.status_code >= 400:
            raise TeamsDestinationError(
                f"chatMessage POST failed: {response.status_code} {response.text}"
            )


# ---------------------------------------------------------------------------
# Webhook (no Graph permissions required)
# ---------------------------------------------------------------------------

class TeamsWebhookDestination(Destination):
    """Send card images to an Incoming Webhook as Adaptive Cards."""

    key = "teams"
    label = "Teams (Webhook)"

    def __init__(
        self,
        webhook_url: str | None = None,
        webhook_url_env: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(webhook_url=webhook_url, webhook_url_env=webhook_url_env, **kwargs)
        if not webhook_url and not webhook_url_env:
            raise TeamsDestinationError(
                "Provide either `webhook_url` or `webhook_url_env`."
            )
        self._webhook_url = webhook_url
        self._webhook_url_env = webhook_url_env or "TEAMS_WEBHOOK_URL"

    def prepare(self) -> None:
        if not self._webhook_url:
            self._webhook_url = get_env(self._webhook_url_env, required=True)

    @retry(
        retry=retry_if_exception_type(TeamsDestinationError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def send_image(self, ctx: DestinationContext) -> None:
        if not self._webhook_url:
            self.prepare()
        assert self._webhook_url

        with open(ctx.image_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")

        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "type": "AdaptiveCard",
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "version": "1.4",
                        "body": [
                            {"type": "TextBlock", "text": ctx.card_name, "weight": "Bolder", "size": "Medium"},
                            {"type": "Image", "url": f"data:image/png;base64,{b64}"},
                        ],
                        "actions": [
                            {"type": "Action.OpenUrl", "title": "Open in Domo", "url": ctx.card_url},
                        ],
                    },
                }
            ],
        }
        response = requests.post(self._webhook_url, json=payload, timeout=30)
        if response.status_code >= 400:
            raise TeamsDestinationError(
                f"Teams webhook POST failed: {response.status_code} {response.text}"
            )
        logger.info("Sent %s to Teams webhook", ctx.card_name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _escape(value: str) -> str:
    """Tiny HTML escaper for safe insertion into Teams chat-message content."""

    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
