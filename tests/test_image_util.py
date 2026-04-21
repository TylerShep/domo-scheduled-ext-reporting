"""Tests for the Pillow-based image post-processing."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.utils.image_util import PRESETS, edit_card_images


@pytest.fixture
def sample_png(tmp_path) -> Path:
    image = Image.new("RGB", (1200, 900), (255, 255, 255))
    path = tmp_path / "card.png"
    image.save(path)
    return path


def test_single_value_crops_to_preset(sample_png):
    edit_card_images(str(sample_png), "Single Value")
    with Image.open(sample_png) as result:
        assert result.size == (800, 400)  # crop=(0,200,800,600) -> 800x400


def test_line_resizes_to_preset(sample_png):
    edit_card_images(str(sample_png), "Line")
    with Image.open(sample_png) as result:
        assert result.size == (1000, 700)


def test_unknown_viz_type_leaves_image_unchanged(sample_png):
    original_size = Image.open(sample_png).size
    edit_card_images(str(sample_png), "Unrecognized Viz Type")
    with Image.open(sample_png) as result:
        assert result.size == original_size


def test_crop_override_takes_precedence(sample_png):
    edit_card_images(
        str(sample_png),
        "Single Value",
        crop_override=[0, 0, 100, 100],
    )
    with Image.open(sample_png) as result:
        assert result.size == (100, 100)


def test_resize_override_takes_precedence(sample_png):
    edit_card_images(
        str(sample_png),
        "Line",
        resize_override=[200, 200],
    )
    with Image.open(sample_png) as result:
        assert result.size == (200, 200)


def test_caption_increases_image_height(sample_png):
    pre = Image.open(sample_png).size
    edit_card_images(
        str(sample_png),
        "Line",
        add_caption=True,
        caption_text="Daily Revenue",
    )
    with Image.open(sample_png) as result:
        assert result.height > 700  # resize=(1000,700) + caption band
        assert result.width == 1000
        del pre


def test_rgba_input_is_flattened_to_rgb(tmp_path):
    image = Image.new("RGBA", (1200, 900), (255, 0, 0, 128))
    path = tmp_path / "rgba.png"
    image.save(path)

    edit_card_images(str(path), "Line")
    with Image.open(path) as result:
        assert result.mode == "RGB"


def test_presets_cover_common_viz_types():
    for viz_type in ["Single Value", "Multi Value", "Line", "Bar", "Pie", "Donut"]:
        assert viz_type in PRESETS
