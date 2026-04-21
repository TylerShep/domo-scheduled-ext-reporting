"""Compatibility shim around the old ``app.utils.domo_util`` API.

The real engine lives in :mod:`app.engines` now (see Wave 1 of the v2
rebuild). This module preserves the legacy public functions so any caller
that imported ``exec_domo_util`` / ``CardImageRequest`` / etc. keeps working.

For new code, import :class:`app.engines.DomoEngine` and call
:func:`app.engines.get_engine` directly.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from app.engines import CardImageRequest as _EngineCardImageRequest
from app.engines.base import DomoEngineError as _EngineError
from app.engines.jar import JarEngine
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Public type aliases preserved for backwards compatibility.
CardImageRequest = _EngineCardImageRequest


class DomoCliError(_EngineError):
    """Legacy alias for :class:`app.engines.base.DomoEngineError`."""


def exec_domo_util(
    domo_util_jar_path: str,
    cli_commands: str,
    timeout_seconds: int = 600,
) -> tuple[str, str]:
    """Run a single newline-terminated CLI command via the JAR engine.

    Kept for backward compatibility. New code should call methods on a
    :class:`~app.engines.jar.JarEngine` instance directly.
    """

    engine = JarEngine(jar_path=domo_util_jar_path, timeout_seconds=timeout_seconds)
    return engine._run_user_commands(cli_commands)  # type: ignore[no-any-return]


def exec_domo_util_batch(
    domo_util_jar_path: str,
    cli_commands: Sequence[str],
    timeout_seconds: int = 600,
) -> tuple[str, str]:
    """Run many CLI commands in one JVM session. Backwards-compatible."""

    if not cli_commands:
        return "", ""
    engine = JarEngine(jar_path=domo_util_jar_path, timeout_seconds=timeout_seconds)
    return engine._run_user_commands("".join(cli_commands))  # type: ignore[no-any-return]


def exec_domo_export_dataset(domo_util_jar_path: str, output_file_path: str) -> None:
    """Backwards-compatible wrapper -- pulls dataset id from env."""

    from app.configuration.settings import get_env

    dataset_id = get_env("DOMO_CARDS_META_DATASET_ID", required=True)
    engine = JarEngine(jar_path=domo_util_jar_path)
    engine.export_dataset(dataset_id, output_file_path)


def exec_domo_generate_image(
    domo_util_jar_path: str,
    card_id: int,
    output_image_path: str,
) -> None:
    """Backwards-compatible single-card image generator."""

    engine = JarEngine(jar_path=domo_util_jar_path)
    engine.generate_card_image(card_id, output_image_path)


def exec_domo_generate_images(
    domo_util_jar_path: str,
    requests: Sequence[CardImageRequest],
) -> None:
    """Backwards-compatible batched image generator."""

    if not requests:
        return
    engine = JarEngine(jar_path=domo_util_jar_path)
    engine.generate_card_images(requests)


def query_card_metadata(
    card_lst: Sequence[str],
    file_path: str,
) -> tuple[int, str, str]:
    """Resolve a card's ID/URL/page from the exported metadata CSV.

    Args:
        card_lst: Either a 3-tuple ``[dashboard, card, viz_type]`` (as in the
            original Python service classes) or a longer list whose
            ``dashboard`` and ``card`` values are at indexes 0 and 1.
        file_path: Path to the exported metadata CSV.

    Returns:
        ``(card_id, card_url, page_name)``

    Raises:
        DomoCliError: If no row matches.
    """

    df = pd.read_csv(file_path)
    df.columns = df.columns.str.strip()

    expected = {"CardID", "CardName", "CardURL", "PageID", "PageTItle"}
    missing = expected - set(df.columns)
    if missing:
        raise DomoCliError(
            f"Metadata CSV is missing required columns: {sorted(missing)}. "
            "Update DOMO_CARDS_META_DATASET_ID to point at a dataset with "
            "these columns: CardID, CardName, CardURL, PageID, PageTItle."
        )

    df = df[["CardID", "CardName", "CardURL", "PageID", "PageTItle"]]
    output = df.loc[df["PageTItle"].isin(card_lst) & df["CardName"].isin(card_lst)]

    if output.empty:
        raise DomoCliError(
            f"No metadata row matched dashboard={card_lst[0]!r} card={card_lst[1]!r}. "
            "Verify the card name + dashboard name in your YAML/Python report exactly "
            "match the values in your metadata dataset."
        )

    return (
        int(output["CardID"].iloc[0]),
        str(output["CardURL"].iloc[0]),
        str(output["PageTItle"].iloc[0]),
    )
