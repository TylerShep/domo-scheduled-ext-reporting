"""JAR-based Domo engine.

Talks to the bundled ``domoUtil.jar`` via ``java -jar`` over stdin/stdout.
This is the legacy path -- new users should prefer the REST engine. The JAR
remains useful for two reasons:

    1. Some Domo CLI features (e.g. card-image rendering) are not exposed
       on the public REST API in every plan.
    2. Existing deployments may rely on it.

Performance note: a single JVM cold start serves N requests when you call
:meth:`JarEngine.generate_card_images`. Calling
:meth:`generate_card_image` in a loop pays the cost N times -- always
prefer the batched method when you have multiple cards.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.configuration.settings import get_env
from app.engines.base import CardImageRequest, DomoEngine, DomoEngineError
from app.utils.logger import get_logger
from app.utils.project_setup_util import get_domo_util_path

logger = get_logger(__name__)


_DEFAULT_TIMEOUT_SECONDS = 600


class JarEngineError(DomoEngineError):
    """Raised when the bundled Domo CLI subprocess fails or times out."""


class JarEngine(DomoEngine):
    """Wraps ``domoUtil.jar`` behind the :class:`DomoEngine` interface."""

    key = "jar"
    label = "Domo JAR CLI"

    def __init__(
        self,
        jar_path: str | None = None,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._jar_path = jar_path or get_domo_util_path()
        self._timeout_seconds = timeout_seconds

    # ---- DomoEngine ----

    def export_dataset(self, dataset_id: str, output_path: str) -> None:
        cmd = f"export-data -i {dataset_id} -f {shlex.quote(output_path)}\n"
        self._run_user_commands(cmd)
        logger.info("JAR engine exported dataset %s -> %s", dataset_id, output_path)

    def generate_card_image(
        self,
        card_id: int,
        output_path: str,
        **opts: Any,
    ) -> None:
        cmd = f"generate-card-image -i {card_id} -f {shlex.quote(output_path)}\n"
        self._run_user_commands(cmd)

    def generate_card_images(self, requests: Sequence[CardImageRequest]) -> None:
        if not requests:
            return
        commands = "".join(req.to_jar_command() for req in requests)
        logger.info(
            "JAR engine batch-generating %d card image(s) in one JVM session.",
            len(requests),
        )
        self._run_user_commands(commands)

    def _self_test(self) -> None:
        if not shutil.which("java"):
            raise JarEngineError(
                "`java` binary not found on PATH. Install a JRE or switch " "DOMO_ENGINE to `rest`."
            )
        # We DO NOT spawn the JVM here -- too expensive. Just confirm config.
        _domo_instance()
        _domo_token()

    # ---- internals ----

    @retry(
        retry=retry_if_exception_type(JarEngineError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _run_user_commands(self, user_commands: str) -> tuple[str, str]:
        """Run ``user_commands`` against a fresh JVM with retry/backoff."""

        if not os.path.isfile(self._jar_path):
            raise JarEngineError(
                f"Domo CLI JAR not found at {self._jar_path}. "
                f"Run `domo-report --download-jar` to fetch it, or switch "
                f"DOMO_ENGINE to `rest`."
            )

        instance = _domo_instance()
        token = _domo_token()
        full_input = f"connect -s {instance} -t {token}\n{user_commands}exit\n"

        logger.debug("Spawning JVM (timeout=%ss)", self._timeout_seconds)
        try:
            process = subprocess.Popen(
                ["java", "-jar", self._jar_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise JarEngineError(
                "`java` not found on PATH. Install a JRE (e.g. "
                "`apt install default-jre-headless` or `brew install openjdk`) "
                "and try again."
            ) from exc

        try:
            stdout, stderr = process.communicate(full_input, timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise JarEngineError(f"Domo CLI timed out after {self._timeout_seconds}s.") from exc

        if process.returncode != 0:
            raise JarEngineError(
                f"Domo CLI exited with code {process.returncode}. "
                f"stderr: {stderr.strip() or '<empty>'}"
            )

        if stderr.strip():
            logger.warning("Domo CLI stderr: %s", stderr.strip())

        return stdout, stderr


def _domo_instance() -> str:
    return get_env("DOMO_INSTANCE", required=True)


def _domo_token() -> str:
    return get_env("DOMO_TOKEN", required=True)
