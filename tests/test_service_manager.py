"""Tests for the ServiceManager registry."""

from __future__ import annotations

import pytest

from app.services.base import DomoBase
from app.service_manager.exceptions import ServiceManagerException
from app.service_manager.manager import ServiceManager


class _FakeReport(DomoBase):
    def __init__(self, name: str, sink: list[str]) -> None:
        self.name = name
        self._sink = sink

    def file_name(self) -> str:
        return f"{self.name}_metadata"

    def list_of_cards(self):
        return [["d", "c", "Single Value"]]

    def execute_service(self) -> None:
        self._sink.append(self.name)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Make sure each test gets a clean registry."""

    ServiceManager.reset()
    ServiceManager._initialized = True  # skip auto-discovery
    yield
    ServiceManager.reset()


def test_register_and_lookup():
    sink: list[str] = []
    ServiceManager.register("alpha", _FakeReport("alpha", sink))

    assert ServiceManager.get_sync_names() == ["alpha"]
    reports = ServiceManager.get_reports("alpha")
    assert len(reports) == 1
    assert reports[0].name == "alpha"


def test_execute_runs_every_registered_instance():
    sink: list[str] = []
    ServiceManager.register("alpha", _FakeReport("alpha", sink))
    ServiceManager.register("alpha", _FakeReport("alpha", sink))

    ServiceManager.execute("alpha")
    assert sink == ["alpha", "alpha"]


def test_execute_unknown_key_raises():
    with pytest.raises(ServiceManagerException, match="No report registered"):
        ServiceManager.execute("does_not_exist")


def test_execute_all_runs_each_key_once():
    sink: list[str] = []
    ServiceManager.register("alpha", _FakeReport("alpha", sink))
    ServiceManager.register("beta", _FakeReport("beta", sink))

    ServiceManager.execute_all()
    assert sorted(sink) == ["alpha", "beta"]
