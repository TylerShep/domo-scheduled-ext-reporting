"""Shared fixtures for the web UI test suite.

Every test gets a fresh :class:`YamlStore` rooted in a temp directory, a fresh
:class:`FastAPI` app, and an authenticated :class:`httpx.Client` pointed at
it so writing happy-path tests stays a one-liner.
"""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.auth import hash_password
from app.web.config import WebConfig


@pytest.fixture
def admin_password() -> str:
    return "s3cr3t-test-password"


@pytest.fixture
def reports_dir(tmp_path) -> Path:
    reports = tmp_path / "reports"
    reports.mkdir()
    return reports


@pytest.fixture
def web_config(tmp_path, reports_dir, admin_password) -> WebConfig:
    return WebConfig(
        reports_dir=reports_dir,
        session_secret=secrets.token_urlsafe(24),
        session_cookie="domo_session",
        session_max_age_seconds=600,
        admin_username="admin",
        admin_password_hash=hash_password(admin_password),
        admin_password_plain=None,
        csrf_cookie="domo_csrf",
        allow_destination_tests=True,
        bind_host="127.0.0.1",
        bind_port=8080,
    )


@pytest.fixture
def app(web_config):
    return create_app(web_config)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_client(app, web_config, admin_password) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    # First GET primes the CSRF cookie.
    c.get("/login")
    csrf = c.cookies.get(web_config.csrf_cookie) or ""
    response = c.post(
        "/login",
        data={
            "username": web_config.admin_username,
            "password": admin_password,
            "csrf_token": csrf,
        },
    )
    assert response.status_code in (200, 303), response.text
    return c


_VALID_YAML = """name: demo
metadata_dataset_file_name: demo_file

cards:
  - dashboard: Dash
    card: "Sales by Region"
    viz_type: "Single Value"

destinations:
  - type: slack
    channel_name: "#demo"
"""


@pytest.fixture
def sample_yaml_text() -> str:
    return _VALID_YAML
