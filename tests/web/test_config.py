"""Tests for :class:`WebConfig.from_env`."""

from __future__ import annotations

from pathlib import Path

from app.web.config import WebConfig


def test_from_env_returns_defaults(monkeypatch):
    for key in [
        "DOMO_WEB_REPORTS_DIR",
        "DOMO_WEB_SESSION_SECRET",
        "DOMO_WEB_SESSION_COOKIE",
        "DOMO_WEB_SESSION_TTL",
        "DOMO_WEB_ADMIN_USER",
        "DOMO_WEB_ADMIN_PASSWORD_HASH",
        "DOMO_WEB_ADMIN_PASSWORD",
        "DOMO_WEB_CSRF_COOKIE",
        "DOMO_WEB_ALLOW_DESTINATION_TESTS",
        "DOMO_WEB_HOST",
        "DOMO_WEB_PORT",
    ]:
        monkeypatch.delenv(key, raising=False)

    cfg = WebConfig.from_env()
    assert cfg.bind_host == "127.0.0.1"
    assert cfg.bind_port == 8080
    assert cfg.admin_username == "admin"
    assert cfg.allow_destination_tests is True
    assert cfg.session_cookie == "domo_session"
    # Secret is random but stable within the call
    assert len(cfg.session_secret) > 0


def test_from_env_respects_overrides(monkeypatch, tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setenv("DOMO_WEB_REPORTS_DIR", str(reports))
    monkeypatch.setenv("DOMO_WEB_SESSION_SECRET", "xyzzy")
    monkeypatch.setenv("DOMO_WEB_SESSION_TTL", "120")
    monkeypatch.setenv("DOMO_WEB_ADMIN_USER", "tyler")
    monkeypatch.setenv("DOMO_WEB_ADMIN_PASSWORD_HASH", "$argon2id$...")
    monkeypatch.setenv("DOMO_WEB_ALLOW_DESTINATION_TESTS", "false")
    monkeypatch.setenv("DOMO_WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("DOMO_WEB_PORT", "9090")

    cfg = WebConfig.from_env()
    assert cfg.reports_dir == Path(reports).resolve()
    assert cfg.session_secret == "xyzzy"
    assert cfg.session_max_age_seconds == 120
    assert cfg.admin_username == "tyler"
    assert cfg.admin_password_hash == "$argon2id$..."
    assert cfg.allow_destination_tests is False
    assert cfg.bind_host == "0.0.0.0"
    assert cfg.bind_port == 9090


def test_from_env_falls_back_on_bad_int(monkeypatch):
    monkeypatch.setenv("DOMO_WEB_SESSION_TTL", "not-a-number")
    monkeypatch.setenv("DOMO_WEB_PORT", "")
    cfg = WebConfig.from_env()
    assert cfg.session_max_age_seconds == 60 * 60 * 8
    assert cfg.bind_port == 8080


def test_from_env_bool_parses_synonyms(monkeypatch):
    monkeypatch.setenv("DOMO_WEB_ALLOW_DESTINATION_TESTS", "YES")
    assert WebConfig.from_env().allow_destination_tests is True
    monkeypatch.setenv("DOMO_WEB_ALLOW_DESTINATION_TESTS", "off")
    assert WebConfig.from_env().allow_destination_tests is False
    monkeypatch.setenv("DOMO_WEB_ALLOW_DESTINATION_TESTS", "1")
    assert WebConfig.from_env().allow_destination_tests is True
