"""Filesystem helpers for the report run lifecycle.

We use two scratch folders under ``app/`` for each report run:
    * ``cards_metadata/`` -- holds the exported metadata CSV
    * ``temp_files/``     -- holds generated card PNGs

Both are wiped at the end of every run via :func:`remove_temp_folders`.
"""

from __future__ import annotations

import datetime
import os
import re
import shutil
from pathlib import Path

# Folders we manage inside ``app/``.
_TEMP_FOLDERS: tuple[str, ...] = ("temp_files", "cards_metadata")
_FILETYPE_TO_FOLDER: dict[str, str] = {".png": "temp_files", ".csv": "cards_metadata"}


def _app_dir() -> Path:
    """Return the absolute path to the ``app/`` package directory."""

    return Path(__file__).resolve().parent.parent


def create_temp_folder(folder: str) -> str:
    """Create ``app/<folder>`` if missing and return its absolute path."""

    path = _app_dir() / folder
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def clean_filename(filename: str) -> str:
    """Strip non-alphanumeric chars and prefix with today's date (YYYYMMDD)."""

    cleaned = re.sub(r"[^a-zA-Z0-9]", "", filename)
    today = datetime.date.today().strftime("%Y%m%d")
    return f"{today}{cleaned}"


def find_file_path(file_name: str, search_path: str) -> str | None:
    """Walk ``search_path`` and return the first match for ``file_name``."""

    for root, _dirs, files in os.walk(search_path):
        if file_name in files:
            return os.path.join(root, file_name)
    return None


def get_domo_util_path() -> str:
    """Return the absolute path of the bundled ``domoUtil.jar``."""

    return str(Path(__file__).resolve().parent / "domoUtil.jar")


def get_output_file_path(file_name: str, file_type: str) -> tuple[str, str]:
    """Build an output path under the appropriate scratch folder.

    Returns a ``(absolute_path, folder_name)`` tuple. ``folder_name`` is the
    name of the scratch folder that was selected based on ``file_type``.
    """

    folder = _FILETYPE_TO_FOLDER.get(file_type)
    if folder is None:
        raise ValueError(
            f"Unsupported file_type {file_type!r}; expected one of "
            f"{sorted(_FILETYPE_TO_FOLDER.keys())}"
        )

    create_temp_folder(folder)
    output_path = _app_dir() / folder / f"{file_name}{file_type}"
    return str(output_path), folder


def remove_temp_folders() -> None:
    """Remove every scratch folder we created during a run."""

    for folder in _TEMP_FOLDERS:
        path = _app_dir() / folder
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(f"Error removing folder {folder}: {exc}")
    print("Project cleanup complete.")
