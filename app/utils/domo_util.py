"""Wrapper around the bundled ``domoUtil.jar`` Domo CLI.

The Domo CLI is a Java tool. We talk to it by spawning ``java -jar`` with
``stdin=PIPE`` and feeding it commands. The single biggest perf win versus
the original implementation is **batching** -- a single JVM cold start can
serve N card-image generations instead of paying that cost per card.

Performance comparison for a 9-card report (typical RD-style report):
    * Original: ~9 JVM cold starts -> ~25-40s
    * Batched:  ~1 JVM cold start  -> ~5-10s
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.configuration.settings import get_env
from app.utils.logger import get_logger

logger = get_logger(__name__)


# How long to let the Java process run before we give up. Generous default --
# generating 30+ cards in a single batch is normal.
_DEFAULT_TIMEOUT_SECONDS = 600


class DomoCliError(RuntimeError):
    """Raised when the Domo CLI subprocess fails or times out."""


@dataclass(frozen=True)
class CardImageRequest:
    """A single card-image generation request for a batched CLI call."""

    card_id: int
    output_path: str

    def to_command(self) -> str:
        return f"generate-card-image -i {self.card_id} -f {shlex.quote(self.output_path)}\n"


def _domo_instance() -> str:
    return get_env("DOMO_INSTANCE", required=True)


def _domo_token() -> str:
    return get_env("DOMO_TOKEN", required=True)


def _domo_cards_meta_dataset_id() -> str:
    return get_env("DOMO_CARDS_META_DATASET_ID", required=True)


@retry(
    retry=retry_if_exception_type(DomoCliError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
def exec_domo_util(
    domo_util_jar_path: str,
    cli_commands: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
) -> tuple[str, str]:
    """Run a single Domo CLI command string against a fresh JVM.

    Args:
        domo_util_jar_path: Absolute path to ``domoUtil.jar``.
        cli_commands: Newline-terminated CLI commands. ``connect`` and
            ``exit`` are added automatically.
        timeout_seconds: Hard upper bound; raises :class:`DomoCliError` on
            timeout.

    Returns:
        ``(stdout, stderr)`` from the JVM.
    """

    return _run_jvm(domo_util_jar_path, cli_commands, timeout_seconds)


def exec_domo_util_batch(
    domo_util_jar_path: str,
    cli_commands: Sequence[str],
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
) -> tuple[str, str]:
    """Run many Domo CLI commands against a single JVM session.

    ``connect`` and ``exit`` are added automatically. Each command in
    ``cli_commands`` should be a single newline-terminated CLI line.
    """

    if not cli_commands:
        return "", ""
    return _run_jvm(domo_util_jar_path, "".join(cli_commands), timeout_seconds)


def _run_jvm(
    domo_util_jar_path: str,
    user_commands: str,
    timeout_seconds: int,
) -> tuple[str, str]:
    """Internal: actually spawn the JVM and feed it commands."""

    instance = _domo_instance()
    token = _domo_token()
    full_input = f"connect -s {instance} -t {token}\n{user_commands}exit\n"

    logger.debug("Spawning JVM for Domo CLI (timeout=%ss)", timeout_seconds)
    try:
        process = subprocess.Popen(
            ["java", "-jar", domo_util_jar_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise DomoCliError(
            "`java` not found on PATH. Install a JRE (e.g. `apt install default-jre-headless` "
            "or `brew install openjdk`) and try again."
        ) from exc

    try:
        stdout, stderr = process.communicate(full_input, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise DomoCliError(
            f"Domo CLI timed out after {timeout_seconds}s."
        ) from exc

    if process.returncode != 0:
        raise DomoCliError(
            f"Domo CLI exited with code {process.returncode}. "
            f"stderr: {stderr.strip() or '<empty>'}"
        )

    if stderr.strip():
        # CLI sometimes prints harmless warnings to stderr; log at WARNING.
        logger.warning("Domo CLI stderr: %s", stderr.strip())

    return stdout, stderr


# ----------------------------------------------------------------------------
# High-level helpers (called by DomoBase)
# ----------------------------------------------------------------------------

def exec_domo_export_dataset(domo_util_jar_path: str, output_file_path: str) -> None:
    """Export the configured metadata dataset to ``output_file_path``."""

    dataset_id = _domo_cards_meta_dataset_id()
    exec_domo_util(
        domo_util_jar_path,
        cli_commands=f"export-data -i {dataset_id} -f {shlex.quote(output_file_path)}\n",
    )
    logger.info("Exported metadata dataset to %s", output_file_path)


def exec_domo_generate_image(
    domo_util_jar_path: str,
    card_id: int,
    output_image_path: str,
) -> None:
    """Generate a single card image. Prefer :func:`exec_domo_generate_images`."""

    exec_domo_util(
        domo_util_jar_path,
        cli_commands=f"generate-card-image -i {card_id} -f {shlex.quote(output_image_path)}\n",
    )


def exec_domo_generate_images(
    domo_util_jar_path: str,
    requests: Sequence[CardImageRequest],
) -> None:
    """Generate many card images in **one** JVM session (much faster)."""

    if not requests:
        return
    commands = [req.to_command() for req in requests]
    logger.info("Batch-generating %d card image(s) in a single JVM.", len(requests))
    exec_domo_util_batch(domo_util_jar_path, commands)


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
