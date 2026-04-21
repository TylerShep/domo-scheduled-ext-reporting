"""Tests for the FileDestination (CSV / XLSX delivery)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.destinations.base import DatasetContext, DestinationContext
from app.destinations.file import FileDestination, FileDestinationError


def _make_ctx(tmp_path, fmt: str = "csv") -> DatasetContext:
    source = tmp_path / "data.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")
    return DatasetContext(
        file_path=str(source),
        dataset_name="Daily Orders",
        dataset_id="abc-123",
        file_format=fmt,
    )


def test_invalid_target_raises():
    with pytest.raises(FileDestinationError, match="Unknown FileDestination target"):
        FileDestination(target="floppy-disk")


def test_unknown_format_raises(tmp_path):
    dest = FileDestination(target="local", output_dir=str(tmp_path))
    ctx = DatasetContext(
        file_path=str(tmp_path / "x.csv"),
        dataset_name="x",
        dataset_id="x",
        file_format="parquet",
    )
    with pytest.raises(FileDestinationError, match="Unsupported dataset format"):
        dest.send_dataset(ctx)


def test_local_target_copies_into_output_dir(tmp_path):
    output_dir = tmp_path / "out"
    dest = FileDestination(target="local", output_dir=str(output_dir))
    ctx = _make_ctx(tmp_path)
    dest.send_dataset(ctx)
    assert (output_dir / "data.csv").read_text() == "a,b\n1,2\n"


def test_local_target_xlsx_writes_workbook(tmp_path):
    output_dir = tmp_path / "out"
    dest = FileDestination(target="local", output_dir=str(output_dir))
    ctx = _make_ctx(tmp_path, fmt="xlsx")
    dest.send_dataset(ctx)
    written = output_dir / "data.xlsx"
    assert written.exists()
    # openpyxl writes a ZIP-based .xlsx; the file must be non-empty.
    assert written.stat().st_size > 0


def test_slack_target_delegates_to_slack_destination(monkeypatch, tmp_path):
    """The file destination should build + delegate to a Slack sub-dest."""

    monkeypatch.setenv("SLACK_BOT_USER_TOKEN", "xoxb-fake")
    dest = FileDestination(target="slack", channel_name="data-drops")

    stub = MagicMock()
    dest._sub_destination = stub
    dest.send_dataset(_make_ctx(tmp_path))

    stub.send_dataset.assert_called_once()
    forwarded = stub.send_dataset.call_args.args[0]
    assert forwarded.dataset_name == "Daily Orders"
    assert forwarded.file_format == "csv"


def test_send_image_is_noop(tmp_path):
    dest = FileDestination(target="local", output_dir=str(tmp_path / "x"))
    ctx = DestinationContext(
        image_path=str(tmp_path / "img.png"),
        card_name="n",
        card_url="u",
        page_name="p",
    )
    dest.send_image(ctx)  # should not raise


def test_prepare_builds_sub_destination_for_non_local_targets(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_USER_TOKEN", "xoxb-fake")
    dest = FileDestination(target="slack", channel_name="data-drops")

    fake = MagicMock()
    monkeypatch.setattr(dest, "_build_sub_destination", lambda: fake)
    dest.prepare()
    fake.prepare.assert_called_once()


def test_email_target_buffers(tmp_path):
    dest = FileDestination(target="email")
    dest.prepare()  # should not raise
    dest.send_dataset(_make_ctx(tmp_path))  # logs only
