"""Tests for filesystem helpers."""

from __future__ import annotations

import datetime

import pytest

from app.utils import project_setup_util as setup


def test_clean_filename_strips_specials_and_prepends_date():
    today = datetime.date.today().strftime("%Y%m%d")
    assert setup.clean_filename("Hello, World!") == f"{today}HelloWorld"


def test_get_output_file_path_for_png():
    path, folder = setup.get_output_file_path("card_one", ".png")
    assert path.endswith("card_one.png")
    assert folder == "temp_files"


def test_get_output_file_path_for_csv():
    path, folder = setup.get_output_file_path("metadata", ".csv")
    assert path.endswith("metadata.csv")
    assert folder == "cards_metadata"


def test_get_output_file_path_unknown_type_raises():
    with pytest.raises(ValueError, match="Unsupported file_type"):
        setup.get_output_file_path("foo", ".xls")


def test_get_domo_util_path_points_to_jar():
    path = setup.get_domo_util_path()
    assert path.endswith("domoUtil.jar")
