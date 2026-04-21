"""Abstract base class every report subclasses (directly or via YAML).

Lifecycle of ``execute_service``:
    1. Build a list of :class:`Destination` instances.
    2. Export the metadata dataset to a temp CSV.
    3. Resolve every card's ID/URL via the metadata CSV.
    4. Batch-generate every card image in a single JVM session.
    5. Edit each image (crop/resize/caption).
    6. Fan the image out to every destination.
    7. Wipe the scratch folders.

This generalizes the original ``DomoSlackBase`` (single-destination,
per-card JVM start) to N destinations and one JVM start per report.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Sequence

import app.utils.domo_util as domo_service
import app.utils.image_util as image_service
import app.utils.project_setup_util as setup_service
from app.destinations.base import Destination, DestinationContext
from app.destinations.registry import build_destination
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DomoBase(ABC):
    """Base class for every report. Subclass and implement the abstract methods.

    Attributes:
        name: Human-friendly report name (used in logs and the registry key).
    """

    name: str = ""

    # ---- subclass contract ----

    @abstractmethod
    def file_name(self) -> str:
        """Return the metadata-CSV stem (no extension) for this report."""

    @abstractmethod
    def list_of_cards(self) -> Sequence[Sequence[Any]]:
        """Return ``[[dashboard, card, viz_type, *optional_overrides], ...]``.

        For backward compatibility a 3-element list works exactly like the
        original. Optional 4th element may be a dict of per-card overrides:
        ``{"crop": [l, u, r, b], "resize": [w, h], "add_caption": True}``.
        """

    def list_of_destinations(self) -> Sequence[dict]:
        """Return YAML-style destination specs for this report.

        Subclasses that override this can fan out to multiple destinations.
        The default is empty -- override either this or
        :meth:`build_destinations`.
        """

        return []

    def build_destinations(self) -> list[Destination]:
        """Build :class:`Destination` instances. Override for full control."""

        return [build_destination(spec) for spec in self.list_of_destinations()]

    # ---- runtime ----

    def execute_service(self) -> None:
        report_name = self.name or self.__class__.__name__
        logger.info("=== Running report: %s ===", report_name)

        destinations = self.build_destinations()
        if not destinations:
            logger.warning("Report %s has no destinations; nothing to send.", report_name)
            return

        for destination in destinations:
            destination.prepare()

        cards = list(self.list_of_cards())
        if not cards:
            logger.warning("Report %s has no cards configured; nothing to do.", report_name)
            return

        try:
            metadata_path = self._export_metadata()
            resolved = self._resolve_cards(cards, metadata_path)
            self._generate_images(resolved)
            self._dispatch(resolved, destinations)
        finally:
            for destination in destinations:
                try:
                    destination.teardown()
                except Exception:
                    logger.exception("Destination teardown failed for %s", destination.describe())
            setup_service.remove_temp_folders()

    # ---- internal helpers ----

    def _export_metadata(self) -> str:
        setup_service.create_temp_folder("cards_metadata")
        jar_path = setup_service.get_domo_util_path()
        output_path, _ = setup_service.get_output_file_path(self.file_name(), ".csv")
        domo_service.exec_domo_export_dataset(jar_path, output_path)
        return output_path

    def _resolve_cards(
        self,
        cards: list[Sequence[Any]],
        metadata_path: str,
    ) -> list[dict[str, Any]]:
        """Look up each card's ID/URL/page_name and pre-compute its output path."""

        setup_service.create_temp_folder("temp_files")
        resolved: list[dict[str, Any]] = []

        for card in cards:
            try:
                card_id, card_url, page_name = domo_service.query_card_metadata(
                    card, metadata_path
                )
            except Exception as exc:
                logger.error(
                    "Skipping card %s: metadata lookup failed (%s)",
                    list(card),
                    exc,
                )
                continue

            card_name = card[1]
            viz_type = card[2] if len(card) > 2 else ""
            overrides = card[3] if len(card) > 3 and isinstance(card[3], dict) else {}

            cleaned_name = setup_service.clean_filename(str(card_name))
            output_path, _ = setup_service.get_output_file_path(cleaned_name, ".png")

            resolved.append(
                {
                    "card_id": card_id,
                    "card_url": card_url,
                    "page_name": page_name,
                    "card_name": card_name,
                    "viz_type": viz_type,
                    "image_path": output_path,
                    "overrides": overrides,
                }
            )

        return resolved

    def _generate_images(self, resolved: list[dict[str, Any]]) -> None:
        """One JVM start, N card-image generations."""

        if not resolved:
            return
        jar_path = setup_service.get_domo_util_path()
        requests = [
            domo_service.CardImageRequest(card_id=item["card_id"], output_path=item["image_path"])
            for item in resolved
        ]
        domo_service.exec_domo_generate_images(jar_path, requests)

    def _dispatch(
        self,
        resolved: list[dict[str, Any]],
        destinations: list[Destination],
    ) -> None:
        """Edit each image and send it to every destination."""

        for item in resolved:
            try:
                image_service.edit_card_images(
                    image_path=item["image_path"],
                    card_viz_type=item["viz_type"],
                    crop_override=item["overrides"].get("crop"),
                    resize_override=item["overrides"].get("resize"),
                    add_caption=bool(item["overrides"].get("add_caption", False)),
                    caption_text=item["overrides"].get("caption_text") or item["card_name"],
                )
            except Exception:
                logger.exception("Image edit failed for %s; sending original.", item["card_name"])

            ctx = DestinationContext(
                image_path=item["image_path"],
                card_name=str(item["card_name"]),
                card_url=str(item["card_url"]),
                page_name=str(item["page_name"]),
            )
            for destination in destinations:
                try:
                    destination.send_image(ctx)
                except Exception:
                    logger.exception(
                        "Failed to send %s to %s",
                        item["card_name"],
                        destination.describe(),
                    )
