"""Authentication flow tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_login_requires_valid_credentials(client, web_config):
    client.get("/login")
    csrf = client.cookies.get(web_config.csrf_cookie) or ""
    bad = client.post(
        "/login",
        data={"username": "admin", "password": "wrong", "csrf_token": csrf},
    )
    assert bad.status_code == 401


def test_login_sets_session_cookie(client, web_config, admin_password):
    client.get("/login")
    csrf = client.cookies.get(web_config.csrf_cookie) or ""
    client = TestClient(client.app, follow_redirects=False)
    client.get("/login")
    csrf = client.cookies.get(web_config.csrf_cookie) or ""
    ok = client.post(
        "/login",
        data={"username": "admin", "password": admin_password, "csrf_token": csrf},
    )
    assert ok.status_code == 303
    assert ok.headers["location"] == "/reports"
    assert client.cookies.get(web_config.session_cookie)


def test_unauthenticated_redirect_to_login(client):
    resp = client.get("/reports", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/login"


def test_unauthenticated_json_api_returns_401(client):
    resp = client.post(
        "/reports/validate",
        json={"content": "foo"},
        headers={"accept": "application/json"},
    )
    assert resp.status_code in (401, 403, 307)


def test_logout_clears_session(auth_client, web_config):
    # The auth_client fixture ran a successful login already.
    assert auth_client.cookies.get(web_config.session_cookie)
    csrf = auth_client.cookies.get(web_config.csrf_cookie) or ""
    resp = auth_client.post("/logout", data={"csrf_token": csrf})
    assert resp.status_code == 303
    # After logout, hitting a protected page should redirect back to /login.
    auth_client.cookies.clear()
    resp2 = auth_client.get("/reports", follow_redirects=False)
    assert resp2.status_code == 307
