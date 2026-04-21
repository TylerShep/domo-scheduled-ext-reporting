"""Abstract base class every report subclasses (directly or via YAML).

Lifecycle of ``execute_service``:
    1. Open a :func:`app.history.record` context.
    2. Build a list of :class:`Destination` instances.
    3. Pick the active :class:`~app.engines.base.DomoEngine` (REST or JAR).
    4. Export the metadata dataset to a temp CSV.
    5. Resolve every card's ID/URL via the metadata CSV.
    6. Generate every card image (batched on engines that support it).
    7. Edit each image (crop/resize/caption).
    8. Fan the image out to every destination.
    9. Wipe the scratch folders.

Throughout 4-8 we record :class:`CardOutcome` and
:class:`DestinationOutcome` rows on the active :class:`RunRecord` so the
web UI / alerts have something to read.
"""

from __future__ import annotations

import shutil
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import app.utils.image_util as image_service
import app.utils.project_setup_util as setup_service
from app.alerts import build_card_context, build_dataset_context, should_send
from app.configuration.settings import get_env
from app.destinations.base import DatasetContext, Destination, DestinationContext
from app.destinations.registry import build_destination
from app.engines import CardImageRequest, DomoEngine, get_engine
from app.history import (
    CardOutcome,
    DestinationOutcome,
    RunStatus,
    record,
)
from app.observability import (
    observe_card_send,
    observe_run_duration,
    record_run_status,
)
from app.runtime import get_flags, preview_dir
from app.utils.domo_util import query_card_metadata
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

    def list_of_datasets(self) -> Sequence[dict]:
        """Return raw-dataset delivery specs.

        Each entry is ``{"name", "dataset_id", "format"}`` where
        ``format`` is ``csv`` (default) or ``xlsx``. Datasets are
        exported via the active engine and then fanned out to every
        ``type: file`` destination on this report.
        """

        return []

    def build_destinations(self) -> list[Destination]:
        """Build :class:`Destination` instances. Override for full control."""

        return [build_destination(spec) for spec in self.list_of_destinations()]

    # ---- engine ----

    def get_engine(self) -> DomoEngine:
        """Return the active engine. Override to inject in tests."""

        return get_engine()

    # ---- runtime ----

    def execute_service(self) -> None:
        report_name = self.name or self.__class__.__name__
        logger.info("=== Running report: %s ===", report_name)

        started = time.monotonic()
        try:
            with record(report_name) as run:
                destinations = self.build_destinations()
                if not destinations:
                    logger.warning("Report %s has no destinations; nothing to send.", report_name)
                    run.mark_finished(RunStatus.SKIPPED)
                    return

                for destination in destinations:
                    destination.prepare()
                    run.destinations.append(
                        DestinationOutcome(
                            destination_label=destination.describe(),
                            destination_type=destination.key or "unknown",
                        )
                    )

                cards = list(self.list_of_cards())
                datasets = list(self.list_of_datasets())
                if not cards and not datasets:
                    logger.warning(
                        "Report %s has no cards or datasets configured; nothing to do.",
                        report_name,
                    )
                    run.mark_finished(RunStatus.SKIPPED)
                    return

                engine = self.get_engine()

                try:
                    if cards:
                        metadata_path = self._export_metadata(engine)
                        resolved = self._resolve_cards(cards, metadata_path, run)
                        self._generate_images(engine, resolved)
                        self._dispatch(resolved, destinations, run)
                    if datasets:
                        self._dispatch_datasets(engine, datasets, destinations, run)
                finally:
                    for destination in destinations:
                        try:
                            destination.teardown()
                        except Exception:
                            logger.exception(
                                "Destination teardown failed for %s",
                                destination.describe(),
                            )
                    setup_service.remove_temp_folders()
        finally:
            duration = time.monotonic() - started
            observe_run_duration(report_name, duration)
            # ``record`` set the final status by the time we get here.
            record_run_status(report_name, _final_status_label(report_name))

    # ---- internal helpers ----

    def _export_metadata(self, engine: DomoEngine) -> str:
        setup_service.create_temp_folder("cards_metadata")
        output_path, _ = setup_service.get_output_file_path(self.file_name(), ".csv")
        dataset_id = get_env("DOMO_CARDS_META_DATASET_ID", required=True)
        engine.export_dataset(dataset_id, output_path)
        return output_path

    def _resolve_cards(
        self,
        cards: list[Sequence[Any]],
        metadata_path: str,
        run: Any = None,
    ) -> list[dict[str, Any]]:
        """Look up each card's ID/URL/page_name and pre-compute its output path."""

        setup_service.create_temp_folder("temp_files")
        resolved: list[dict[str, Any]] = []

        for card in cards:
            try:
                card_id, card_url, page_name = query_card_metadata(card, metadata_path)
            except Exception as exc:
                logger.error(
                    "Skipping card %s: metadata lookup failed (%s)",
                    list(card),
                    exc,
                )
                if run is not None:
                    run.cards.append(
                        CardOutcome(
                            card_name=str(card[1]) if len(card) > 1 else "?",
                            sent=False,
                            error=str(exc)[:500],
                        )
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

    def _generate_images(
        self,
        engine: DomoEngine,
        resolved: list[dict[str, Any]],
    ) -> None:
        """Generate every card image via the active engine."""

        if not resolved:
            return
        requests = [
            CardImageRequest(card_id=item["card_id"], output_path=item["image_path"])
            for item in resolved
        ]
        logger.info(
            "Generating %d card image(s) via %s.",
            len(requests),
            engine.describe(),
        )
        engine.generate_card_images(requests)

    def _dispatch(
        self,
        resolved: list[dict[str, Any]],
        destinations: list[Destination],
        run: Any = None,
    ) -> None:
        """Edit each image and send it to every destination."""

        # Index destinations by label so we can update outcomes in place.
        outcome_by_label: dict[str, DestinationOutcome] = {}
        if run is not None:
            outcome_by_label = {d.destination_label: d for d in run.destinations}

        report_name = self.name or self.__class__.__name__
        for item in resolved:
            overrides = item.get("overrides") or {}
            card_send_when = overrides.get("send_when")
            card_context = build_card_context(item, run)

            if not should_send(card_send_when, card_context):
                logger.info(
                    "Skipping card %s -- send_when evaluated false: %s",
                    item["card_name"],
                    card_send_when,
                )
                if run is not None:
                    run.cards.append(
                        CardOutcome(
                            card_name=str(item["card_name"]),
                            card_id=item.get("card_id"),
                            page_name=str(item.get("page_name") or ""),
                            image_path=str(item.get("image_path") or ""),
                            sent=False,
                            skipped=True,
                            skip_reason=f"send_when: {card_send_when}",
                        )
                    )
                continue

            try:
                caption_text = _resolve_caption(item, report_name)
                image_service.edit_card_images(
                    image_path=item["image_path"],
                    card_viz_type=item["viz_type"],
                    crop_override=overrides.get("crop"),
                    resize_override=overrides.get("resize"),
                    add_caption=bool(overrides.get("add_caption", False)),
                    caption_text=caption_text,
                )
            except Exception:
                logger.exception("Image edit failed for %s; sending original.", item["card_name"])

            _maybe_copy_to_preview(
                image_path=item["image_path"],
                report_name=report_name,
                card_name=str(item["card_name"]),
            )

            ctx = DestinationContext(
                image_path=item["image_path"],
                card_name=str(item["card_name"]),
                card_url=str(item["card_url"]),
                page_name=str(item["page_name"]),
            )

            card_outcome = CardOutcome(
                card_name=str(item["card_name"]),
                card_id=item.get("card_id"),
                page_name=str(item.get("page_name") or ""),
                image_path=str(item.get("image_path") or ""),
                sent=False,
            )

            sent_to_at_least_one = False
            for destination in destinations:
                outcome = outcome_by_label.get(destination.describe())

                dest_send_when = getattr(destination, "send_when", None)
                if dest_send_when and not should_send(dest_send_when, card_context):
                    logger.info(
                        "Skipping %s -> %s (destination send_when false: %s)",
                        item["card_name"],
                        destination.describe(),
                        dest_send_when,
                    )
                    if outcome is not None:
                        outcome.cards_skipped += 1
                    continue

                if outcome is not None:
                    outcome.cards_attempted += 1
                try:
                    destination.send_image(ctx)
                    sent_to_at_least_one = True
                    if outcome is not None:
                        outcome.cards_sent += 1
                    observe_card_send(destination.key or "unknown", success=True)
                except Exception as exc:
                    logger.exception(
                        "Failed to send %s to %s",
                        item["card_name"],
                        destination.describe(),
                    )
                    if outcome is not None and outcome.error is None:
                        outcome.error = str(exc)[:500]
                    observe_card_send(destination.key or "unknown", success=False)
                    card_outcome.error = str(exc)[:500]

            card_outcome.sent = sent_to_at_least_one
            if run is not None:
                run.cards.append(card_outcome)

    def _dispatch_datasets(
        self,
        engine: DomoEngine,
        datasets: list[dict[str, Any]],
        destinations: list[Destination],
        run: Any = None,
    ) -> None:
        """Export each dataset to CSV and send to every file destination.

        Non-file destinations are silently skipped -- raw data delivery is
        an opt-in feature, not a default fanout.
        """

        file_destinations = [d for d in destinations if d.key == "file"]
        if not file_destinations:
            logger.info(
                "Report has %d dataset(s) but no file destinations; skipping.",
                len(datasets),
            )
            return

        outcome_by_label: dict[str, DestinationOutcome] = {}
        if run is not None:
            outcome_by_label = {d.destination_label: d for d in run.destinations}

        setup_service.create_temp_folder("cards_metadata")
        for ds in datasets:
            ds_name = str(ds.get("name") or ds.get("dataset_id"))
            ds_id = str(ds["dataset_id"])
            fmt = str(ds.get("format", "csv")).lower()
            output_path, _ = setup_service.get_output_file_path(
                setup_service.clean_filename(ds_name), ".csv"
            )
            try:
                engine.export_dataset(ds_id, output_path)
            except Exception as exc:
                logger.exception("Failed to export dataset %s", ds_name)
                if run is not None:
                    run.extras.setdefault("dataset_errors", []).append(
                        {"name": ds_name, "error": str(exc)[:500]}
                    )
                continue

            ds_context = build_dataset_context(ds, output_path, run)
            ds_send_when = ds.get("send_when")
            if not should_send(ds_send_when, ds_context):
                logger.info(
                    "Skipping dataset %s -- send_when evaluated false: %s",
                    ds_name,
                    ds_send_when,
                )
                continue

            ctx = DatasetContext(
                file_path=output_path,
                dataset_name=ds_name,
                dataset_id=ds_id,
                file_format=fmt,
            )
            for destination in file_destinations:
                outcome = outcome_by_label.get(destination.describe())

                dest_send_when = getattr(destination, "send_when", None)
                if dest_send_when and not should_send(dest_send_when, ds_context):
                    logger.info(
                        "Skipping dataset %s -> %s (destination send_when false)",
                        ds_name,
                        destination.describe(),
                    )
                    if outcome is not None:
                        outcome.cards_skipped += 1
                    continue

                if outcome is not None:
                    outcome.cards_attempted += 1
                try:
                    destination.send_dataset(ctx)
                    if outcome is not None:
                        outcome.cards_sent += 1
                except Exception as exc:
                    logger.exception(
                        "Failed to send dataset %s to %s",
                        ds_name,
                        destination.describe(),
                    )
                    if outcome is not None and outcome.error is None:
                        outcome.error = str(exc)[:500]


def _resolve_caption(item: dict[str, Any], report_name: str) -> str:
    """Render the caption template (if any) or fall back to static text."""

    import datetime

    overrides = item.get("overrides") or {}
    raw = overrides.get("caption_text")
    default = str(item["card_name"])
    if not raw:
        return default
    if "{{" not in str(raw) and "{%" not in str(raw):
        # No Jinja syntax; treat as a static string.
        return str(raw)
    from app.templating import render_safe

    now = datetime.datetime.now()
    context = {
        "today": now.date().isoformat(),
        "now": now.isoformat(timespec="seconds"),
        "card": {
            "name": item["card_name"],
            "url": item.get("card_url"),
            "page_name": item.get("page_name"),
        },
        "card_name": item["card_name"],
        "card_url": item.get("card_url"),
        "page_name": item.get("page_name"),
        "report_name": report_name,
    }
    return render_safe(str(raw), context, fallback=default)


def _maybe_copy_to_preview(image_path: str, report_name: str, card_name: str) -> None:
    """Copy an edited card image into the preview folder if --preview is on.

    We swallow any failures here -- previews are a debug convenience and
    must never mask a real delivery error.
    """

    flags = get_flags()
    if not flags.preview:
        return
    try:
        source = Path(image_path)
        if not source.exists():
            return
        target_dir = Path(preview_dir()) / setup_service.clean_filename(report_name)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{setup_service.clean_filename(card_name)}{source.suffix}"
        shutil.copy2(source, target_path)
        logger.info("[preview] Saved %s -> %s", card_name, target_path)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Preview copy failed for %s", card_name)


def _final_status_label(report_name: str) -> str:
    """Best-effort label lookup for the metrics counter.

    The :func:`record` context already wrote the final status to the
    history backend by the time we reach the ``finally`` clause; we just
    pull the most recent status label out for the Prometheus counter.
    """

    try:
        from app.history import get_backend

        backend = get_backend()
        runs = backend.get_runs(report_name=report_name, limit=1)
        return runs[0].status.value if runs else "unknown"
    except Exception:  # pragma: no cover - defensive
        return "unknown"
