"""Tests for the JAR-based Domo engine.

We patch :mod:`subprocess.Popen` so no JVM is actually spawned.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.engines import CardImageRequest
from app.engines.jar import JarEngine, JarEngineError


@pytest.fixture(autouse=True)
def _set_jar_creds(monkeypatch):
    monkeypatch.setenv("DOMO_INSTANCE", "example.domo.com")
    monkeypatch.setenv("DOMO_TOKEN", "tok")
    monkeypatch.setenv("DOMO_CARDS_META_DATASET_ID", "ds-1")


@pytest.fixture
def jar_path(tmp_path) -> str:
    """Return a path to a tangible (if empty) JAR file so the existence
    guard inside :class:`JarEngine` does not fire for tests that mock
    :mod:`subprocess.Popen`.
    """

    path = tmp_path / "domoUtil.jar"
    path.write_bytes(b"")
    return str(path)


def _fake_popen(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    process = MagicMock()
    process.communicate.return_value = (stdout, stderr)
    process.returncode = returncode
    return process


def test_export_dataset_invokes_popen_with_jar_path(tmp_path, jar_path):
    out = tmp_path / "data.csv"
    engine = JarEngine(jar_path=jar_path)

    with patch("app.engines.jar.subprocess.Popen", return_value=_fake_popen()) as popen:
        engine.export_dataset("ds-1", str(out))

    args, _ = popen.call_args
    assert args[0][0] == "java"
    assert args[0][1] == "-jar"
    assert args[0][2] == jar_path


def test_generate_card_images_batches_into_one_jvm(tmp_path, jar_path):
    requests = [
        CardImageRequest(card_id=10, output_path=str(tmp_path / "a.png")),
        CardImageRequest(card_id=11, output_path=str(tmp_path / "b.png")),
        CardImageRequest(card_id=12, output_path=str(tmp_path / "c.png")),
    ]
    engine = JarEngine(jar_path=jar_path)

    with patch("app.engines.jar.subprocess.Popen", return_value=_fake_popen()) as popen:
        engine.generate_card_images(requests)

    assert popen.call_count == 1
    fed_input = popen.return_value.communicate.call_args[0][0]
    assert "generate-card-image -i 10" in fed_input
    assert "generate-card-image -i 11" in fed_input
    assert "generate-card-image -i 12" in fed_input
    assert fed_input.startswith("connect -s ")
    assert fed_input.endswith("exit\n")


def test_nonzero_exit_raises_after_retries(tmp_path, jar_path):
    out = tmp_path / "data.csv"
    engine = JarEngine(jar_path=jar_path)

    with patch(
        "app.engines.jar.subprocess.Popen",
        return_value=_fake_popen(stderr="bad", returncode=2),
    ):
        with pytest.raises(JarEngineError, match="exited with code 2"):
            engine.export_dataset("ds-1", str(out))


def test_timeout_kills_process_and_raises(tmp_path, jar_path):
    out = tmp_path / "data.csv"
    engine = JarEngine(jar_path=jar_path, timeout_seconds=1)

    def _new_process(*_args, **_kwargs):
        proc = MagicMock(returncode=0)
        proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="java", timeout=1),
            ("", ""),
        ]
        return proc

    with patch("app.engines.jar.subprocess.Popen", side_effect=_new_process):
        with pytest.raises(JarEngineError, match="timed out"):
            engine.export_dataset("ds-1", str(out))


def test_missing_java_binary_raises_descriptive_error(tmp_path, jar_path):
    engine = JarEngine(jar_path=jar_path)

    with patch("app.engines.jar.subprocess.Popen", side_effect=FileNotFoundError("java")):
        with pytest.raises(JarEngineError, match="`java` not found"):
            engine.export_dataset("ds-1", str(tmp_path / "x.csv"))


def test_missing_jar_file_raises_descriptive_error(tmp_path):
    """When the jar itself isn't installed we expect the new guard to fire
    before any subprocess gets invoked."""

    engine = JarEngine(jar_path=str(tmp_path / "nonexistent.jar"))
    with pytest.raises(JarEngineError, match="JAR not found"):
        engine.export_dataset("ds-1", str(tmp_path / "x.csv"))


def test_health_check_fails_without_java(monkeypatch, jar_path):
    engine = JarEngine(jar_path=jar_path)
    monkeypatch.setattr("app.engines.jar.shutil.which", lambda _name: None)

    ok, msg = engine.health_check()
    assert ok is False
    assert "java" in msg.lower()


def test_health_check_succeeds_when_configured(monkeypatch, jar_path):
    engine = JarEngine(jar_path=jar_path)
    monkeypatch.setattr("app.engines.jar.shutil.which", lambda _name: "/usr/bin/java")
    ok, _msg = engine.health_check()
    assert ok is True
