"""``POST /destinations/test`` smoke-checks a destination spec (dry-run)."""

from __future__ import annotations


def _csrf(client, web_config) -> str:
    return client.cookies.get(web_config.csrf_cookie) or ""


def test_test_destination_requires_auth(client):
    resp = client.post("/destinations/test", json={"type": "slack"})
    assert resp.status_code in (401, 403, 307)


def test_test_destination_happy_path(auth_client, web_config, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_USER_TOKEN", "xoxb-test")
    resp = auth_client.post(
        "/destinations/test",
        json={"type": "slack", "channel_name": "#demo"},
        headers={"X-CSRF-Token": _csrf(auth_client, web_config)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "slack" in body["destination"].lower()


def test_test_destination_reports_error(auth_client, web_config):
    resp = auth_client.post(
        "/destinations/test",
        json={"type": "nonexistent-destination"},
        headers={"X-CSRF-Token": _csrf(auth_client, web_config)},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
