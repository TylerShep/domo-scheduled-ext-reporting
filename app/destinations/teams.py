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
from collections.abc import Sequence
from typing import Any

import msal
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.configuration.settings import get_env
from app.destinations.base import (
    DatasetContext,
    Destination,
    DestinationContext,
)
from app.destinations.context import card_context
from app.templating import render_safe
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
    """Send card images via the Microsoft Graph API (full file uploads).

    ``batch_mode`` controls how card images are grouped into chat
    messages:

    * ``"single_carousel"`` (default) -- buffer every card during the
      run and post one chatMessage at teardown. The message has a
      summary header (``summary_template``) and one ``<attachment>``
      per card, with optional ``@`` mentions of Azure AD users.
    * ``"per_message"`` -- legacy v1 behaviour, one chatMessage per
      card. Use when the channel has retention rules that dislike
      mass-attached messages.
    """

    key = "teams"
    label = "Teams (Graph)"

    def __init__(
        self,
        team_name: str | None = None,
        team_id: str | None = None,
        channel_name: str | None = None,
        channel_id: str | None = None,
        caption_template: str | None = None,
        batch_mode: str = "single_carousel",
        summary_template: str | None = None,
        mentions: Sequence[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            team_name=team_name,
            team_id=team_id,
            channel_name=channel_name,
            channel_id=channel_id,
            caption_template=caption_template,
            batch_mode=batch_mode,
            summary_template=summary_template,
            mentions=list(mentions or []),
            **kwargs,
        )
        if not (team_id or team_name):
            raise TeamsDestinationError("Provide either `team_id` or `team_name`.")
        if not (channel_id or channel_name):
            raise TeamsDestinationError("Provide either `channel_id` or `channel_name`.")
        if batch_mode not in {"single_carousel", "per_message"}:
            raise TeamsDestinationError("batch_mode must be 'single_carousel' or 'per_message'")
        self._team_name = team_name
        self._team_id: str | None = team_id
        self._channel_name = channel_name
        self._channel_id: str | None = channel_id
        self.caption_template = caption_template
        self.batch_mode = batch_mode
        self.summary_template = summary_template
        self.mentions = list(mentions or [])
        self._access_token: str | None = None
        self._pending: list[dict[str, Any]] = []

    # ---- lifecycle ----

    def prepare(self) -> None:
        if self._is_dry_run():
            logger.info(
                "[dry-run] %s: skipping Teams token + channel resolution.",
                self.describe(),
            )
            return
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
        if self._is_dry_run():
            self._log_dry_run_send(
                kind="image",
                target=self._channel_name or self._channel_id or "?",
                detail=f"{ctx.card_name} ({ctx.image_path})",
            )
            return

        if not self._access_token or not self._team_id or not self._channel_id:
            self.prepare()
        assert self._access_token and self._team_id and self._channel_id

        uploaded = self._upload_to_channel_files(
            self._team_id, self._channel_id, ctx.image_path, content_type="image/png"
        )

        if self.batch_mode == "per_message":
            self._post_single_card_message(self._team_id, self._channel_id, ctx, uploaded)
            logger.info("Sent %s to Teams channel %s", ctx.card_name, self._channel_name)
            return

        # single_carousel: buffer for teardown
        self._pending.append({"ctx": ctx, "uploaded": uploaded})
        logger.debug(
            "Buffered %s for Teams single_carousel post (%d pending)",
            ctx.card_name,
            len(self._pending),
        )

    def teardown(self) -> None:
        if self.batch_mode != "single_carousel":
            self._pending = []
            return
        if not self._pending:
            return
        if self._is_dry_run():
            self._log_dry_run_send(
                kind="carousel",
                target=self._channel_name or self._channel_id or "?",
                detail=f"{len(self._pending)} card(s)",
            )
            self._pending = []
            return
        if not self._access_token or not self._team_id or not self._channel_id:
            self.prepare()
        assert self._access_token and self._team_id and self._channel_id

        self._post_carousel_message(self._team_id, self._channel_id, self._pending)
        logger.info(
            "Posted Teams carousel with %d card(s) to %s",
            len(self._pending),
            self._channel_name,
        )
        self._pending = []

    def send_dataset(self, ctx: DatasetContext) -> None:
        if self._is_dry_run():
            self._log_dry_run_send(
                kind="dataset",
                target=self._channel_name or self._channel_id or "?",
                detail=f"{ctx.dataset_name} ({ctx.file_path})",
            )
            return

        if not self._access_token or not self._team_id or not self._channel_id:
            self.prepare()
        assert self._access_token and self._team_id and self._channel_id

        content_type = (
            "text/csv"
            if ctx.file_format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        self._upload_to_channel_files(
            self._team_id, self._channel_id, ctx.file_path, content_type=content_type
        )
        logger.info(
            "Uploaded dataset %s (%s) to Teams channel %s",
            ctx.dataset_name,
            ctx.file_format,
            self._channel_name,
        )

    # ---- internals ----

    def _render_caption(self, ctx: DestinationContext) -> str:
        """Render an optional per-card caption. Returns an empty string if
        no template is set so the original HTML layout is preserved.
        """

        if not self.caption_template:
            return ""
        caption = render_safe(
            self.caption_template,
            card_context(ctx),
            fallback="",
        )
        if not caption:
            return ""
        # The caption is treated as plain text; wrap it in a paragraph so
        # it renders cleanly in the Teams chatMessage HTML body.
        return f"<p>{_escape(caption)}</p>"

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
        self,
        team_id: str,
        channel_id: str,
        file_path: str,
        content_type: str = "image/png",
    ) -> dict[str, Any]:
        """Upload a file to the channel's ``Files`` folder via SharePoint."""

        folder_url = f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/filesFolder"
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

        upload_url = f"{_GRAPH_BASE}/drives/{drive_id}/root:/" f"{folder_path}/{file_name}:/content"
        response = requests.put(
            upload_url,
            headers=self._headers(content_type=content_type),
            data=data,
            timeout=60,
        )
        if response.status_code >= 400:
            raise TeamsDestinationError(
                f"SharePoint upload failed: {response.status_code} {response.text}"
            )
        return response.json()

    def _post_single_card_message(
        self,
        team_id: str,
        channel_id: str,
        ctx: DestinationContext,
        uploaded: dict[str, Any],
    ) -> None:
        """Legacy per-message mode: one chatMessage per card."""

        url = f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages"
        attachment_id = _attachment_id_from_etag(uploaded["eTag"])
        caption_html = self._render_caption(ctx)
        body_html = (
            f"{caption_html}"
            f"<p><strong>{_escape(ctx.card_name)}</strong></p>"
            f'<p><a href="{_escape(ctx.card_url)}">Open card in Domo</a></p>'
            f'<attachment id="{attachment_id}"></attachment>'
        )
        payload = {
            "body": {"contentType": "html", "content": body_html},
            "attachments": [
                _message_attachment(attachment_id, uploaded),
            ],
        }
        self._post_message(url, payload)

    def _post_carousel_message(
        self,
        team_id: str,
        channel_id: str,
        pending: list[dict[str, Any]],
    ) -> None:
        """single_carousel mode: summary header + one attachment per card."""

        url = f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages"

        attachments_meta: list[tuple[str, dict[str, Any]]] = []
        for entry in pending:
            attachment_id = _attachment_id_from_etag(entry["uploaded"]["eTag"])
            attachments_meta.append((attachment_id, entry["uploaded"]))

        summary_html = self._render_summary(pending)
        mention_html, mention_payload = self._build_mentions()

        sections: list[str] = [summary_html, mention_html]
        for entry, (attachment_id, _) in zip(pending, attachments_meta):
            ctx = entry["ctx"]
            caption_html = self._render_caption(ctx)
            sections.append(
                f"<hr/>"
                f"{caption_html}"
                f"<p><strong>{_escape(ctx.card_name)}</strong></p>"
                f'<p><a href="{_escape(ctx.card_url)}">Open in Domo</a></p>'
                f'<attachment id="{attachment_id}"></attachment>'
            )

        payload: dict[str, Any] = {
            "body": {
                "contentType": "html",
                "content": "".join(s for s in sections if s),
            },
            "attachments": [
                _message_attachment(att_id, uploaded) for att_id, uploaded in attachments_meta
            ],
        }
        if mention_payload:
            payload["mentions"] = mention_payload
        self._post_message(url, payload)

    def _post_message(self, url: str, payload: dict[str, Any]) -> None:
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

    def _render_summary(self, pending: list[dict[str, Any]]) -> str:
        """Render the summary header HTML block.

        Default shows ``"{n} cards -- {today}"``. Users can override with
        ``summary_template`` (full Jinja env).
        """

        template = self.summary_template or (
            "{{ count }} card{{ 's' if count != 1 else '' }} -- {{ today }}"
        )
        context = {
            "count": len(pending),
            "cards": [
                {
                    "name": p["ctx"].card_name,
                    "url": p["ctx"].card_url,
                    "page_name": p["ctx"].page_name,
                }
                for p in pending
            ],
        }
        context.update(_today_ctx())
        text = render_safe(template, context, fallback="")
        return f"<p><strong>{_escape(text)}</strong></p>" if text else ""

    def _build_mentions(self) -> tuple[str, list[dict[str, Any]]]:
        """Return ``(html_snippet, mentions_payload)`` for AAD mentions.

        ``mentions`` config items look like::

            - id: "00000000-1111-2222-3333-444444444444"
              display_name: "Priya Patel"

        We add one ``<at id="N">Name</at>`` tag in the chat body and a
        corresponding entry in the ``mentions`` payload array.
        """

        if not self.mentions:
            return "", []
        html_parts: list[str] = []
        payload: list[dict[str, Any]] = []
        for idx, m in enumerate(self.mentions):
            aad_id = str(m.get("id") or "").strip()
            name = str(m.get("display_name") or m.get("name") or "").strip()
            if not aad_id or not name:
                continue
            html_parts.append(f'<at id="{idx}">{_escape(name)}</at>')
            payload.append(
                {
                    "id": idx,
                    "mentionText": name,
                    "mentioned": {
                        "user": {
                            "id": aad_id,
                            "displayName": name,
                            "userIdentityType": "aadUser",
                        }
                    },
                }
            )
        if not html_parts:
            return "", []
        return f"<p>{' '.join(html_parts)}</p>", payload


# ---------------------------------------------------------------------------
# Webhook (no Graph permissions required)
# ---------------------------------------------------------------------------


class TeamsWebhookDestination(Destination):
    """Send card images to an Incoming Webhook.

    ``payload_format`` picks the webhook body:

    * ``"adaptive"`` (default) -- one Adaptive-Card POST per ``send_image``.
      Good for small reports; each card renders independently in the
      channel.
    * ``"message_card"`` -- buffer everything and post a single
      legacy Office 365 ``MessageCard`` at teardown, with one ``section``
      per card and an optional ``facts`` table.
    """

    key = "teams"
    label = "Teams (Webhook)"

    def __init__(
        self,
        webhook_url: str | None = None,
        webhook_url_env: str | None = None,
        caption_template: str | None = None,
        payload_format: str = "adaptive",
        title: str | None = None,
        facts: Sequence[dict[str, str]] | None = None,
        summary_template: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            webhook_url=webhook_url,
            webhook_url_env=webhook_url_env,
            caption_template=caption_template,
            payload_format=payload_format,
            title=title,
            facts=list(facts or []),
            summary_template=summary_template,
            **kwargs,
        )
        if not webhook_url and not webhook_url_env:
            raise TeamsDestinationError("Provide either `webhook_url` or `webhook_url_env`.")
        if payload_format not in {"adaptive", "message_card"}:
            raise TeamsDestinationError("payload_format must be 'adaptive' or 'message_card'")
        self._webhook_url = webhook_url
        self._webhook_url_env = webhook_url_env or "TEAMS_WEBHOOK_URL"
        self.caption_template = caption_template
        self.payload_format = payload_format
        self.title = title
        self.facts = list(facts or [])
        self.summary_template = summary_template
        self._pending: list[dict[str, Any]] = []

    def prepare(self) -> None:
        if self._is_dry_run():
            return
        if not self._webhook_url:
            self._webhook_url = get_env(self._webhook_url_env, required=True)

    @retry(
        retry=retry_if_exception_type(TeamsDestinationError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def send_image(self, ctx: DestinationContext) -> None:
        if self._is_dry_run():
            self._log_dry_run_send(
                kind="image",
                target="webhook",
                detail=f"{ctx.card_name} ({ctx.image_path})",
            )
            return

        if not self._webhook_url:
            self.prepare()
        assert self._webhook_url

        if self.payload_format == "message_card":
            with open(ctx.image_path, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode("ascii")
            self._pending.append({"ctx": ctx, "b64": b64})
            logger.debug(
                "Buffered %s for Teams MessageCard (%d pending)",
                ctx.card_name,
                len(self._pending),
            )
            return

        payload = self._build_adaptive_payload(ctx)
        response = requests.post(self._webhook_url, json=payload, timeout=30)
        if response.status_code >= 400:
            raise TeamsDestinationError(
                f"Teams webhook POST failed: {response.status_code} {response.text}"
            )
        logger.info("Sent %s to Teams webhook", ctx.card_name)

    def teardown(self) -> None:
        if self.payload_format != "message_card":
            self._pending = []
            return
        if not self._pending:
            return
        if self._is_dry_run():
            self._log_dry_run_send(
                kind="message_card",
                target="webhook",
                detail=f"{len(self._pending)} card(s)",
            )
            self._pending = []
            return
        if not self._webhook_url:
            self.prepare()
        assert self._webhook_url

        payload = self._build_message_card_payload(self._pending)
        response = requests.post(self._webhook_url, json=payload, timeout=30)
        if response.status_code >= 400:
            raise TeamsDestinationError(
                f"Teams MessageCard POST failed: " f"{response.status_code} {response.text}"
            )
        logger.info(
            "Posted Teams MessageCard with %d section(s)",
            len(self._pending),
        )
        self._pending = []

    # ---- payload builders ----

    def _build_adaptive_payload(self, ctx: DestinationContext) -> dict[str, Any]:
        with open(ctx.image_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        caption = (
            render_safe(self.caption_template, card_context(ctx), fallback="")
            if self.caption_template
            else ""
        )
        adaptive_body: list[dict[str, Any]] = [
            {"type": "TextBlock", "text": ctx.card_name, "weight": "Bolder", "size": "Medium"},
        ]
        if caption:
            adaptive_body.append(
                {"type": "TextBlock", "text": caption, "wrap": True, "spacing": "Small"}
            )
        adaptive_body.append({"type": "Image", "url": f"data:image/png;base64,{b64}"})
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "type": "AdaptiveCard",
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "version": "1.4",
                        "body": adaptive_body,
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "Open in Domo",
                                "url": ctx.card_url,
                            },
                        ],
                    },
                }
            ],
        }

    def _build_message_card_payload(
        self,
        pending: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Return a legacy Office 365 ``MessageCard`` payload.

        Each buffered card becomes one ``section`` with an activity
        title, image, and optional fact table.
        """

        title = self.title or f"Domo report -- {len(pending)} card(s)"
        summary_text = self._render_summary(pending) or title

        sections: list[dict[str, Any]] = []
        for entry in pending:
            ctx: DestinationContext = entry["ctx"]
            caption = (
                render_safe(self.caption_template, card_context(ctx), fallback="")
                if self.caption_template
                else ""
            )
            section: dict[str, Any] = {
                "activityTitle": f"**{ctx.card_name}**",
                "activitySubtitle": ctx.page_name or "",
                "text": caption or "",
                "images": [
                    {
                        "image": f"data:image/png;base64,{entry['b64']}",
                        "title": ctx.card_name,
                    }
                ],
                "potentialAction": [
                    {
                        "@type": "OpenUri",
                        "name": "Open in Domo",
                        "targets": [{"os": "default", "uri": ctx.card_url}],
                    }
                ],
            }
            if self.facts:
                section["facts"] = [
                    {"name": str(f.get("name", "")), "value": str(f.get("value", ""))}
                    for f in self.facts
                ]
            sections.append(section)

        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": summary_text,
            "themeColor": "0078D4",
            "title": title,
            "sections": sections,
        }

    def _render_summary(self, pending: list[dict[str, Any]]) -> str:
        if not self.summary_template:
            return ""
        context = {
            "count": len(pending),
            "cards": [
                {
                    "name": p["ctx"].card_name,
                    "url": p["ctx"].card_url,
                    "page_name": p["ctx"].page_name,
                }
                for p in pending
            ],
        }
        context.update(_today_ctx())
        return render_safe(self.summary_template, context, fallback="")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _escape(value: str) -> str:
    """Tiny HTML escaper for safe insertion into Teams chat-message content."""

    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _attachment_id_from_etag(etag: str) -> str:
    """Derive the Graph chatMessage attachment ID from the uploaded file's eTag."""

    return etag.strip('"').split(",")[0]


def _message_attachment(attachment_id: str, uploaded: dict[str, Any]) -> dict[str, Any]:
    """Return a reference-type attachment object for a chatMessage payload."""

    return {
        "id": attachment_id,
        "contentType": "reference",
        "contentUrl": uploaded.get("webUrl"),
        "name": uploaded.get("name"),
    }


def _today_ctx() -> dict[str, Any]:
    import datetime

    now = datetime.datetime.now()
    return {
        "today": now.date().isoformat(),
        "now": now.isoformat(timespec="seconds"),
    }
