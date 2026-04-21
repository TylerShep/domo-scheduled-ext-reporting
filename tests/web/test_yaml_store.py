"""Direct tests for the :class:`YamlStore` filesystem layer."""

from __future__ import annotations

import pytest

from app.web.storage import YamlStore, YamlStoreError


@pytest.fixture
def store(tmp_path) -> YamlStore:
    return YamlStore(tmp_path / "reports")


_VALID = """name: demo
metadata_dataset_file_name: demo_file

cards:
  - dashboard: Dash
    card: Sales
    viz_type: Single Value

destinations:
  - type: slack
    channel_name: "#demo"
"""


def test_empty_store_list_is_empty(store):
    assert store.list_summaries() == []


def test_write_text_creates_file(store):
    store.write_text("demo.yaml", _VALID)
    assert (store.reports_dir / "demo.yaml").exists()


def test_write_rejects_traversal(store):
    with pytest.raises(YamlStoreError):
        store.write_text("../escape.yaml", _VALID)


def test_write_rejects_unknown_extension(store):
    with pytest.raises(YamlStoreError):
        store.write_text("bad.txt", _VALID)


def test_write_rejects_bad_yaml(store):
    with pytest.raises(YamlStoreError):
        store.write_text("bad.yaml", "name:\n\tfoo: 1")


def test_read_as_dict_roundtrips(store):
    store.write_text("demo.yaml", _VALID)
    data = store.read_as_dict("demo.yaml")
    assert data["name"] == "demo"
    assert len(data["cards"]) == 1


def test_delete_removes_file(store):
    store.write_text("demo.yaml", _VALID)
    store.delete("demo.yaml")
    assert not (store.reports_dir / "demo.yaml").exists()


def test_delete_missing_raises(store):
    with pytest.raises(YamlStoreError):
        store.delete("nope.yaml")


def test_list_summaries_counts_children(store):
    store.write_text("demo.yaml", _VALID)
    summaries = store.list_summaries()
    assert len(summaries) == 1
    s = summaries[0]
    assert s.name == "demo"
    assert s.cards_count == 1
    assert s.destinations_count == 1
    assert s.datasets_count == 0


def test_validate_text_returns_parsed(store):
    data = store.validate_text(_VALID)
    assert data["name"] == "demo"


def test_validate_text_raises_on_schema_error(store):
    with pytest.raises(YamlStoreError):
        store.validate_text("name: foo\ndestinations: []")


def test_exists_returns_false_for_unsafe_name(store):
    # _resolve raises for traversal; exists() should swallow it.
    assert store.exists("../escape.yaml") is False


def test_read_text_missing_raises(store):
    with pytest.raises(YamlStoreError, match="not found"):
        store.read_text("ghost.yaml")


def test_write_text_rejects_when_overwrite_false(store):
    store.write_text("demo.yaml", _VALID)
    with pytest.raises(YamlStoreError, match="already exists"):
        store.write_text("demo.yaml", _VALID, overwrite=False)


def test_write_dict_serializes_with_ruamel(store):
    store.write_dict(
        "demo.yaml",
        {
            "name": "demo",
            "metadata_dataset_file_name": "demo_file",
            "cards": [{"dashboard": "D", "card": "C", "viz_type": "Single Value"}],
            "destinations": [{"type": "slack", "channel_name": "#demo"}],
        },
    )
    assert "name: demo" in store.read_text("demo.yaml")


def test_list_summaries_skips_non_yaml_files(store):
    store.write_text("demo.yaml", _VALID)
    (store.reports_dir / "notes.txt").write_text("not yaml", encoding="utf-8")
    summaries = store.list_summaries()
    assert [s.filename for s in summaries] == ["demo.yaml"]


def test_list_summaries_tolerates_corrupt_yaml(store):
    store.write_text("demo.yaml", _VALID)
    (store.reports_dir / "broken.yaml").write_text("name:\n\tbad:  1", encoding="utf-8")
    summaries = store.list_summaries()
    # broken file is still listed, just with zero counts.
    assert any(s.filename == "broken.yaml" for s in summaries)


def test_validate_text_rejects_non_mapping_root(store):
    with pytest.raises(YamlStoreError, match="expected a YAML mapping"):
        store.validate_text("- just\n- a list\n")


def test_reports_dir_is_created_on_init(tmp_path):
    target = tmp_path / "deeply" / "nested" / "reports"
    YamlStore(target)
    assert target.is_dir()


def test_reports_dir_not_a_directory_raises(tmp_path):
    file = tmp_path / "not-a-dir"
    file.write_text("hello", encoding="utf-8")
    with pytest.raises(YamlStoreError, match="isn't a directory"):
        YamlStore(file)
