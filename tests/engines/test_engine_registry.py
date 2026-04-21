"""Tests for the engine factory + cache."""

from __future__ import annotations

import pytest

from app.engines import (
    DomoEngine,
    DomoEngineError,
    available_engines,
    get_engine,
    register_engine,
    reset_engine_cache,
)
from app.engines.jar import JarEngine
from app.engines.rest import RestEngine


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


def test_default_engine_is_rest(monkeypatch):
    monkeypatch.delenv("DOMO_ENGINE", raising=False)
    engine = get_engine()
    assert isinstance(engine, RestEngine)


def test_explicit_jar_returns_jar_engine(monkeypatch):
    monkeypatch.setenv("DOMO_ENGINE", "jar")
    engine = get_engine()
    assert isinstance(engine, JarEngine)


def test_unknown_engine_raises(monkeypatch):
    monkeypatch.setenv("DOMO_ENGINE", "made_up")
    with pytest.raises(DomoEngineError, match="Unknown DOMO_ENGINE"):
        get_engine()


def test_force_key_overrides_env(monkeypatch):
    monkeypatch.setenv("DOMO_ENGINE", "rest")
    engine = get_engine(force_key="jar")
    assert isinstance(engine, JarEngine)
    # force_key should NOT pollute the cache.
    assert isinstance(get_engine(), RestEngine)


def test_engine_is_cached(monkeypatch):
    monkeypatch.setenv("DOMO_ENGINE", "rest")
    a = get_engine()
    b = get_engine()
    assert a is b


def test_reset_cache_returns_fresh_instance(monkeypatch):
    monkeypatch.setenv("DOMO_ENGINE", "rest")
    a = get_engine()
    reset_engine_cache()
    b = get_engine()
    assert a is not b


def test_auto_picks_rest_when_oauth_set(monkeypatch):
    monkeypatch.setenv("DOMO_ENGINE", "auto")
    monkeypatch.setenv("DOMO_CLIENT_ID", "id")
    monkeypatch.setenv("DOMO_CLIENT_SECRET", "secret")
    engine = get_engine()
    assert isinstance(engine, RestEngine)


def test_auto_picks_jar_when_only_java_present(monkeypatch):
    monkeypatch.setenv("DOMO_ENGINE", "auto")
    monkeypatch.delenv("DOMO_CLIENT_ID", raising=False)
    monkeypatch.delenv("DOMO_CLIENT_SECRET", raising=False)
    monkeypatch.setattr("app.engines.registry.shutil.which", lambda _name: "/usr/bin/java")
    engine = get_engine()
    assert isinstance(engine, JarEngine)


def test_auto_raises_when_nothing_works(monkeypatch):
    monkeypatch.setenv("DOMO_ENGINE", "auto")
    monkeypatch.delenv("DOMO_CLIENT_ID", raising=False)
    monkeypatch.delenv("DOMO_CLIENT_SECRET", raising=False)
    monkeypatch.setattr("app.engines.registry.shutil.which", lambda _name: None)
    with pytest.raises(DomoEngineError, match="auto could not pick"):
        get_engine()


def test_register_custom_engine(monkeypatch):
    class Stub(DomoEngine):
        key = "stub"
        label = "Stub"

        def export_dataset(self, dataset_id, output_path):
            pass

        def generate_card_image(self, card_id, output_path, **opts):
            pass

    register_engine("stub", Stub)
    monkeypatch.setenv("DOMO_ENGINE", "stub")
    engine = get_engine()
    assert isinstance(engine, Stub)
    assert "stub" in available_engines()
