"""Tests for the env-loading helper."""

from __future__ import annotations

import pytest

from app.configuration import settings


@pytest.fixture(autouse=True)
def _reset_loader():
    settings._loaded = False
    yield
    settings._loaded = False


def test_get_env_returns_os_value(monkeypatch):
    monkeypatch.setenv("MY_KEY", "from_os")
    assert settings.get_env("MY_KEY") == "from_os"


def test_get_env_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("MY_KEY", raising=False)
    assert settings.get_env("MY_KEY", default="fallback") == "fallback"


def test_get_env_required_raises_when_missing(monkeypatch):
    monkeypatch.delenv("MY_KEY", raising=False)
    with pytest.raises(settings.ConfigError, match="Missing required configuration"):
        settings.get_env("MY_KEY", required=True)


def test_get_env_treats_empty_string_as_missing(monkeypatch):
    monkeypatch.setenv("MY_KEY", "")
    assert settings.get_env("MY_KEY", default="fallback") == "fallback"


def test_app_env_default(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    assert settings.app_env() == "local"
