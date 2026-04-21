"""Tests for app.engines.jar_downloader."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.engines.jar_downloader import (
    JarDownloadError,
    JarVersion,
    default_install_path,
    describe_version,
    download_jar,
    jar_is_installed,
    sha256_file,
    verify_jar,
)

# ---- JarVersion.load ----


def test_jar_version_loads_from_default_file():
    ver = JarVersion.load()
    assert ver.filename == "domoUtil.jar"
    assert ver.version
    assert len(ver.sha256) == 64
    assert ver.url.startswith("http")


def test_jar_version_load_missing_file(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(JarDownloadError, match="missing"):
        JarVersion.load(missing)


def test_jar_version_load_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all")
    with pytest.raises(JarDownloadError, match="not valid JSON"):
        JarVersion.load(bad)


def test_jar_version_load_missing_keys(tmp_path):
    incomplete = tmp_path / "inc.json"
    incomplete.write_text(json.dumps({"version": "1", "filename": "x"}))
    with pytest.raises(JarDownloadError, match="missing required keys"):
        JarVersion.load(incomplete)


# ---- hashing helpers ----


def test_sha256_file_matches_known_hash(tmp_path):
    payload = b"hello\n"
    target = tmp_path / "x.bin"
    target.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    assert sha256_file(target) == expected


def test_verify_jar_ok(tmp_path):
    target = tmp_path / "x.bin"
    payload = b"payload"
    target.write_bytes(payload)
    assert verify_jar(target, hashlib.sha256(payload).hexdigest())


def test_verify_jar_mismatch(tmp_path):
    target = tmp_path / "x.bin"
    target.write_bytes(b"payload")
    assert not verify_jar(target, "0" * 64)


def test_verify_jar_is_case_insensitive(tmp_path):
    target = tmp_path / "x.bin"
    payload = b"payload"
    target.write_bytes(payload)
    upper = hashlib.sha256(payload).hexdigest().upper()
    assert verify_jar(target, upper)


# ---- download_jar happy path ----


def _make_version(tmp_path: Path, payload: bytes, url: str) -> JarVersion:
    return JarVersion(
        version="9.9.9",
        filename="test.jar",
        url=url,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_download_jar_writes_file_and_verifies(tmp_path):
    payload = b"fake jar bytes"
    version = _make_version(tmp_path, payload, "https://fake/url")
    install = tmp_path / "install" / "domoUtil.jar"

    def fake_fetch(url, dest_path):
        assert url == "https://fake/url"
        dest_path.write_bytes(payload)

    result = download_jar(
        install_path=install,
        version=version,
        fetch=fake_fetch,
    )
    assert result == install
    assert install.read_bytes() == payload
    assert jar_is_installed(install)


def test_download_jar_respects_url_override(tmp_path):
    payload = b"mirror bytes"
    version = _make_version(tmp_path, payload, "https://original/url")
    install = tmp_path / "jar"

    def fake_fetch(url, dest_path):
        assert url == "https://mirror/url"
        dest_path.write_bytes(payload)

    download_jar(
        install_path=install,
        version=version,
        url_override="https://mirror/url",
        fetch=fake_fetch,
    )


def test_download_jar_env_url_override(tmp_path, monkeypatch):
    payload = b"bytes"
    version = _make_version(tmp_path, payload, "https://baked/url")
    monkeypatch.setenv("DOMO_JAR_URL", "https://env/url")
    install = tmp_path / "jar"

    urls_seen: list[str] = []

    def fake_fetch(url, dest_path):
        urls_seen.append(url)
        dest_path.write_bytes(payload)

    download_jar(install_path=install, version=version, fetch=fake_fetch)
    assert urls_seen == ["https://env/url"]


def test_download_jar_rejects_tampered_bytes(tmp_path):
    payload = b"the real bytes"
    tampered = b"tampered!"
    version = _make_version(tmp_path, payload, "https://fake/url")
    install = tmp_path / "jar"

    def fake_fetch(url, dest_path):
        dest_path.write_bytes(tampered)

    with pytest.raises(JarDownloadError, match="hash mismatch"):
        download_jar(install_path=install, version=version, fetch=fake_fetch)

    assert not install.exists()


def test_download_jar_skips_when_already_verified(tmp_path):
    payload = b"real bytes"
    version = _make_version(tmp_path, payload, "https://fake/url")
    install = tmp_path / "domoUtil.jar"
    install.write_bytes(payload)

    def fake_fetch(url, dest_path):  # should not be called
        raise AssertionError("fetch should not fire when hash already matches")

    result = download_jar(install_path=install, version=version, fetch=fake_fetch)
    assert result == install


def test_download_jar_force_redownloads_even_if_present(tmp_path):
    payload = b"bytes"
    version = _make_version(tmp_path, payload, "https://fake/url")
    install = tmp_path / "domoUtil.jar"
    install.write_bytes(payload)

    fetches = 0

    def fake_fetch(url, dest_path):
        nonlocal fetches
        fetches += 1
        dest_path.write_bytes(payload)

    download_jar(install_path=install, version=version, fetch=fake_fetch, force=True)
    assert fetches == 1


def test_download_jar_raises_when_hash_wrong_after_existing_install_is_bad(tmp_path):
    """If the on-disk JAR doesn't match, we re-download; if that also
    fails the hash check, raise."""

    real_payload = b"real bytes"
    bad_payload = b"different bytes"
    version = _make_version(tmp_path, real_payload, "https://fake/url")

    install = tmp_path / "jar"
    install.write_bytes(b"wrong bytes")  # on-disk version is bad

    def fake_fetch(url, dest_path):
        dest_path.write_bytes(bad_payload)  # network version is also bad

    with pytest.raises(JarDownloadError, match="hash mismatch"):
        download_jar(install_path=install, version=version, fetch=fake_fetch)


def test_download_jar_wraps_network_errors(tmp_path):
    version = _make_version(tmp_path, b"anything", "https://fake/url")
    install = tmp_path / "jar"

    def fake_fetch(url, dest_path):
        raise ConnectionError("dns fail")

    with pytest.raises(JarDownloadError, match="Failed to download"):
        download_jar(install_path=install, version=version, fetch=fake_fetch)


# ---- utility wrappers ----


def test_jar_is_installed_false_for_missing_file(tmp_path):
    assert not jar_is_installed(tmp_path / "nope.jar")


def test_jar_is_installed_false_for_empty_file(tmp_path):
    empty = tmp_path / "empty.jar"
    empty.write_bytes(b"")
    assert not jar_is_installed(empty)


def test_jar_is_installed_true_for_present_file(tmp_path):
    target = tmp_path / "domoUtil.jar"
    target.write_bytes(b"some bytes")
    assert jar_is_installed(target)


def test_default_install_path_within_app_utils():
    assert default_install_path().name == "domoUtil.jar"
    assert default_install_path().parent.name == "utils"


def test_describe_version_returns_string():
    desc = describe_version()
    assert isinstance(desc, str)
    assert desc  # non-empty


# ---- JarEngine fails fast when JAR is missing ----


def test_jar_engine_raises_if_jar_missing(monkeypatch, tmp_path):
    from app.engines.jar import JarEngine, JarEngineError

    monkeypatch.setenv("DOMO_INSTANCE", "x.domo.com")
    monkeypatch.setenv("DOMO_TOKEN", "y")

    engine = JarEngine(jar_path=str(tmp_path / "missing.jar"))
    with pytest.raises(JarEngineError, match="JAR not found"):
        engine._run_user_commands("export-data -i ds -f /tmp/x.csv\n")


# ---- CLI flag wiring ----


def test_main_download_jar_calls_downloader(monkeypatch, tmp_path):
    import main as main_module

    monkeypatch.setattr("sys.argv", ["domo-report", "--download-jar"])

    calls: dict[str, int] = {"download": 0}

    def fake_download(*args, **kwargs):
        calls["download"] += 1
        return tmp_path / "domoUtil.jar"

    monkeypatch.setattr(
        "app.engines.jar_downloader.download_jar",
        fake_download,
    )

    exit_code = main_module.main()
    assert exit_code == 0
    assert calls["download"] == 1


def test_main_download_jar_returns_one_on_error(monkeypatch):
    import main as main_module

    monkeypatch.setattr("sys.argv", ["domo-report", "--download-jar"])

    def fake_download(*args, **kwargs):
        raise JarDownloadError("boom")

    monkeypatch.setattr(
        "app.engines.jar_downloader.download_jar",
        fake_download,
    )

    exit_code = main_module.main()
    assert exit_code == 1
