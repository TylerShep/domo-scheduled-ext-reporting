"""File-backed CRUD for YAML reports with comment/order preservation.

The web UI writes back files that a developer might also edit by hand. We use
:mod:`ruamel.yaml` round-trip mode so YAML comments and key ordering survive
writes from the UI.

The :class:`YamlStore` wraps an arbitrary directory (default is
``config/reports``) and exposes the CRUD surface the HTTP layer needs:

    * :meth:`list_summaries`
    * :meth:`read_text` / :meth:`write_text`
    * :meth:`read_as_dict` / :meth:`write_dict`
    * :meth:`delete`
    * :meth:`validate_text`

Every mutating method resolves the filename safely (no path traversal) and
writes atomically.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.parser import ParserError
    from ruamel.yaml.scanner import ScannerError
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Install the [web] extras to use the YAML store "
        "(pip install 'domo-scheduled-ext-reporting[web]')."
    ) from exc


class YamlStoreError(Exception):
    """Raised when a YAML file operation fails."""


_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class ReportSummary:
    """Tiny DTO for list views."""

    filename: str
    name: str
    destinations_count: int
    cards_count: int
    datasets_count: int
    schedule: str | None
    mtime: float
    size: int


def _new_yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 120
    return yaml


class YamlStore:
    """CRUD surface over ``<reports_dir>/*.yaml``."""

    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = Path(reports_dir).expanduser().resolve()
        if not self.reports_dir.exists():
            self.reports_dir.mkdir(parents=True, exist_ok=True)
        elif not self.reports_dir.is_dir():
            raise YamlStoreError(
                f"reports directory {self.reports_dir} exists but isn't a directory"
            )

    # ------------------------------------------------------------------ path
    def _resolve(self, filename: str) -> Path:
        if not filename or not _SAFE_NAME.match(filename):
            raise YamlStoreError(
                "filename must only contain letters, digits, dot, dash, or underscore"
            )
        if not filename.endswith((".yaml", ".yml")):
            raise YamlStoreError("filename must end with .yaml or .yml")
        path = (self.reports_dir / filename).resolve()
        # path traversal guard
        try:
            path.relative_to(self.reports_dir)
        except ValueError as exc:
            raise YamlStoreError("path traversal is not allowed") from exc
        return path

    # ----------------------------------------------------------------- list
    def list_summaries(self) -> list[ReportSummary]:
        """Return a sorted-by-name summary for each report in the directory."""

        out: list[ReportSummary] = []
        yaml = _new_yaml()
        for path in sorted(self.reports_dir.iterdir()):
            if path.suffix.lower() not in {".yaml", ".yml"}:
                continue
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = yaml.load(fh) or {}
            except (ScannerError, ParserError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            cards = data.get("cards") or []
            datasets = data.get("datasets") or []
            destinations = data.get("destinations") or []
            out.append(
                ReportSummary(
                    filename=path.name,
                    name=str(data.get("name") or path.stem),
                    destinations_count=len(destinations) if isinstance(destinations, list) else 0,
                    cards_count=len(cards) if isinstance(cards, list) else 0,
                    datasets_count=len(datasets) if isinstance(datasets, list) else 0,
                    schedule=str(data.get("schedule")) if data.get("schedule") else None,
                    mtime=path.stat().st_mtime,
                    size=path.stat().st_size,
                )
            )
        return out

    # ------------------------------------------------------------------- io
    def exists(self, filename: str) -> bool:
        try:
            return self._resolve(filename).exists()
        except YamlStoreError:
            return False

    def read_text(self, filename: str) -> str:
        path = self._resolve(filename)
        if not path.exists():
            raise YamlStoreError(f"{filename} not found")
        return path.read_text(encoding="utf-8")

    def write_text(self, filename: str, text: str, *, overwrite: bool = True) -> Path:
        path = self._resolve(filename)
        if path.exists() and not overwrite:
            raise YamlStoreError(f"{filename} already exists")
        self._validate_text_or_raise(text)
        _atomic_write(path, text)
        return path

    def read_as_dict(self, filename: str) -> dict[str, Any]:
        text = self.read_text(filename)
        try:
            data = _new_yaml().load(text) or {}
        except (ScannerError, ParserError) as exc:
            raise YamlStoreError(f"{filename} is not valid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise YamlStoreError(f"{filename} must be a YAML mapping")
        return data

    def write_dict(self, filename: str, data: dict[str, Any], *, overwrite: bool = True) -> Path:
        buf = io.StringIO()
        _new_yaml().dump(data, buf)
        return self.write_text(filename, buf.getvalue(), overwrite=overwrite)

    def delete(self, filename: str) -> None:
        path = self._resolve(filename)
        if not path.exists():
            raise YamlStoreError(f"{filename} not found")
        path.unlink()

    # ----------------------------------------------------------- validation
    def validate_text(self, text: str) -> dict[str, Any]:
        """Run the same validator the CLI uses, to catch schema errors."""

        import yaml as _pyyaml

        from app.configuration.report_loader import _validate

        try:
            data = _pyyaml.safe_load(text) or {}
        except _pyyaml.YAMLError as exc:
            raise YamlStoreError(f"invalid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise YamlStoreError("expected a YAML mapping at the root")
        try:
            _validate(data, self.reports_dir / "(unsaved).yaml")
        except Exception as exc:
            raise YamlStoreError(str(exc)) from exc
        return data

    def _validate_text_or_raise(self, text: str) -> None:
        self.validate_text(text)  # raises YamlStoreError on failure


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (tmp file + rename)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            if not text.endswith("\n"):
                fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
