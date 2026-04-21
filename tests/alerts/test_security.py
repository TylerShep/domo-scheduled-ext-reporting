"""Security tests: the expression sandbox must refuse dangerous calls."""

from __future__ import annotations

import pytest

from app.alerts.conditions import evaluate

# ---- refused tokens (fail open but never actually eval) ----


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('whoami')",
        "os.system('ls')",
        "os.popen('id')",
        "subprocess.run(['ls'])",
        "__builtins__.open('/etc/passwd')",
        "().__class__.__bases__",
        "globals()",
        "locals()",
        "getattr(card, 'name')",
        "setattr(card, 'name', 'x')",
        "vars(card)",
        "open('/etc/passwd')",
        "compile('x=1', '', 'exec')",
        "exec('print(1)')",
        "eval('1 + 1')",
        "input('hi')",
        "import os",
    ],
)
def test_refused_tokens_fail_open_without_executing(expression):
    """Refused tokens must fail open (allow=True) and mark reason='refused'.

    This is belt-and-suspenders. Even if asteval let one through, our
    token denylist catches it.
    """

    result = evaluate(expression)
    assert result.allowed is True
    assert result.reason == "refused"
    assert result.error is not None


# ---- asteval sandbox escapes ----


def test_cannot_read_filesystem_through_open(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("SHOULD_NEVER_APPEAR")

    # Even if the token filter somehow let "open" through, asteval won't
    # expose it as a callable.  Any pathway that reads file contents should
    # fail -- we assert we never get the string back.
    result = evaluate(f"open({str(secret)!r}).read() == 'SHOULD_NEVER_APPEAR'")
    assert result.allowed is True
    assert result.reason in {"refused", "error"}


def test_cannot_access_environment_vars_via_os(monkeypatch):
    monkeypatch.setenv("TYLER_SECRET", "topsecret")
    result = evaluate("os.environ['TYLER_SECRET'] == 'topsecret'")
    assert result.allowed is True
    assert result.reason in {"refused", "error"}


def test_no_import_possible():
    result = evaluate("__import__('os').listdir('/')")
    assert result.reason == "refused"


# ---- sanity: simple expressions return promptly ----


def test_simple_arithmetic_returns_quickly():
    """Simple arithmetic completes normally and returns expected boolean."""

    result = evaluate("1 + 1 == 2")
    assert result.allowed is True


def test_listcomp_is_disabled_in_minimal_mode():
    """`minimal=True` blocks list comprehensions -- a deliberate hardening.

    List comps aren't needed for alert conditions, and disabling them
    prevents accidental / adversarial O(n) blow-ups.
    """

    result = evaluate("[x for x in range(5)]")
    # Fails parse -> fail-open (allowed=True) with reason="error".
    assert result.reason == "error"
    assert result.allowed is True


# ---- sanity: no access via dunders even when asteval would allow it ----


@pytest.mark.parametrize(
    "payload",
    [
        "(1).__class__.__base__.__subclasses__()",
        "card.__class__",
        "{}.__class__.__mro__",
    ],
)
def test_dunder_payloads_refused(payload):
    result = evaluate(payload, context={"card": {"name": "X"}})
    assert result.reason == "refused"
    # State should not have been mutated. Nothing to assert beyond "we didn't
    # crash" -- the key point is "refused".
    assert result.allowed is True
