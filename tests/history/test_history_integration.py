"""End-to-end test: a stubbed report execution writes a row.

We swap out the engine, destinations, and scratch-folder helpers so the
test never touches Domo, Slack, or the real filesystem outside ``tmp_path``.
"""

from __future__ import annotations

from collections.abc import Sequence
from unittest.mock import patch

import pandas as pd

from app.destinations.base import Destination, DestinationContext
from app.engines.base import DomoEngine
from app.history import RunStatus, get_backend
from app.services.base import DomoBase


class _StubEngine(DomoEngine):
    key = "stub"
    label = "Stub"

    def __init__(self):
        self.exported: list[tuple[str, str]] = []
        self.generated: list[tuple[int, str]] = []

    def export_dataset(self, dataset_id: str, output_path: str) -> None:
        self.exported.append((dataset_id, output_path))
        df = pd.DataFrame(
            [
                {
                    "CardID": 100,
                    "CardName": "Revenue",
                    "CardURL": "https://example.com/c/100",
                    "PageID": 1,
                    "PageTItle": "Sales",
                }
            ]
        )
        df.to_csv(output_path, index=False)

    def generate_card_image(self, card_id: int, output_path: str, **opts) -> None:
        self.generated.append((card_id, output_path))
        with open(output_path, "wb") as fh:
            fh.write(b"\x89PNG fake")


class _StubDestination(Destination):
    key = "stub"
    label = "Stub"

    def __init__(self, **config) -> None:
        super().__init__(**config)
        self.sent: list[DestinationContext] = []

    def send_image(self, ctx: DestinationContext) -> None:
        self.sent.append(ctx)


class _StubReport(DomoBase):
    name = "integration_report"

    def __init__(self, engine: _StubEngine, destination: _StubDestination):
        self._engine = engine
        self._destination = destination

    def file_name(self) -> str:
        return "integration_metadata"

    def list_of_cards(self) -> Sequence[Sequence]:
        return [["Sales", "Revenue", "Single Value"]]

    def build_destinations(self):
        return [self._destination]

    def get_engine(self):
        return self._engine


def test_full_run_writes_history_row(monkeypatch, tmp_path):
    monkeypatch.setenv("DOMO_CARDS_META_DATASET_ID", "ds-1")
    monkeypatch.setenv("RUN_HISTORY_BACKEND", "sqlite")
    monkeypatch.setenv("RUN_HISTORY_DB_PATH", str(tmp_path / "runs.db"))

    # Redirect scratch folders into tmp_path so we don't pollute app/.
    monkeypatch.setattr("app.utils.project_setup_util._app_dir", lambda: tmp_path)

    engine = _StubEngine()
    destination = _StubDestination()
    report = _StubReport(engine, destination)

    # Image edits aren't the focus -- skip them so we don't load PIL.
    with patch("app.utils.image_util.edit_card_images"):
        report.execute_service()

    runs = get_backend().get_runs(report_name="integration_report")
    assert len(runs) == 1
    run = runs[0]
    assert run.status == RunStatus.SUCCESS
    assert run.duration_seconds() is not None and run.duration_seconds() >= 0
    assert len(run.cards) == 1
    assert run.cards[0].card_name == "Revenue"
    assert run.cards[0].sent is True
    assert len(run.destinations) == 1
    assert run.destinations[0].cards_sent == 1
    assert engine.exported == [
        ("ds-1", str(tmp_path / "cards_metadata" / "integration_metadata.csv"))
    ]


def test_no_destinations_marks_skipped(monkeypatch, tmp_path):
    monkeypatch.setenv("DOMO_CARDS_META_DATASET_ID", "ds-1")
    monkeypatch.setenv("RUN_HISTORY_DB_PATH", str(tmp_path / "runs.db"))

    class _NoDest(_StubReport):
        def build_destinations(self):
            return []

    report = _NoDest(_StubEngine(), _StubDestination())
    report.execute_service()

    runs = get_backend().get_runs(report_name="integration_report")
    assert runs[0].status == RunStatus.SKIPPED
