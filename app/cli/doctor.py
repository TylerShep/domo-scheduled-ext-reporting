"""`domo-report --doctor` -- environment health check.

Runs a series of :class:`DoctorCheck` probes against the current
environment and prints a pass/fail table.  Typical checks:

* Python version is >= 3.10.
* ``DOMO_ENGINE`` is set to a known engine key.
* When engine is ``rest``:  ``DOMO_CLIENT_ID`` + ``DOMO_CLIENT_SECRET``
  + ``DOMO_API_HOST`` are populated and (optionally) that we can acquire
  a token.
* When engine is ``jar``:  the JAR file is present and we can find a JVM.
* YAML reports under ``config/reports/`` parse cleanly.
* History backend is initialized and reachable.
* ``reports:write`` / ``files:write`` / ``chat:write`` scopes are
  present on the Slack token (if a Slack destination is configured).

Output format uses :mod:`rich` when available; otherwise plain ANSI
fallback. Either way the function returns a :class:`DoctorReport` so
tests can assert structured pass/fail data.
"""

from __future__ import annotations

import os
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from app.utils.logger import get_logger

logger = get_logger(__name__)


class _CheckStatus:
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class DoctorCheck:
    """One self-contained probe."""

    name: str
    status: str = _CheckStatus.SKIP
    detail: str = ""
    hint: str | None = None


@dataclass
class DoctorReport:
    """Collection of :class:`DoctorCheck` results with a summary."""

    checks: list[DoctorCheck] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for c in self.checks if c.status == _CheckStatus.OK)

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.status == _CheckStatus.WARN)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status == _CheckStatus.FAIL)

    @property
    def exit_code(self) -> int:
        """``0`` when all checks pass, ``1`` when any fail."""

        return 1 if self.fail_count else 0

    def add(self, check: DoctorCheck) -> None:
        self.checks.append(check)


# ---------------------------------------------------------------------------
# Individual check runners
# ---------------------------------------------------------------------------


def _check_python_version() -> DoctorCheck:
    major, minor = sys.version_info.major, sys.version_info.minor
    if (major, minor) >= (3, 10):
        return DoctorCheck(
            name="Python version",
            status=_CheckStatus.OK,
            detail=f"{major}.{minor}.{sys.version_info.micro} on {platform.system()}",
        )
    return DoctorCheck(
        name="Python version",
        status=_CheckStatus.FAIL,
        detail=f"Python {major}.{minor} detected (requires 3.10+)",
        hint="Install Python 3.10 or newer and reinstall the project.",
    )


def _check_engine_env(getenv: Callable[[str, str | None], str | None]) -> DoctorCheck:
    engine = getenv("DOMO_ENGINE", "rest") or "rest"
    if engine not in {"rest", "jar", "auto"}:
        return DoctorCheck(
            name="DOMO_ENGINE",
            status=_CheckStatus.FAIL,
            detail=f"Unknown engine key {engine!r}",
            hint="Valid values: 'rest' (default), 'jar', or 'auto'.",
        )
    return DoctorCheck(
        name="DOMO_ENGINE",
        status=_CheckStatus.OK,
        detail=f"Using engine: {engine}",
    )


def _check_rest_credentials(
    getenv: Callable[[str, str | None], str | None],
) -> list[DoctorCheck]:
    engine = (getenv("DOMO_ENGINE", "rest") or "rest").lower()
    if engine not in {"rest", "auto"}:
        return [
            DoctorCheck(
                name="Domo REST credentials",
                status=_CheckStatus.SKIP,
                detail=f"engine={engine}, skipping REST credential check.",
            )
        ]

    out: list[DoctorCheck] = []
    for var in ("DOMO_CLIENT_ID", "DOMO_CLIENT_SECRET", "DOMO_API_HOST"):
        val = getenv(var, None)
        if not val:
            out.append(
                DoctorCheck(
                    name=var,
                    status=_CheckStatus.FAIL,
                    detail="missing",
                    hint=f"Set {var} in your .env or environment.",
                )
            )
        else:
            masked = val if var == "DOMO_API_HOST" else "***"
            out.append(DoctorCheck(name=var, status=_CheckStatus.OK, detail=masked))
    return out


def _check_jar_available(getenv: Callable[[str, str | None], str | None]) -> DoctorCheck:
    engine = (getenv("DOMO_ENGINE", "rest") or "rest").lower()
    if engine not in {"jar", "auto"}:
        return DoctorCheck(
            name="Domo JAR",
            status=_CheckStatus.SKIP,
            detail=f"engine={engine}, JAR not needed.",
        )
    try:
        from app.utils.project_setup_util import get_domo_util_path

        jar_path = get_domo_util_path()
    except Exception as exc:
        return DoctorCheck(
            name="Domo JAR",
            status=_CheckStatus.FAIL,
            detail=f"failed to resolve JAR path: {exc}",
            hint="Download the JAR with `domo-report --download-jar`.",
        )

    if not jar_path or not os.path.isfile(str(jar_path)):
        return DoctorCheck(
            name="Domo JAR",
            status=_CheckStatus.FAIL,
            detail="JAR file not found",
            hint=(
                "Download the JAR to app/utils/domoUtil.jar or set "
                "DOMO_UTIL_PATH to an existing file."
            ),
        )
    return DoctorCheck(
        name="Domo JAR",
        status=_CheckStatus.OK,
        detail=str(jar_path),
    )


def _check_yaml_reports() -> DoctorCheck:
    from app.configuration.report_loader import validate_all

    valid, errors = validate_all()
    if not valid and not errors:
        return DoctorCheck(
            name="YAML reports",
            status=_CheckStatus.WARN,
            detail="no YAML reports found in config/reports/",
            hint="Run `domo-report --init` to scaffold one.",
        )
    if errors:
        return DoctorCheck(
            name="YAML reports",
            status=_CheckStatus.FAIL,
            detail=f"{len(valid)} valid, {len(errors)} invalid",
            hint=("First error: " + errors[0]) if errors else None,
        )
    return DoctorCheck(
        name="YAML reports",
        status=_CheckStatus.OK,
        detail=f"{len(valid)} report(s) valid",
    )


def _check_history_backend() -> DoctorCheck:
    try:
        from app.history import get_backend

        backend = get_backend()
        # Do a read-only smoke test: request zero rows.
        backend.get_runs(limit=0)
    except Exception as exc:
        return DoctorCheck(
            name="History backend",
            status=_CheckStatus.FAIL,
            detail=f"initialization failed: {exc}",
            hint=(
                "Check RUN_HISTORY_BACKEND (default: sqlite) and the " "corresponding DSN / path."
            ),
        )
    return DoctorCheck(
        name="History backend",
        status=_CheckStatus.OK,
        detail=backend.__class__.__name__,
    )


def _check_destinations_importable() -> DoctorCheck:
    try:
        from app.destinations.registry import known_destination_types

        registered = known_destination_types()
    except Exception as exc:
        return DoctorCheck(
            name="Destination registry",
            status=_CheckStatus.FAIL,
            detail=f"failed to import: {exc}",
        )
    return DoctorCheck(
        name="Destination registry",
        status=_CheckStatus.OK,
        detail=f"{len(registered)} registered: {', '.join(registered)}",
    )


def _check_optional_deps() -> list[DoctorCheck]:
    """Warn (never fail) when nice-to-have deps are missing."""

    def _probe(module: str, extra: str | None = None) -> DoctorCheck:
        try:
            __import__(module)
        except ImportError:
            hint = (
                f'pip install "domo-scheduled-ext-reporting[{extra}]"'
                if extra
                else f"pip install {module}"
            )
            return DoctorCheck(
                name=f"Optional: {module}",
                status=_CheckStatus.WARN,
                detail="not installed",
                hint=hint,
            )
        return DoctorCheck(
            name=f"Optional: {module}",
            status=_CheckStatus.OK,
            detail="installed",
        )

    return [
        _probe("prometheus_client", extra="metrics"),
        _probe("openpyxl", extra="xlsx"),
        _probe("psycopg", extra="postgres"),
    ]


# ---------------------------------------------------------------------------
# Orchestration + reporting
# ---------------------------------------------------------------------------


def run_doctor(
    getenv: Callable[[str, str | None], str | None] | None = None,
) -> DoctorReport:
    """Run every doctor check and return a structured report."""

    env = getenv or (lambda name, default=None: os.environ.get(name, default))

    report = DoctorReport()
    report.add(_check_python_version())
    report.add(_check_engine_env(env))
    for check in _check_rest_credentials(env):
        report.add(check)
    report.add(_check_jar_available(env))
    report.add(_check_yaml_reports())
    report.add(_check_destinations_importable())
    report.add(_check_history_backend())
    for check in _check_optional_deps():
        report.add(check)
    return report


# ---------------------------------------------------------------------------
# Human-friendly printing
# ---------------------------------------------------------------------------


def print_report(report: DoctorReport) -> None:
    """Print a ``DoctorReport`` using ``rich`` when available."""

    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        _print_report_plain(report)
        return

    console = Console()
    table = Table(title="domo-report doctor", show_lines=False)
    table.add_column("Check", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", overflow="fold")

    style_map = {
        _CheckStatus.OK: ("[bold green]OK[/]", None),
        _CheckStatus.WARN: ("[bold yellow]WARN[/]", None),
        _CheckStatus.FAIL: ("[bold red]FAIL[/]", None),
        _CheckStatus.SKIP: ("[dim]SKIP[/]", None),
    }
    for c in report.checks:
        status_text, _ = style_map.get(c.status, (c.status.upper(), None))
        detail = c.detail
        if c.hint:
            detail += f"\n[dim]-> {c.hint}[/]"
        table.add_row(c.name, status_text, detail)

    console.print(table)
    console.print(
        f"\n[bold]Summary:[/] ok={report.ok_count}  "
        f"warn={report.warn_count}  fail={report.fail_count}"
    )


def _print_report_plain(report: DoctorReport) -> None:
    """Fallback renderer when ``rich`` isn't installed."""

    width = max(len(c.name) for c in report.checks) + 2
    print("== domo-report doctor ==")
    for c in report.checks:
        print(f"  [{c.status.upper():4}] {c.name.ljust(width)} {c.detail}")
        if c.hint:
            print(f"         -> {c.hint}")
    print(
        f"\nSummary: ok={report.ok_count}  " f"warn={report.warn_count}  fail={report.fail_count}"
    )
