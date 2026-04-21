"""Smoke tests for the :mod:`app.utils.domo_util` backward-compatibility shim."""

from __future__ import annotations

import pytest

from app.utils.domo_util import DomoCliError, query_card_metadata


def _write_metadata_csv(path, rows):
    header = "CardID,CardName,CardURL,PageID,PageTItle\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        for row in rows:
            fh.write(",".join(str(v) for v in row) + "\n")


def test_query_card_metadata_matches_row(tmp_path):
    csv_path = tmp_path / "meta.csv"
    _write_metadata_csv(
        csv_path,
        [
            (101, "Daily KPIs", "https://example.domo.com/cards/101", 9, "Sales"),
            (102, "Pipeline", "https://example.domo.com/cards/102", 9, "Sales"),
        ],
    )

    card_id, card_url, page_name = query_card_metadata(
        ["Sales", "Daily KPIs", "bar"], str(csv_path)
    )
    assert card_id == 101
    assert card_url == "https://example.domo.com/cards/101"
    assert page_name == "Sales"


def test_query_card_metadata_no_match_raises(tmp_path):
    csv_path = tmp_path / "meta.csv"
    _write_metadata_csv(
        csv_path,
        [(1, "Other", "url", 2, "Other Page")],
    )
    with pytest.raises(DomoCliError, match="No metadata row matched"):
        query_card_metadata(["Sales", "Daily KPIs", "bar"], str(csv_path))


def test_query_card_metadata_missing_columns_raises(tmp_path):
    csv_path = tmp_path / "meta.csv"
    csv_path.write_text("CardID,CardName\n1,Daily KPIs\n", encoding="utf-8")
    with pytest.raises(DomoCliError, match="missing required columns"):
        query_card_metadata(["Sales", "Daily KPIs"], str(csv_path))
