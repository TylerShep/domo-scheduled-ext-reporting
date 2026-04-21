"""SMTP email destination.

Buffers every image and dataset that the run produces, then assembles a
single multipart MIME email at ``teardown`` time. Images are inlined via
``Content-ID`` references so modern clients render them in the body, and
datasets are attached with their real filename.

YAML example::

    destinations:
      - type: email
        to_addrs: ["leadership@company.com"]
        cc_addrs: ["ops@company.com"]
        subject_template: "Daily KPIs - {{ today }}"
        body_template: |
          ## Daily KPIs for {{ today }}
          {% for card in cards %}
          * **{{ card.name }}** -- <https://domo.com/{{ card.id }}>
          {% endfor %}
        attach_as: inline          # inline | attachment
        attach_datasets: true      # include any ``type: file`` datasets

Env vars read:
    * ``SMTP_HOST`` (default: smtp.gmail.com)
    * ``SMTP_PORT`` (default: 587)
    * ``SMTP_USER``
    * ``SMTP_PASSWORD``
    * ``SMTP_USE_TLS`` (default: ``true``)
    * ``SMTP_FROM_ADDR`` (required if not overridden per-destination)

Per-destination overrides (kwargs) take priority over env vars.
"""

from __future__ import annotations

import datetime
import smtplib
from collections.abc import Sequence
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

from app.configuration.settings import get_env
from app.destinations.base import (
    DatasetContext,
    Destination,
    DestinationContext,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


_DEFAULT_SUBJECT = "Domo report -- {{ today }}"
_DEFAULT_BODY = """{% for card in cards %}
## {{ card.name }}
{{ card.cid_html|safe }}

{% endfor %}
"""

_ALLOWED_ATTACH_AS = {"inline", "attachment"}


class EmailDestinationError(RuntimeError):
    """Raised on SMTP failures or bad configuration."""


class EmailDestination(Destination):
    """Buffers everything in a run and sends one email at the end."""

    key = "email"
    label = "Email"

    def __init__(
        self,
        to_addrs: Sequence[str],
        from_addr: str | None = None,
        cc_addrs: Sequence[str] | None = None,
        subject_template: str = _DEFAULT_SUBJECT,
        body_template: str = _DEFAULT_BODY,
        attach_as: str = "inline",
        attach_datasets: bool = True,
        smtp_host_env: str | None = None,
        smtp_user_env: str | None = None,
        smtp_password_env: str | None = None,
        smtp_port: int | None = None,
        use_tls: bool | None = None,
        **kwargs: Any,
    ) -> None:
        if not to_addrs:
            raise EmailDestinationError("Email destination requires to_addrs")
        attach_as_norm = str(attach_as).lower()
        if attach_as_norm not in _ALLOWED_ATTACH_AS:
            raise EmailDestinationError(f"attach_as must be one of {sorted(_ALLOWED_ATTACH_AS)}")
        super().__init__(
            to_addrs=list(to_addrs),
            from_addr=from_addr,
            cc_addrs=list(cc_addrs or []),
            subject_template=subject_template,
            body_template=body_template,
            attach_as=attach_as_norm,
            attach_datasets=attach_datasets,
            **kwargs,
        )
        self.to_addrs = list(to_addrs)
        self.cc_addrs = list(cc_addrs or [])
        self.from_addr = from_addr
        self.subject_template = subject_template
        self.body_template = body_template
        self.attach_as = attach_as_norm
        self.attach_datasets = bool(attach_datasets)
        self._smtp_host_env = smtp_host_env or "SMTP_HOST"
        self._smtp_user_env = smtp_user_env or "SMTP_USER"
        self._smtp_password_env = smtp_password_env or "SMTP_PASSWORD"
        self._smtp_port_override = smtp_port
        self._use_tls_override = use_tls

        self._pending_cards: list[dict[str, Any]] = []
        self._pending_datasets: list[dict[str, Any]] = []

    # ---- lifecycle ----

    def prepare(self) -> None:
        # Reset buffers for idempotency.
        self._pending_cards = []
        self._pending_datasets = []

    def teardown(self) -> None:
        if not self._pending_cards and not self._pending_datasets:
            logger.info("Email destination had nothing to send; skipping.")
            return
        if self._is_dry_run():
            self._log_dry_run_send(
                kind="email",
                target=", ".join(self.to_addrs),
                detail=(
                    f"{len(self._pending_cards)} card(s), "
                    f"{len(self._pending_datasets)} dataset(s)"
                ),
            )
            self._pending_cards = []
            self._pending_datasets = []
            return
        message = self._build_message()
        self._send(message)
        self._pending_cards = []
        self._pending_datasets = []

    # ---- buffer ----

    def send_image(self, ctx: DestinationContext) -> None:
        cid = make_msgid(domain="domo-reports.local")
        self._pending_cards.append(
            {
                "name": ctx.card_name,
                "url": ctx.card_url,
                "page": ctx.page_name,
                "path": ctx.image_path,
                "cid": cid,
            }
        )

    def send_dataset(self, ctx: DatasetContext) -> None:
        if not self.attach_datasets:
            return
        self._pending_datasets.append(
            {
                "name": ctx.dataset_name,
                "path": ctx.file_path,
                "format": ctx.file_format,
            }
        )

    # ---- internals ----

    def _build_message(self) -> EmailMessage:
        subject = self._render(self.subject_template, context=self._template_context())
        html_body, markdown_body = self._render_bodies()

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._resolve_from_addr()
        msg["To"] = ", ".join(self.to_addrs)
        if self.cc_addrs:
            msg["Cc"] = ", ".join(self.cc_addrs)

        msg.set_content(markdown_body)
        msg.add_alternative(html_body, subtype="html")
        self._attach_images(msg)
        self._attach_datasets_to(msg)
        return msg

    def _send(self, msg: EmailMessage) -> None:
        host = get_env(self._smtp_host_env, default="smtp.gmail.com")
        port = int(
            self._smtp_port_override
            if self._smtp_port_override is not None
            else get_env("SMTP_PORT", default="587")
        )
        user = get_env(self._smtp_user_env)
        password = get_env(self._smtp_password_env)
        use_tls = (
            self._use_tls_override
            if self._use_tls_override is not None
            else _coerce_bool(get_env("SMTP_USE_TLS", default="true"))
        )

        try:
            with smtplib.SMTP(host, port, timeout=60) as smtp:
                if use_tls:
                    smtp.starttls()
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(msg)
                logger.info(
                    "Email sent via %s:%s to %d recipient(s)",
                    host,
                    port,
                    len(self.to_addrs) + len(self.cc_addrs),
                )
        except smtplib.SMTPException as exc:
            raise EmailDestinationError(f"SMTP send failed: {exc}") from exc

    def _resolve_from_addr(self) -> str:
        if self.from_addr:
            return self.from_addr
        env_value = get_env("SMTP_FROM_ADDR")
        if env_value:
            return env_value
        user = get_env(self._smtp_user_env)
        if user:
            return user
        raise EmailDestinationError(
            "No `from_addr` configured and SMTP_FROM_ADDR / SMTP_USER env vars are empty."
        )

    def _template_context(self) -> dict[str, Any]:
        now = datetime.datetime.now()
        # HTML bits for inline-image Content-ID references.
        for card in self._pending_cards:
            cid = card["cid"].strip("<>")
            card["cid_html"] = (
                f'<p><strong>{_escape(card["name"])}</strong></p>'
                f'<p><a href="{_escape(card["url"])}">Open card in Domo</a></p>'
                f'<img src="cid:{cid}" alt="{_escape(card["name"])}" />'
            )
        return {
            "today": now.date().isoformat(),
            "now": now.isoformat(timespec="seconds"),
            "cards": self._pending_cards,
            "datasets": self._pending_datasets,
        }

    def _render_bodies(self) -> tuple[str, str]:
        """Return ``(html, markdown_fallback)``.

        The plaintext alternative is the raw (non-Jinja) markdown so mail
        clients that can't render HTML still get a readable message.
        """

        context = self._template_context()
        markdown_source = self._render(self.body_template, context)
        try:
            import markdown as _md

            html = _md.markdown(
                markdown_source,
                extensions=["extra", "sane_lists"],
                output_format="html",
            )
        except ImportError:
            # The `markdown` package is a core dep; this is a belt-and-braces
            # fallback that just wraps the rendered Jinja output in a <pre>.
            html = f"<pre>{_escape(markdown_source)}</pre>"
        return html, markdown_source

    def _render(self, template: str, context: dict[str, Any]) -> str:
        try:
            from app.templating import TemplateError, render
        except ImportError as exc:  # pragma: no cover - belt-and-braces
            raise EmailDestinationError(
                "Email destination requires jinja2 (install via pyproject core deps)"
            ) from exc
        try:
            return render(template, context)
        except TemplateError as exc:
            raise EmailDestinationError(str(exc)) from exc

    def _attach_images(self, msg: EmailMessage) -> None:
        if not self._pending_cards:
            return
        for card in self._pending_cards:
            path = Path(card["path"])
            if not path.exists():
                logger.warning("Skipping missing image %s", path)
                continue
            with path.open("rb") as fh:
                data = fh.read()
            disposition = "inline" if self.attach_as == "inline" else "attachment"
            msg.get_payload()[1].add_related(
                data,
                maintype="image",
                subtype="png",
                cid=card["cid"],
                disposition=disposition,
                filename=path.name,
            )

    def _attach_datasets_to(self, msg: EmailMessage) -> None:
        for ds in self._pending_datasets:
            path = Path(ds["path"])
            if not path.exists():
                logger.warning("Skipping missing dataset %s", path)
                continue
            maintype, subtype = (
                ("text", "csv")
                if ds["format"] == "csv"
                else (
                    "application",
                    "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            )
            with path.open("rb") as fh:
                data = fh.read()
            msg.add_attachment(
                data,
                maintype=maintype,
                subtype=subtype,
                filename=path.name,
            )


def _coerce_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
