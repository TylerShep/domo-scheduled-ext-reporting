"""Pytest configuration shared by every test module.

Fixtures intentionally bias toward *isolation*: every test gets a fresh
copy of the singletons we care about (engine cache, history backend,
runtime flags), never touches the developer's real ``app/state/`` dir, and
can safely call network-coupled code -- those paths are stubbed via
``responses`` / monkeypatches inside individual tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    """Reset the ServiceManager registry between every test session."""

    from app.service_manager.manager import ServiceManager

    ServiceManager.reset()


@pytest.fixture(autouse=True)
def _reset_engine_and_history(monkeypatch, tmp_path_factory):
    """Isolate process-wide singletons between tests.

    * Resets the engine cache so DOMO_ENGINE changes take effect.
    * Points the SQLite history backend at a tmp file unique to this test
      so we never write to the developer's real ``app/state/runs.db``.
    * Resets :mod:`app.runtime` flags so a leftover ``--dry-run`` from a
      previous test can't bleed into the next one.
    """

    from app.engines import reset_engine_cache
    from app.history import reset_backend_cache
    from app.runtime import RuntimeFlags, set_flags

    db = tmp_path_factory.mktemp("history") / "runs.db"
    monkeypatch.setenv("RUN_HISTORY_DB_PATH", str(db))
    monkeypatch.setenv("RUN_HISTORY_BACKEND", "sqlite")

    set_flags(RuntimeFlags())
    reset_engine_cache()
    reset_backend_cache()
    yield
    set_flags(RuntimeFlags())
    reset_engine_cache()
    reset_backend_cache()


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every env var our app reads so a test starts from a blank slate."""

    for name in (
        "DOMO_ENGINE",
        "DOMO_INSTANCE",
        "DOMO_TOKEN",
        "DOMO_CLIENT_ID",
        "DOMO_CLIENT_SECRET",
        "DOMO_API_HOST",
        "DOMO_CARDS_META_DATASET_ID",
        "SLACK_BOT_USER_TOKEN",
        "TEAMS_TENANT_ID",
        "TEAMS_CLIENT_ID",
        "TEAMS_CLIENT_SECRET",
        "TEAMS_WEBHOOK_URL",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "SMTP_FROM_ADDR",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def tmp_reports_dir(tmp_path):
    """Return a fresh, empty directory suitable as a YAML reports root."""

    reports = tmp_path / "reports"
    reports.mkdir()
    return reports


@pytest.fixture
def fake_engine(monkeypatch):
    """Return a :class:`_FakeEngine` wired into the engine registry.

    Tests that exercise the full report pipeline can use this to assert
    that ``export_dataset`` / ``generate_card_image`` were called with the
    expected arguments, without touching the network.
    """

    from app.engines.base import DomoEngine
    from app.engines.registry import register_engine, reset_engine_cache

    calls: dict[str, list] = {"export": [], "card": []}

    class _FakeEngine(DomoEngine):
        key = "fake"

        def describe(self) -> str:
            return "fake (test stub)"

        def health_check(self):
            return True, "ok"

        def export_dataset(self, dataset_id: str, output_path: str) -> None:
            calls["export"].append((dataset_id, output_path))
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text("col\nval\n")

        def generate_card_image(self, card_id: int, output_path: str) -> None:
            calls["card"].append((card_id, output_path))
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            # Real PNG bytes so downstream Pillow / image_util can open it.
            from PIL import Image

            Image.new("RGBA", (64, 48), color=(200, 200, 200, 255)).save(output_path)

        def generate_card_images(self, requests):
            for r in requests:
                self.generate_card_image(r.card_id, r.output_path)

        def list_cards(self, **kwargs):
            return []

    engine = _FakeEngine()
    engine.calls = calls  # type: ignore[attr-defined]
    register_engine("fake", lambda: engine)
    monkeypatch.setenv("DOMO_ENGINE", "fake")
    reset_engine_cache()
    return engine
