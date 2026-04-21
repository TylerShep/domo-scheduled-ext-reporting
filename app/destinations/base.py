"""Pluggable destination interface.

A *destination* is anywhere a generated card image or dataset file can be
sent: a Slack channel, a Microsoft Teams channel via Graph API, a Teams
webhook, an SMTP mailbox, etc.

To add a new destination:
    1. Subclass :class:`Destination` and implement :meth:`send_image`
       (and optionally :meth:`send_dataset` if you want to deliver raw data).
    2. Register it in ``app/destinations/registry.py``.
    3. Reference it from a YAML report by ``type: <your_key>``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.runtime import is_dry_run
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DestinationContext:
    """Information passed to :meth:`Destination.send_image` per card."""

    image_path: str
    card_name: str
    card_url: str
    page_name: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetContext:
    """Information passed to :meth:`Destination.send_dataset` per dataset."""

    file_path: str
    dataset_name: str
    dataset_id: str
    file_format: str = "csv"  # csv | xlsx
    extra: dict[str, Any] = field(default_factory=dict)


class Destination(ABC):
    """Base class every destination implementation inherits from."""

    #: Unique key used in YAML ``type:`` and the destination registry.
    key: str = ""

    #: Human-friendly label that appears in logs.
    label: str = ""

    def __init__(
        self,
        *,
        dry_run: bool = False,
        send_when: str | None = None,
        **config: Any,
    ) -> None:
        self.config = config
        #: Per-instance dry-run flag. If True (or the global dry-run flag
        #: is True), ``send_image`` / ``send_dataset`` short-circuit.
        self.dry_run = bool(dry_run)
        #: Optional ``send_when:`` expression evaluated by
        #: :mod:`app.alerts` before each delivery. None means "always send".
        self.send_when: str | None = send_when if send_when else None

    @abstractmethod
    def send_image(self, ctx: DestinationContext) -> None:
        """Send a single card image. Implementations should raise on failure."""

    def send_dataset(self, ctx: DatasetContext) -> None:
        """Send a single dataset file (CSV / XLSX).

        Default raises so destinations that don't support data delivery
        fail loudly; the :class:`~app.destinations.file.FileDestination`
        wrapper routes around this when needed.
        """

        raise NotImplementedError(f"Destination {self.describe()} does not support send_dataset()")

    def prepare(self) -> None:
        """Optional one-time setup before the first :meth:`send_image` call.

        Useful for resolving channel IDs / acquiring auth tokens. Default is
        a no-op.
        """

    def teardown(self) -> None:
        """Optional cleanup after all sends complete. Default is a no-op."""

    def describe(self) -> str:
        """Short string describing this destination for log lines."""

        return f"{self.label or self.key}({self.config})"

    # ---- dry-run plumbing ----

    def _is_dry_run(self) -> bool:
        """True if either the global or per-destination dry-run flag is on."""

        return is_dry_run(self.dry_run)

    def _log_dry_run_send(self, kind: str, target: str, detail: str = "") -> None:
        """Emit a standardized `[dry-run]` log line.

        Destinations call this from their ``send_image`` / ``send_dataset``
        when dry-run is active so humans can see exactly what *would* have
        happened.
        """

        suffix = f" -- {detail}" if detail else ""
        logger.info(
            "[dry-run] %s -> %s: %s%s",
            self.describe(),
            target,
            kind,
            suffix,
        )
