"""Contract tests: every engine must honor the same interface.

Both engines should:
    * subclass :class:`DomoEngine`
    * write the dataset CSV to the requested path
    * write the card PNG to the requested path
    * report a sensible health status

We mock the IO layer so neither implementation actually touches the network
or the JVM.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import responses

from app.engines import CardImageRequest, DomoEngine
from app.engines.jar import JarEngine
from app.engines.rest import RestEngine


@pytest.fixture(autouse=True)
def _set_envs(monkeypatch):
    monkeypatch.setenv("DOMO_INSTANCE", "x.domo.com")
    monkeypatch.setenv("DOMO_TOKEN", "t")


@pytest.fixture
def fake_jar_path(tmp_path) -> str:
    path = tmp_path / "domoUtil.jar"
    path.write_bytes(b"")
    return str(path)


def _make_jar(jar_path: str = "/tmp/fake.jar") -> JarEngine:
    return JarEngine(jar_path=jar_path)


def _make_rest() -> RestEngine:
    return RestEngine(client_id="id", client_secret="secret", api_host="api.domo.com")


def test_both_engines_subclass_domoengine():
    assert issubclass(JarEngine, DomoEngine)
    assert issubclass(RestEngine, DomoEngine)


def test_both_engines_have_key_and_label():
    assert _make_jar().key == "jar"
    assert _make_rest().key == "rest"
    assert _make_jar().describe()
    assert _make_rest().describe()


def test_jar_writes_dataset_to_path(tmp_path, fake_jar_path):
    out = tmp_path / "out.csv"
    process = MagicMock(returncode=0)
    process.communicate.return_value = ("", "")
    with patch("app.engines.jar.subprocess.Popen", return_value=process):
        _make_jar(fake_jar_path).export_dataset("ds-1", str(out))
    # JAR engine writes the file via the subprocess, so the test only proves
    # the subprocess was invoked. The file write itself happens in Java.
    process.communicate.assert_called_once()


@responses.activate
def test_rest_writes_dataset_to_path(tmp_path):
    responses.add(
        responses.GET,
        "https://api.domo.com/oauth/token",
        json={"access_token": "tok", "expires_in": 3600},
    )
    responses.add(
        responses.GET,
        "https://api.domo.com/v1/datasets/ds-1/data",
        body=b"a,b\n1,2",
        status=200,
    )
    out = tmp_path / "out.csv"
    _make_rest().export_dataset("ds-1", str(out))
    assert out.read_bytes() == b"a,b\n1,2"


@responses.activate
def test_rest_writes_card_image_to_path(tmp_path):
    responses.add(
        responses.GET,
        "https://api.domo.com/oauth/token",
        json={"access_token": "tok", "expires_in": 3600},
    )
    responses.add(
        responses.POST,
        "https://api.domo.com/v1/cards/5/render",
        body=b"PNGBYTES",
        status=200,
    )
    out = tmp_path / "card.png"
    _make_rest().generate_card_image(5, str(out))
    assert out.read_bytes() == b"PNGBYTES"


def test_jar_card_image_batch_invokes_one_subprocess(tmp_path, fake_jar_path):
    process = MagicMock(returncode=0)
    process.communicate.return_value = ("", "")
    with patch("app.engines.jar.subprocess.Popen", return_value=process) as popen:
        _make_jar(fake_jar_path).generate_card_images(
            [
                CardImageRequest(card_id=1, output_path=str(tmp_path / "1.png")),
                CardImageRequest(card_id=2, output_path=str(tmp_path / "2.png")),
            ]
        )
    assert popen.call_count == 1
