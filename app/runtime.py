"""Process-wide runtime flags: dry-run, preview, verbose, etc.

These are global toggles the CLI can flip at startup so destinations /
engines / services can react without us threading a flags object through
every method call.

Typical use::

    from app.runtime import get_flags, set_flags, RuntimeFlags

    set_flags(RuntimeFlags(dry_run=True, preview=True))

    if get_flags().dry_run:
        logger.info("Dry run -- not actually sending.")
        return

Destinations consult :func:`get_flags` at the top of ``send_image`` /
``send_dataset`` and short-circuit if ``dry_run`` is on. Each destination
also accepts a per-instance ``dry_run=True`` constructor kwarg -- we
merge the two (either set => skip the send).

The ``preview`` flag additionally saves every generated card image to
``state/preview/<report_name>/<card>.png`` so users can eyeball output
without sending anywhere.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, replace

__all__ = [
    "RuntimeFlags",
    "get_flags",
    "set_flags",
    "reset_flags",
    "update_flags",
    "preview_dir",
    "is_preview_enabled",
    "is_dry_run",
]


_DEFAULT_PREVIEW_DIR = "state/preview"


@dataclass(frozen=True)
class RuntimeFlags:
    """Global runtime toggles set once at CLI startup.

    Attributes:
        dry_run: If True, destinations log what they would send but make
            no network calls. Images are still generated (so the preview
            folder works).
        preview: If True, every generated card image is copied into
            ``preview_path`` before destinations run. Implies nothing
            about ``dry_run`` -- you can preview a real run.
        preview_path: Directory the preview images are copied to. Ignored
            when ``preview`` is False.
        verbose: If True, the CLI surfaces verbose log output. Destinations
            may use this to add extra breadcrumbs; it does not short-circuit
            any sends.
    """

    dry_run: bool = False
    preview: bool = False
    preview_path: str = _DEFAULT_PREVIEW_DIR
    verbose: bool = False


_LOCK = threading.Lock()
_CURRENT: RuntimeFlags = RuntimeFlags()


def get_flags() -> RuntimeFlags:
    """Return the current process-wide :class:`RuntimeFlags`."""

    with _LOCK:
        return _CURRENT


def set_flags(flags: RuntimeFlags) -> None:
    """Replace the current process-wide :class:`RuntimeFlags`."""

    global _CURRENT
    with _LOCK:
        _CURRENT = flags


def reset_flags() -> None:
    """Reset to the default :class:`RuntimeFlags` (useful for tests)."""

    set_flags(RuntimeFlags())


def update_flags(**changes) -> RuntimeFlags:
    """Return and install an updated copy of the current flags.

    This is a thin wrapper around ``dataclasses.replace`` that also
    writes the result back into the process-wide slot. Returns the new
    :class:`RuntimeFlags` for convenience.
    """

    global _CURRENT
    with _LOCK:
        _CURRENT = replace(_CURRENT, **changes)
        return _CURRENT


# ---- convenience helpers ----


def is_dry_run(override: bool | None = None) -> bool:
    """Return True if either the global flag or the per-destination override is set.

    Destinations call this as ``is_dry_run(self.dry_run)`` so the caller
    can opt one destination in/out of dry-run independently.
    """

    if override:
        return True
    return get_flags().dry_run


def is_preview_enabled() -> bool:
    """Return True when the global preview flag is on."""

    return get_flags().preview


def preview_dir() -> str:
    """Return the resolved preview directory (absolute or CWD-relative)."""

    path = get_flags().preview_path or _DEFAULT_PREVIEW_DIR
    return os.path.abspath(path)
