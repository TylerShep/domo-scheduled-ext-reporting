"""Reports CRUD tests: list, view, create, update, delete, validate."""

from __future__ import annotations

from pathlib import Path


def _csrf(client, web_config) -> str:
    return client.cookies.get(web_config.csrf_cookie) or ""


def test_list_reports_empty(auth_client):
    resp = auth_client.get("/reports", follow_redirects=False)
    assert resp.status_code == 200
    assert "No reports" in resp.text or "empty" in resp.text.lower()


def test_create_report_writes_file(auth_client, web_config, reports_dir, sample_yaml_text):
    resp = auth_client.post(
        "/reports",
        data={
            "filename": "demo.yaml",
            "content": sample_yaml_text,
            "csrf_token": _csrf(auth_client, web_config),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/reports/demo.yaml"
    file_path: Path = reports_dir / "demo.yaml"
    assert file_path.exists()
    assert "name: demo" in file_path.read_text()


def test_create_rejects_bad_filename(auth_client, web_config, sample_yaml_text):
    resp = auth_client.post(
        "/reports",
        data={
            "filename": "../escape.yaml",
            "content": sample_yaml_text,
            "csrf_token": _csrf(auth_client, web_config),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_create_rejects_invalid_yaml(auth_client, web_config):
    resp = auth_client.post(
        "/reports",
        data={
            "filename": "bad.yaml",
            "content": "this is: not: valid: yaml:\n  - because",
            "csrf_token": _csrf(auth_client, web_config),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_update_writes_file(auth_client, web_config, reports_dir, sample_yaml_text):
    path = reports_dir / "demo.yaml"
    path.write_text(sample_yaml_text)
    resp = auth_client.post(
        "/reports/demo.yaml",
        data={
            "content": sample_yaml_text.replace("demo_file", "demo_file_v2"),
            "csrf_token": _csrf(auth_client, web_config),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "demo_file_v2" in path.read_text()


def test_delete_removes_file(auth_client, web_config, reports_dir, sample_yaml_text):
    path = reports_dir / "doomed.yaml"
    path.write_text(sample_yaml_text)
    resp = auth_client.post(
        "/reports/doomed.yaml/delete",
        data={"csrf_token": _csrf(auth_client, web_config)},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert not path.exists()


def test_validate_returns_json(auth_client, web_config, sample_yaml_text):
    resp = auth_client.post(
        "/reports/validate",
        data={"content": sample_yaml_text, "csrf_token": _csrf(auth_client, web_config)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["report_name"] == "demo"


def test_validate_returns_errors(auth_client, web_config):
    resp = auth_client.post(
        "/reports/validate",
        data={"content": "foo: bar", "csrf_token": _csrf(auth_client, web_config)},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]


def test_mutations_require_csrf(auth_client, sample_yaml_text):
    # Same browser, no csrf_token field -- should be rejected.
    resp = auth_client.post(
        "/reports",
        data={"filename": "x.yaml", "content": sample_yaml_text},
        follow_redirects=False,
    )
    assert resp.status_code == 403
