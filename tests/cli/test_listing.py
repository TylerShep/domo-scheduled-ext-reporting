"""Tests for `app.cli.listing`."""

from __future__ import annotations

from app.cli.listing import (
    list_destinations,
    list_engines,
    print_with_labels,
)


def test_list_engines_contains_rest_and_jar():
    engines = list_engines()
    assert "rest" in engines
    assert "jar" in engines
    assert "auto" in engines


def test_list_destinations_contains_core_types():
    destinations = list_destinations()
    for key in ("slack", "teams", "file", "email"):
        assert key in destinations


def test_list_engines_includes_custom_registrations():
    """Engines registered at runtime should show up in list_engines()."""

    from app.engines.registry import register_engine

    class _FakeEngine:
        def __init__(self):
            self.key = "fakey"

    register_engine("fakey", _FakeEngine)
    engines = list_engines()
    assert "fakey" in engines


def test_list_destinations_includes_custom_registrations():
    from app.destinations.base import Destination
    from app.destinations.registry import register_destination

    class _FakeDestination(Destination):
        key = "carrier-pigeon"
        label = "Carrier Pigeon"

        def send_image(self, ctx):  # type: ignore[override]
            pass

    register_destination("carrier-pigeon", _FakeDestination)
    destinations = list_destinations()
    assert "carrier-pigeon" in destinations


def test_print_with_labels_respects_rich_unavailable(capsys, monkeypatch):
    """Even if rich is unavailable, print_with_labels falls back to plain print."""

    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name.startswith("rich"):
            raise ImportError("pretend rich isn't installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    exit_code = print_with_labels(["rest", "jar"], "engines")
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "rest" in output
    assert "jar" in output


def test_print_with_labels_returns_zero_on_empty_input(capsys):
    exit_code = print_with_labels([], "engines")
    assert exit_code == 0
