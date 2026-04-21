"""Pillow-based post-processing for Domo card images.

The Domo CLI exports images at a fixed canvas size with whitespace padding
that varies by visualization type. This module crops/resizes those raw
exports into a presentation-ready PNG that looks good in Slack and Teams.

Each visualization type maps to a :class:`ImageEditPreset`. Per-card YAML
overrides (``crop`` / ``resize`` / ``add_caption``) take precedence over the
preset defaults.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ImageEditPreset:
    """Default crop+resize behavior for one Domo viz type.

    Attributes:
        crop: ``(left, upper, right, lower)`` -- box to crop. ``None`` skips.
        resize: ``(width, height)`` -- target size after crop. ``None`` skips.
    """

    crop: tuple[int, int, int, int] | None = None
    resize: tuple[int, int] | None = None


# Preset mapping. Easy to extend -- add a new entry and it Just Works.
PRESETS: Mapping[str, ImageEditPreset] = {
    "Single Value": ImageEditPreset(crop=(0, 200, 800, 600)),
    "Multi Value": ImageEditPreset(crop=(0, 0, 800, 175)),
    "Line": ImageEditPreset(resize=(1000, 700)),
    "Bar": ImageEditPreset(resize=(1000, 700)),
    "Stacked Bar": ImageEditPreset(resize=(1000, 700)),
    "Horizontal Bar": ImageEditPreset(resize=(1000, 700)),
    "Pie": ImageEditPreset(crop=(50, 50, 850, 750), resize=(800, 700)),
    "Donut": ImageEditPreset(crop=(50, 50, 850, 750), resize=(800, 700)),
    "Heatmap": ImageEditPreset(resize=(1100, 700)),
    "Map": ImageEditPreset(resize=(1100, 800)),
    "Table": ImageEditPreset(resize=(1100, 700)),
    "Gauge": ImageEditPreset(crop=(50, 100, 850, 700), resize=(800, 600)),
    "Area": ImageEditPreset(resize=(1000, 700)),
    "Scatter": ImageEditPreset(resize=(1000, 700)),
}


def edit_card_images(
    image_path: str,
    card_viz_type: str,
    crop_override: Sequence[int] | None = None,
    resize_override: Sequence[int] | None = None,
    add_caption: bool = False,
    caption_text: str | None = None,
) -> None:
    """Edit a card image in place.

    Args:
        image_path: Absolute path to the PNG written by the Domo CLI.
        card_viz_type: Domo viz type label (e.g. ``"Single Value"``).
        crop_override: Optional ``[left, upper, right, lower]`` to override
            the preset's crop.
        resize_override: Optional ``[width, height]`` to override the preset's
            resize.
        add_caption: If True, draw ``caption_text`` (or the card name) along
            the bottom of the image.
        caption_text: Caption to draw when ``add_caption`` is True.
    """

    preset = PRESETS.get(card_viz_type, ImageEditPreset())
    crop = tuple(crop_override) if crop_override else preset.crop
    resize = tuple(resize_override) if resize_override else preset.resize

    if not crop and not resize and not add_caption:
        logger.info(
            "No image edits configured for viz_type=%s; using original PNG.",
            card_viz_type,
        )
        return

    with Image.open(image_path) as image:
        # Flatten transparency to white so Teams previews render correctly.
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1] if image.mode != "P" else None)
            image = background

        if crop:
            image = image.crop(tuple(crop))
            logger.debug("Cropped image to %s", crop)

        if resize:
            image = image.resize(tuple(resize), Image.Resampling.LANCZOS)
            logger.debug("Resized image to %s", resize)

        if add_caption:
            image = _draw_caption(image, caption_text or "")

        image.save(image_path, format="PNG", optimize=True)


def _draw_caption(image: Image.Image, text: str) -> Image.Image:
    """Render ``text`` plus today's date along the bottom of ``image``."""

    if not text:
        return image

    margin = 12
    band_height = 36
    canvas = Image.new("RGB", (image.width, image.height + band_height), (255, 255, 255))
    canvas.paste(image, (0, 0))

    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 14)
    except OSError:
        font = ImageFont.load_default()

    today = datetime.date.today().strftime("%Y-%m-%d")
    caption = f"{text}  -  {today}"
    draw.text(
        (margin, image.height + (band_height - 14) // 2), caption, fill=(80, 80, 80), font=font
    )
    return canvas
