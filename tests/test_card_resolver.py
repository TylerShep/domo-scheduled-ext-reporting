"""Tests for cards_query auto-discovery and TTL cache."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.configuration.card_resolver import (
    CardResolverError,
    _cache_key,
    clear_discovery_cache,
    resolve_cards_query,
    resolved_cards_to_yaml_rows,
)
from app.configuration.report_loader import (
    ReportConfigError,
    ReportSpec,
    YamlReport,
    parse_report_file,
)
from app.engines import CardSummary


def _fake_engine(summaries: Sequence[CardSummary]) -> MagicMock:
    engine = MagicMock()
    engine.list_cards.return_value = list(summaries)
    engine.describe.return_value = "Fake engine"
    return engine


def _summary(
    card_id: int, name: str, page: str = "P", tags: list[str] | None = None
) -> CardSummary:
    return CardSummary(
        card_id=card_id,
        card_name=name,
        page_id=page,
        page_name=page,
        card_url=f"https://domo.example.com/card/{card_id}",
        tags=list(tags or []),
    )


# ---- happy path ----


def test_resolve_cards_query_happy_path(tmp_path):
    engine = _fake_engine(
        [
            _summary(1, "Revenue", "Sales", tags=["daily"]),
            _summary(2, "Pipeline", "Sales", tags=["daily", "exec"]),
        ]
    )
    cache = tmp_path / "cache.json"
    resolved = resolve_cards_query(
        {"page": "Sales", "tags": ["daily"], "viz_type": "Single Value"},
        engine=engine,
        cache_path=cache,
    )
    assert [r.card for r in resolved] == ["Revenue", "Pipeline"]
    assert all(r.viz_type == "Single Value" for r in resolved)
    assert all(r.card_id in {1, 2} for r in resolved)
    engine.list_cards.assert_called_once()


def test_resolved_cards_to_yaml_rows_contains_dashboard_and_card(tmp_path):
    engine = _fake_engine([_summary(99, "Orders", "Ops", tags=["tag"])])
    resolved = resolve_cards_query(
        {"page": "Ops", "viz_type": "Bar"},
        engine=engine,
        cache_path=tmp_path / "c.json",
    )
    rows = resolved_cards_to_yaml_rows(resolved)
    assert rows == [
        {
            "dashboard": "Ops",
            "card": "Orders",
            "viz_type": "Bar",
            "card_id": 99,
            "card_url": "https://domo.example.com/card/99",
            "tags": ["tag"],
        }
    ]


def test_limit_truncates_results(tmp_path):
    engine = _fake_engine([_summary(i, f"C{i}") for i in range(10)])
    resolved = resolve_cards_query(
        {"limit": 3},
        engine=engine,
        cache_path=tmp_path / "c.json",
    )
    assert len(resolved) == 3


# ---- caching ----


def test_cache_hit_skips_engine(tmp_path):
    cache = tmp_path / "c.json"
    engine_first = _fake_engine([_summary(1, "A")])
    resolve_cards_query({"page": "P"}, engine=engine_first, cache_path=cache, ttl_seconds=60)

    engine_second = _fake_engine([_summary(99, "Z")])
    resolved = resolve_cards_query(
        {"page": "P"}, engine=engine_second, cache_path=cache, ttl_seconds=60
    )

    engine_second.list_cards.assert_not_called()
    assert [r.card for r in resolved] == ["A"]


def test_cache_miss_when_expired(tmp_path):
    cache = tmp_path / "c.json"
    engine_first = _fake_engine([_summary(1, "A")])
    resolve_cards_query(
        {"page": "P"},
        engine=engine_first,
        cache_path=cache,
        ttl_seconds=1,
    )

    # Backdate the cache entry.
    payload = json.loads(cache.read_text())
    key = _cache_key({"page": "P"})
    payload[key]["written_at"] = time.time() - 120
    cache.write_text(json.dumps(payload))

    engine_second = _fake_engine([_summary(2, "B")])
    resolved = resolve_cards_query(
        {"page": "P"},
        engine=engine_second,
        cache_path=cache,
        ttl_seconds=1,
    )
    engine_second.list_cards.assert_called_once()
    assert [r.card for r in resolved] == ["B"]


def test_force_refresh_bypasses_cache(tmp_path):
    cache = tmp_path / "c.json"
    engine_first = _fake_engine([_summary(1, "A")])
    resolve_cards_query({"page": "P"}, engine=engine_first, cache_path=cache)

    engine_second = _fake_engine([_summary(2, "B")])
    resolve_cards_query(
        {"page": "P"},
        engine=engine_second,
        cache_path=cache,
        force_refresh=True,
    )
    engine_second.list_cards.assert_called_once()


def test_corrupt_cache_falls_back_to_engine(tmp_path):
    cache = tmp_path / "c.json"
    cache.write_text("not valid JSON {{{")
    engine = _fake_engine([_summary(1, "A")])
    resolved = resolve_cards_query({"page": "P"}, engine=engine, cache_path=cache)
    assert [r.card for r in resolved] == ["A"]
    # Cache was rewritten.
    payload = json.loads(cache.read_text())
    assert _cache_key({"page": "P"}) in payload


def test_clear_discovery_cache_removes_file(tmp_path):
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps({"foo": "bar"}))
    assert cache.exists()
    clear_discovery_cache(cache)
    assert not cache.exists()


def test_clear_discovery_cache_missing_file_is_noop(tmp_path):
    cache = tmp_path / "nope.json"
    clear_discovery_cache(cache)
    assert not cache.exists()


# ---- validation ----


def test_unknown_query_key_raises(tmp_path):
    engine = _fake_engine([])
    with pytest.raises(CardResolverError, match="Unknown cards_query keys"):
        resolve_cards_query(
            {"bogus": 1},
            engine=engine,
            cache_path=tmp_path / "c.json",
        )


def test_tags_must_be_list_of_strings(tmp_path):
    engine = _fake_engine([])
    with pytest.raises(CardResolverError, match="tags"):
        resolve_cards_query(
            {"tags": "daily"},
            engine=engine,
            cache_path=tmp_path / "c.json",
        )


def test_exclude_tags_must_be_list_of_strings(tmp_path):
    engine = _fake_engine([])
    with pytest.raises(CardResolverError, match="exclude_tags"):
        resolve_cards_query(
            {"exclude_tags": ["ok", 7]},
            engine=engine,
            cache_path=tmp_path / "c.json",
        )


def test_limit_must_be_int(tmp_path):
    engine = _fake_engine([])
    with pytest.raises(CardResolverError, match="limit"):
        resolve_cards_query(
            {"limit": "five"},
            engine=engine,
            cache_path=tmp_path / "c.json",
        )


def test_engine_without_list_cards_raises(tmp_path):
    engine = MagicMock()
    engine.describe.return_value = "stub"
    engine.list_cards.side_effect = NotImplementedError("nope")
    with pytest.raises(CardResolverError, match="does not support card discovery"):
        resolve_cards_query({"page": "P"}, engine=engine, cache_path=tmp_path / "c.json")


# ---- YAML loader integration ----


def _write_yaml(tmp_path: Path, name: str, payload: dict) -> Path:
    import yaml

    reports_dir = tmp_path / "config" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    file_path = reports_dir / f"{name}.yaml"
    file_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return file_path


def test_yaml_accepts_cards_query_alone(tmp_path):
    payload = {
        "name": "auto",
        "metadata_dataset_file_name": "meta",
        "cards_query": {"page": "Sales", "tags": ["daily"], "viz_type": "SV"},
        "destinations": [{"type": "slack", "channel_name": "x"}],
    }
    file_path = _write_yaml(tmp_path, "auto", payload)
    spec = parse_report_file(file_path)
    assert spec.cards == []
    assert spec.cards_query == {"page": "Sales", "tags": ["daily"], "viz_type": "SV"}


def test_yaml_rejects_unknown_cards_query_key(tmp_path):
    payload = {
        "name": "bad",
        "metadata_dataset_file_name": "meta",
        "cards_query": {"xxx": 1},
        "destinations": [{"type": "slack", "channel_name": "x"}],
    }
    file_path = _write_yaml(tmp_path, "bad", payload)
    with pytest.raises(ReportConfigError, match="cards_query has unknown keys"):
        parse_report_file(file_path)


def test_yaml_report_merges_explicit_and_queried_cards(tmp_path, monkeypatch):
    payload = {
        "name": "merge",
        "metadata_dataset_file_name": "meta",
        "cards": [{"dashboard": "D", "card": "Manual", "viz_type": "Bar"}],
        "cards_query": {"page": "Auto", "viz_type": "Single Value"},
        "destinations": [{"type": "slack", "channel_name": "x"}],
    }
    file_path = _write_yaml(tmp_path, "merge", payload)
    spec = parse_report_file(file_path)
    report = YamlReport(spec)

    fake = _fake_engine([_summary(1, "AutoCard", "Auto")])
    cache = tmp_path / "c.json"

    import app.configuration.card_resolver as resolver_module

    monkeypatch.setattr(resolver_module, "_resolve_cache_path", lambda: cache)
    monkeypatch.setattr(resolver_module, "get_engine", lambda: fake)

    rows = report.list_of_cards()
    assert rows[0][:3] == ["D", "Manual", "Bar"]
    assert rows[1][:3] == ["Auto", "AutoCard", "Single Value"]


# ---- spec default ----


def test_report_spec_cards_query_defaults_to_none():
    spec = ReportSpec(
        name="n",
        metadata_dataset_file_name="m",
        cards=[],
        destinations=[],
    )
    assert spec.cards_query is None
