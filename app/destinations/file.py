"""Dataset / CSV / Excel delivery via the :class:`FileDestination`.

A ``file`` destination doesn't take ``send_image`` calls -- it ignores
them and instead consumes :class:`DatasetContext` rows produced by the
report's ``datasets:`` YAML block.

YAML example::

    datasets:
      - name: "Daily orders"
        dataset_id: "abc-123"
        format: csv          # csv | xlsx
    destinations:
      - type: file
        target: slack         # slack | teams_graph | email | local
        channel_name: "data-drops"

Sub-targets:
    * ``slack``        -- delegates to a :class:`SlackDestination` and
      uploads the file via ``files_upload_v2``.
    * ``teams_graph``  -- delegates to a :class:`TeamsGraphDestination`
      and uploads the file to the channel's SharePoint folder.
    * ``email``        -- buffers the dataset for the run-end email
      assembled by :class:`~app.destinations.email.EmailDestination`.
    * ``local``        -- writes the file to ``output_dir`` (default:
      ``app/temp_files/``) and logs the path. Useful for debug + the web
      UI's ``Download`` button.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.destinations.base import (
    DatasetContext,
    Destination,
    DestinationContext,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


_KNOWN_TARGETS = {"slack", "teams_graph", "teams", "email", "local"}
_KNOWN_FORMATS = {"csv", "xlsx"}


class FileDestinationError(RuntimeError):
    """Raised on misconfiguration or sub-target failures."""


class FileDestination(Destination):
    """Delivers raw datasets as CSV or XLSX files.

    The ``target`` field selects a sub-destination that knows how to
    actually transmit the file. ``FileDestination`` itself is responsible
    for:

        * Writing the file to the right path
        * Converting CSV to XLSX when ``format: xlsx`` is requested
        * Calling ``send_dataset`` on the sub-destination
        * Buffering for batch-style sub-targets (email)
    """

    key = "file"
    label = "File"

    def __init__(
        self,
        target: str = "local",
        output_dir: str | None = None,
        sub_destination_spec: dict | None = None,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> None:
        target_norm = target.lower()
        if target_norm not in _KNOWN_TARGETS:
            raise FileDestinationError(
                f"Unknown FileDestination target={target!r}. "
                f"Expected one of {sorted(_KNOWN_TARGETS)}."
            )
        super().__init__(
            target=target_norm,
            output_dir=output_dir,
            sub_destination_spec=sub_destination_spec,
            dry_run=dry_run,
            **kwargs,
        )
        self.target = target_norm
        self.output_dir = output_dir
        self._sub_spec = sub_destination_spec or self._infer_sub_spec(kwargs)
        self._sub_destination: Destination | None = None

    # ---- lifecycle ----

    def prepare(self) -> None:
        if self._is_dry_run():
            return
        if self.target == "local":
            return
        if self.target == "email":
            return
        self._sub_destination = self._build_sub_destination()
        self._sub_destination.prepare()

    def teardown(self) -> None:
        if self._sub_destination is not None:
            try:
                self._sub_destination.teardown()
            except Exception:
                logger.exception("FileDestination sub-destination teardown failed")

    # ---- send ----

    def send_image(self, ctx: DestinationContext) -> None:
        # FileDestination doesn't deliver images; report runner skips it
        # for cards but we override to a no-op so the dispatcher can still
        # iterate destinations uniformly.
        logger.debug(
            "FileDestination(target=%s) ignoring image %s",
            self.target,
            ctx.card_name,
        )

    def send_dataset(self, ctx: DatasetContext) -> None:
        if ctx.file_format not in _KNOWN_FORMATS:
            raise FileDestinationError(
                f"Unsupported dataset format={ctx.file_format!r}. "
                f"Expected one of {sorted(_KNOWN_FORMATS)}."
            )

        if self._is_dry_run():
            self._log_dry_run_send(
                kind="dataset",
                target=self.target,
                detail=f"{ctx.dataset_name} ({ctx.file_format})",
            )
            return

        actual_path = self._materialize(ctx)

        if self.target == "local":
            destination_path = self._copy_to_output_dir(actual_path)
            logger.info("Wrote dataset %s -> %s", ctx.dataset_name, destination_path)
            return

        if self.target == "email":
            # Buffering happens in the email destination's pre-send hook.
            # We just leave the file on disk and tag it for collection.
            logger.info(
                "Buffered dataset %s (%s) for email delivery",
                ctx.dataset_name,
                ctx.file_format,
            )
            return

        if self._sub_destination is None:
            self.prepare()
        assert self._sub_destination is not None

        delivered_ctx = DatasetContext(
            file_path=actual_path,
            dataset_name=ctx.dataset_name,
            dataset_id=ctx.dataset_id,
            file_format=ctx.file_format,
            extra=dict(ctx.extra),
        )
        self._sub_destination.send_dataset(delivered_ctx)

    # ---- internals ----

    def _materialize(self, ctx: DatasetContext) -> str:
        """Convert the source CSV to the requested format if needed."""

        if ctx.file_format == "csv":
            return ctx.file_path
        return _csv_to_xlsx(ctx.file_path)

    def _copy_to_output_dir(self, source_path: str) -> str:
        if self.output_dir is None:
            target_dir = Path(source_path).parent
        else:
            target_dir = Path(self.output_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / Path(source_path).name
        if Path(source_path).resolve() != target.resolve():
            shutil.copy2(source_path, target)
        return str(target)

    def _build_sub_destination(self) -> Destination:
        from app.destinations.registry import build_destination

        spec = dict(self._sub_spec or {})
        spec.setdefault(
            "type",
            (
                "slack"
                if self.target == "slack"
                else "teams" if self.target in {"teams_graph", "teams"} else self.target
            ),
        )
        if self.target == "teams_graph":
            spec.setdefault("auth_mode", "graph")
        return build_destination(spec)

    def _infer_sub_spec(self, leftover_kwargs: dict[str, Any]) -> dict[str, Any]:
        """Build a sub-destination YAML spec out of any extra kwargs.

        Reports usually inline the sub-destination's options on the
        FileDestination block (e.g. ``channel_name`` directly on a slack
        target). We hoist those into a real spec dict so we can reuse the
        existing registry / factories.
        """

        if self.target == "local":
            return {}
        if self.target == "email":
            return {}
        # Gate keys belong to *this* FileDestination, not its sub-destination.
        reserved = {"send_when"}
        return {
            k: v for k, v in leftover_kwargs.items() if not k.startswith("_") and k not in reserved
        }


def _csv_to_xlsx(csv_path: str) -> str:
    """Convert ``csv_path`` to a sibling ``.xlsx`` file (using openpyxl)."""

    try:
        import csv

        from openpyxl import Workbook  # type: ignore[import-untyped]
    except ImportError as exc:
        raise FileDestinationError(
            "Excel output requires `openpyxl`. Install with "
            '`pip install "domo-scheduled-ext-reporting[xlsx]"`.'
        ) from exc

    wb = Workbook()
    ws = wb.active
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            ws.append(row)
    xlsx_path = str(Path(csv_path).with_suffix(".xlsx"))
    wb.save(xlsx_path)
    return xlsx_path
