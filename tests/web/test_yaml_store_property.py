"""Property tests for :class:`YamlStore` filename safety.

For any text ``YamlStore._resolve`` accepts, the resolved path must stay
within the reports directory. For any text it rejects, it must raise the
documented error and never create the file.
"""

from __future__ import annotations

import string
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.web.storage import YamlStore, YamlStoreError

# The fixture builds one YamlStore per test; calls to `_resolve` don't mutate
# state so sharing it across hypothesis shrinks is safe and saves a lot of
# filesystem churn.
_SETTINGS = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])


_SAFE_CHARS = string.ascii_letters + string.digits + "._-"


@pytest.fixture
def store(tmp_path_factory) -> YamlStore:
    return YamlStore(tmp_path_factory.mktemp("reports"))


@_SETTINGS
@given(
    stem=st.text(alphabet=_SAFE_CHARS, min_size=1, max_size=20),
    suffix=st.sampled_from([".yaml", ".yml"]),
)
def test_safe_names_resolve_inside_root(store, stem, suffix):
    filename = f"{stem}{suffix}"
    path = store._resolve(filename)
    assert path.is_absolute()
    assert Path(path).parent == store.reports_dir


@_SETTINGS
@given(stem=st.text(alphabet=_SAFE_CHARS, min_size=1, max_size=20))
def test_names_without_yaml_extension_rejected(store, stem):
    filename = f"{stem}.txt"
    with pytest.raises(YamlStoreError):
        store._resolve(filename)


@_SETTINGS
@given(
    malicious=st.sampled_from(
        [
            "../escape.yaml",
            "..\\escape.yaml",
            "/abs/escape.yaml",
            "deep/nested/escape.yaml",
            "sub/../../escape.yaml",
            "foo bar.yaml",  # contains space -- disallowed
            "foo/bar.yaml",
            "",
            ".",
            "..",
        ]
    )
)
def test_unsafe_names_rejected(store, malicious):
    with pytest.raises(YamlStoreError):
        store._resolve(malicious)
