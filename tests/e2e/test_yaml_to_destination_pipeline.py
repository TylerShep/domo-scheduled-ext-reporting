"""End-to-end test: YAML file → ``DomoBase.execute_service`` → destination + history.

We wire the :class:`FakeEngine` from ``conftest``, a custom
:class:`_RecordingDestination`, and a temp SQLite history backend, then
run a report via the YAML loader to prove every surface we shipped in
Waves 1-13 still plays well together.
"""

from __future__ import annotations

import pytest
import yaml

from app.configuration.report_loader import YamlReport, parse_report_file
from app.destinations.registry import register_destination
from app.history.registry import get_backend
from tests.factories import card_yaml, report_yaml


class _RecordingDestination:
    """Captures every send_image/dataset call. Implements the :class:`Destination` surface."""

    def __init__(self, **config):
        self.config = config
        self.key = "recording"
        self.label = "recording"
        self.send_when = None
        self.dry_run = False
        self.prepared = False
        self.sends: list[dict] = []
        self.datasets: list[dict] = []
        self.torn_down = False

    def describe(self) -> str:
        return "recording(test)"

    def prepare(self) -> None:
        self.prepared = True

    def send_image(self, ctx):  # noqa: D401
        """Record what we were asked to send."""
        self.sends.append(
            {
                "card_name": ctx.card_name,
                "card_url": ctx.card_url,
                "page_name": ctx.page_name,
                "image_path": ctx.image_path,
            }
        )

    def send_dataset(self, ctx):
        self.datasets.append(
            {"name": ctx.dataset_name, "path": ctx.file_path, "format": ctx.file_format}
        )

    def teardown(self) -> None:
        self.torn_down = True


@pytest.fixture
def recording_destination(monkeypatch):
    holder: dict[str, _RecordingDestination] = {}

    def _factory(**config):
        dest = _RecordingDestination(**config)
        holder["last"] = dest
        return dest

    register_destination("recording", _factory)
    yield holder


@pytest.fixture
def seed_metadata(monkeypatch, tmp_path):
    """Stub out the card-metadata CSV lookup with a fixed result."""

    monkeypatch.setenv("DOMO_CARDS_META_DATASET_ID", "fake-meta-id")

    def _fake_query(card, meta_path):
        # Always resolve to card id 10 / page Sales / URL.
        return 10, "https://example/10", "Sales"

    monkeypatch.setattr("app.services.base.query_card_metadata", _fake_query, raising=True)


def test_yaml_report_flows_through_engine_and_destination(
    tmp_reports_dir, fake_engine, recording_destination, seed_metadata
):
    payload = report_yaml(
        name="e2e_demo",
        metadata_dataset_file_name="e2e_demo",
        cards=[card_yaml(dashboard="Sales", card="Example Card")],
        destinations=[{"type": "recording"}],
    )
    file = tmp_reports_dir / "e2e_demo.yaml"
    file.write_text(yaml.safe_dump(payload, sort_keys=False))

    spec = parse_report_file(file)
    report = YamlReport(spec)
    report.execute_service()

    dest = recording_destination["last"]
    assert dest.prepared is True
    assert dest.torn_down is True
    assert len(dest.sends) == 1
    assert dest.sends[0]["card_name"] == "Example Card"

    backend = get_backend()
    runs = backend.get_runs(report_name="e2e_demo", limit=5)
    assert len(runs) == 1
    run = runs[0]
    assert run.report_name == "e2e_demo"
    assert run.status.value in {"success", "partial"}


def test_yaml_report_skips_when_send_when_false(
    tmp_reports_dir, fake_engine, recording_destination, seed_metadata
):
    payload = report_yaml(
        name="e2e_gated",
        metadata_dataset_file_name="e2e_gated",
        cards=[
            card_yaml(
                dashboard="Sales",
                card="Example Card",
                send_when="False",  # always-false -- should skip
            )
        ],
        destinations=[{"type": "recording"}],
    )
    file = tmp_reports_dir / "e2e_gated.yaml"
    file.write_text(yaml.safe_dump(payload, sort_keys=False))

    spec = parse_report_file(file)
    YamlReport(spec).execute_service()

    dest = recording_destination["last"]
    assert dest.sends == []


def test_yaml_report_dataset_pipeline(tmp_reports_dir, tmp_path, fake_engine, seed_metadata):
    """Exercise the dataset pipeline end-to-end with a ``file`` destination."""

    out_dir = tmp_path / "dataset_outputs"
    payload = report_yaml(
        name="e2e_dataset",
        metadata_dataset_file_name="e2e_dataset",
        cards=None,
        datasets=[
            {"name": "daily_rollup", "dataset_id": "abc-123", "format": "csv"},
        ],
        destinations=[
            {
                "type": "file",
                "target": "local",
                "output_dir": str(out_dir),
            }
        ],
    )
    file = tmp_reports_dir / "e2e_dataset.yaml"
    file.write_text(yaml.safe_dump(payload, sort_keys=False))

    spec = parse_report_file(file)
    YamlReport(spec).execute_service()

    # The fake engine wrote a CSV; the file destination should have dropped a
    # copy into output_dir.
    produced = list(out_dir.glob("*.csv"))
    assert len(produced) == 1, f"expected one output CSV, got {produced}"
