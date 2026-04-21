"""Tests for `app.cli.doctor`."""

from __future__ import annotations

from app.cli.doctor import (
    DoctorCheck,
    DoctorReport,
    _print_report_plain,
    run_doctor,
)

# ---- DoctorReport ----


def test_doctor_report_counts_statuses():
    report = DoctorReport()
    report.add(DoctorCheck(name="a", status="ok"))
    report.add(DoctorCheck(name="b", status="warn"))
    report.add(DoctorCheck(name="c", status="fail"))
    report.add(DoctorCheck(name="d", status="skip"))

    assert report.ok_count == 1
    assert report.warn_count == 1
    assert report.fail_count == 1
    assert report.exit_code == 1


def test_doctor_report_exit_code_zero_without_failures():
    report = DoctorReport()
    report.add(DoctorCheck(name="ok", status="ok"))
    report.add(DoctorCheck(name="warn", status="warn"))
    assert report.exit_code == 0


# ---- run_doctor (integration) ----


def test_run_doctor_with_rest_engine_and_creds_set(monkeypatch):
    env: dict[str, str] = {
        "DOMO_ENGINE": "rest",
        "DOMO_CLIENT_ID": "abc",
        "DOMO_CLIENT_SECRET": "def",
        "DOMO_API_HOST": "api.domo.com",
    }
    report = run_doctor(getenv=lambda name, default=None: env.get(name, default))
    names = {c.name: c for c in report.checks}
    assert names["Python version"].status == "ok"
    assert names["DOMO_ENGINE"].status == "ok"
    assert names["DOMO_CLIENT_ID"].status == "ok"
    assert names["DOMO_CLIENT_SECRET"].status == "ok"
    assert names["DOMO_API_HOST"].status == "ok"
    assert names["Domo JAR"].status == "skip"


def test_run_doctor_missing_rest_credentials_flags_failures():
    env: dict[str, str] = {"DOMO_ENGINE": "rest"}
    report = run_doctor(getenv=lambda name, default=None: env.get(name, default))
    names = {c.name: c for c in report.checks}
    assert names["DOMO_CLIENT_ID"].status == "fail"
    assert names["DOMO_CLIENT_SECRET"].status == "fail"
    assert names["DOMO_API_HOST"].status == "fail"
    assert report.exit_code == 1


def test_run_doctor_unknown_engine_fails():
    env = {"DOMO_ENGINE": "zonk"}
    report = run_doctor(getenv=lambda name, default=None: env.get(name, default))
    engine_check = next(c for c in report.checks if c.name == "DOMO_ENGINE")
    assert engine_check.status == "fail"


def test_run_doctor_jar_engine_skips_rest_checks():
    env = {"DOMO_ENGINE": "jar"}
    report = run_doctor(getenv=lambda name, default=None: env.get(name, default))
    # REST credential checks should be marked SKIP, not FAIL, when engine=jar.
    rest_check = next(c for c in report.checks if c.name == "Domo REST credentials")
    assert rest_check.status == "skip"


def test_run_doctor_jar_engine_reports_jar_path():
    env = {"DOMO_ENGINE": "jar"}
    report = run_doctor(getenv=lambda name, default=None: env.get(name, default))
    jar_check = next(c for c in report.checks if c.name == "Domo JAR")
    # Either OK (jar bundled) or FAIL (downloaded separately); not SKIP.
    assert jar_check.status in {"ok", "fail"}


# ---- plain-text renderer ----


def test_plain_renderer_prints_each_check(capsys):
    report = DoctorReport()
    report.add(DoctorCheck(name="Python", status="ok", detail="3.12"))
    report.add(
        DoctorCheck(
            name="DOMO_CLIENT_ID",
            status="fail",
            detail="missing",
            hint="Set DOMO_CLIENT_ID",
        )
    )

    _print_report_plain(report)
    captured = capsys.readouterr().out
    assert "domo-report doctor" in captured
    assert "Python" in captured
    assert "DOMO_CLIENT_ID" in captured
    assert "Set DOMO_CLIENT_ID" in captured
    assert "ok=1" in captured and "fail=1" in captured


# ---- optional deps ----


def test_optional_deps_reported_as_warn_or_ok():
    env: dict[str, str] = {"DOMO_ENGINE": "rest"}
    report = run_doctor(getenv=lambda name, default=None: env.get(name, default))
    optional_checks = [c for c in report.checks if c.name.startswith("Optional:")]
    assert len(optional_checks) >= 1
    # Any optional check's status is either "ok" or "warn"; never "fail".
    for c in optional_checks:
        assert c.status in {"ok", "warn"}


def test_destination_registry_check_passes():
    env: dict[str, str] = {"DOMO_ENGINE": "rest"}
    report = run_doctor(getenv=lambda name, default=None: env.get(name, default))
    dest_check = next(c for c in report.checks if c.name == "Destination registry")
    assert dest_check.status == "ok"
    # Default registry must include at least slack + teams + file + email.
    for key in ("slack", "teams", "file", "email"):
        assert key in dest_check.detail


def test_history_backend_check_passes():
    env: dict[str, str] = {"DOMO_ENGINE": "rest"}
    report = run_doctor(getenv=lambda name, default=None: env.get(name, default))
    history_check = next(c for c in report.checks if c.name == "History backend")
    assert history_check.status == "ok"


# ---- CLI flag wiring ----


def test_main_doctor_returns_exit_code(monkeypatch, capsys):
    """When --doctor is passed, main() should run the doctor and return its exit code."""

    import main as main_module

    monkeypatch.setattr("sys.argv", ["domo-report", "--doctor"])

    # Force a failing env so we exercise non-zero exit
    monkeypatch.setenv("DOMO_ENGINE", "zonk")
    monkeypatch.delenv("DOMO_CLIENT_ID", raising=False)
    monkeypatch.delenv("DOMO_CLIENT_SECRET", raising=False)

    exit_code = main_module.main()
    assert exit_code == 1
    captured = capsys.readouterr().out
    assert "doctor" in captured.lower() or "summary" in captured.lower()
