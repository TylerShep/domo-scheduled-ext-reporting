"""Pure-evaluator tests for app.alerts.conditions."""

from __future__ import annotations

import pytest

from app.alerts.conditions import (
    ConditionResult,
    evaluate,
    should_send,
)

# ---- empty / no expression ----


@pytest.mark.parametrize("expr", [None, "", "   ", "\t\n"])
def test_empty_expression_allows(expr):
    result = evaluate(expr)
    assert isinstance(result, ConditionResult)
    assert result.allowed is True
    assert result.reason == "no-expression"


# ---- truthy / falsy literals ----


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("True", True),
        ("False", False),
        ("1 == 1", True),
        ("1 == 2", False),
        ("1 > 0 and 'a' == 'a'", True),
        ("1 > 2 or 'a' == 'b'", False),
    ],
)
def test_literal_expressions(expr, expected):
    result = evaluate(expr)
    assert result.allowed is expected
    assert result.reason in {"truthy", "falsy"}


# ---- context variables ----


def test_dotdict_access_on_nested_context():
    ctx = {"card": {"value": 42, "name": "X"}}
    assert should_send("card.value > 40", ctx) is True
    assert should_send("card.value < 40", ctx) is False
    assert should_send("card.name == 'X'", ctx) is True


def test_missing_attribute_returns_none_not_error():
    from app.alerts.context import DotDict

    ctx = {"card": DotDict(name="X")}
    # card.value does not exist -> None -> comparisons are False.
    result = evaluate("card.value == 0", ctx)
    assert result.allowed is False


def test_expression_uses_builtins_safely():
    ctx = {"card": {"name": "ACME"}}
    assert should_send("len(card['name']) == 4", ctx) is True


# ---- type coercion ----


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("0", False),
        ("1", True),
        ("''", False),
        ("'x'", True),
        ("[]", False),
        ("[1]", True),
        ("None", False),
    ],
)
def test_result_bool_coercion(expr, expected):
    assert evaluate(expr).allowed is expected


# ---- syntax errors ----


def test_syntax_error_falls_back_to_allow():
    """A syntax error should NOT suppress sending -- fail open."""

    result = evaluate("this is not valid (python")
    assert result.allowed is True
    assert result.reason == "error"
    assert result.error is not None


def test_runtime_error_falls_back_to_allow():
    result = evaluate("1 / 0")
    assert result.allowed is True
    assert result.reason == "error"


# ---- statelessness ----


def test_assignments_do_not_persist_between_calls():
    evaluate("x = 100")
    # A second call should NOT see x defined.
    result = evaluate("x > 50")
    assert result.allowed is True  # fail-open, but it's "error" since x is undefined
    assert result.reason == "error"
