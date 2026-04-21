"""Property-based tests for :mod:`app.templating`.

We care about invariants more than individual inputs:

* :func:`render_safe` is a pure function -- calling it twice with the same
  inputs always returns the same output.
* The arithmetic filters (``currency``, ``pct``, ``human_number``) never raise
  for any finite floating-point input.
"""

from __future__ import annotations

import math

from hypothesis import assume, given
from hypothesis import strategies as st

from app.templating.engine import render_safe

# ------------------------------------------------------------- render_safe


@given(
    name=st.text(min_size=0, max_size=50, alphabet=st.characters(blacklist_categories=("Cs",))),
    count=st.integers(min_value=0, max_value=10_000),
)
def test_render_safe_is_deterministic(name, count):
    """Same input -> same output, every time."""

    template = "Hello {{ name }}, you have {{ count }} cards."
    ctx = {"name": name, "count": count}
    assert render_safe(template, ctx) == render_safe(template, ctx)


@given(
    data=st.dictionaries(
        keys=st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz"),
        values=st.integers(min_value=-1_000_000, max_value=1_000_000),
        min_size=0,
        max_size=10,
    )
)
def test_render_safe_ignores_unused_keys(data):
    """Passing extra context keys never changes the output for a static template."""

    template = "static text"
    assert render_safe(template, data) == "static text"


# --------------------------------------------------------------- filters


@given(
    amount=st.floats(
        min_value=-1e12,
        max_value=1e12,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_currency_filter_never_raises(amount):
    out = render_safe("{{ x | currency }}", {"x": amount})
    assert isinstance(out, str) and out  # non-empty


@given(
    value=st.floats(
        min_value=-1e6,
        max_value=1e6,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_pct_filter_never_raises(value):
    out = render_safe("{{ x | pct }}", {"x": value})
    assert "%" in out


@given(
    value=st.floats(
        min_value=-1e15,
        max_value=1e15,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_human_number_never_raises(value):
    assume(not math.isnan(value) and not math.isinf(value))
    out = render_safe("{{ x | human_number }}", {"x": value})
    assert isinstance(out, str) and out
