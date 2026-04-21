"""Abstract base class for everything that talks to Domo.

Two implementations ship today (REST + JAR), and you can register more via
:func:`app.engines.registry.register_engine`. Anything that needs to fetch
metadata or render a card image goes through this interface so the rest of
the codebase never imports ``requests`` or ``subprocess`` directly.
"""

from __future__ import annotations

import shlex
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


class DomoEngineError(RuntimeError):
    """Raised when a Domo engine call fails or is misconfigured."""


@dataclass(frozen=True)
class CardImageRequest:
    """Single card-image generation request.

    The JAR engine concatenates these into one stdin script so it pays the
    JVM cold-start cost only once. The REST engine iterates them with
    pooled HTTP connections.
    """

    card_id: int
    output_path: str

    def to_jar_command(self) -> str:
        """Render the JAR-CLI line for this request."""

        return f"generate-card-image -i {self.card_id} -f {shlex.quote(self.output_path)}\n"


@dataclass
class CardSummary:
    """Lightweight card descriptor used for auto-discovery (Wave 6).

    Only the fields all engines can populate cheaply. The web UI / alert
    runner can fetch richer data via :meth:`DomoEngine.get_card_metadata`
    when needed.
    """

    card_id: int
    card_name: str
    page_id: str | None = None
    page_name: str | None = None
    card_url: str | None = None
    tags: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)


class DomoEngine(ABC):
    """Interface implemented by every Domo engine.

    Concrete subclasses must override :meth:`export_dataset` and
    :meth:`generate_card_image`. The other methods have sensible defaults
    or raise :class:`NotImplementedError` (engines that don't support a
    feature should let the registry/runtime handle the fallback).
    """

    #: Short identifier the registry uses (``rest``, ``jar``, ...).
    key: str = ""

    #: Human-friendly label for log lines.
    label: str = ""

    # ---- required ----

    @abstractmethod
    def export_dataset(self, dataset_id: str, output_path: str) -> None:
        """Stream the rows of ``dataset_id`` into a CSV at ``output_path``."""

    @abstractmethod
    def generate_card_image(
        self,
        card_id: int,
        output_path: str,
        **opts: Any,
    ) -> None:
        """Render a single card to a PNG at ``output_path``."""

    # ---- batched (optional override) ----

    def generate_card_images(self, requests: Sequence[CardImageRequest]) -> None:
        """Render many cards. Default falls back to a Python-side loop.

        Engines (like JAR) that can do this in a single transaction should
        override for the perf win.
        """

        for req in requests:
            self.generate_card_image(req.card_id, req.output_path)

    # ---- discovery / introspection (optional) ----

    def list_cards(
        self,
        page: str | None = None,
        tags: Sequence[str] | None = None,
        exclude_tags: Sequence[str] | None = None,
    ) -> list[CardSummary]:
        """Return cards matching the filter. Engines that can't list cards
        should raise :class:`NotImplementedError` so the caller can decide
        whether to error or fall back to a metadata-CSV scan.
        """

        raise NotImplementedError(f"{self.label or self.key} cannot list cards")

    def get_card_metadata(self, card_id: int) -> dict[str, Any]:
        """Return arbitrary metadata for a single card."""

        raise NotImplementedError(f"{self.label or self.key} cannot fetch single-card metadata")

    # ---- health (optional) ----

    def health_check(self) -> tuple[bool, str]:
        """Return ``(ok, message)``. Default: assume healthy if config loads."""

        try:
            self._self_test()
            return True, f"{self.label or self.key} configured"
        except Exception as exc:
            return False, f"{self.label or self.key}: {exc}"

    def _self_test(self) -> None:
        """Hook for :meth:`health_check`. Subclasses should ping the API."""

        return None

    # ---- meta ----

    def describe(self) -> str:
        return self.label or self.key or self.__class__.__name__
