"""Tests for the shared Jinja2 templating engine + filters."""

from __future__ import annotations

import pytest

from app.templating import TemplateError, build_environment, render, render_safe
from app.templating.engine import currency, delta, human_number, pct

# ---- filter: currency ----


def test_currency_basic():
    assert currency(1234.5) == "$1,234.50"


def test_currency_custom_symbol_and_digits():
    assert currency(1234, symbol="£", digits=0) == "£1,234"


def test_currency_invalid_value_passes_through():
    assert currency("oops") == "oops"


def test_currency_handles_nan():
    assert currency(float("nan")) == "nan"


# ---- filter: pct ----


def test_pct_ratio_input():
    assert pct(0.425) == "42.50%"


def test_pct_direct_input():
    assert pct(42.5, as_ratio=False) == "42.50%"


def test_pct_custom_digits():
    assert pct(0.1, digits=0) == "10%"


# ---- filter: delta ----


def test_delta_positive():
    assert delta(0.08) == "+8.0%"


def test_delta_negative():
    assert delta(-0.032) == "-3.2%"


def test_delta_zero_is_flat():
    assert delta(0) == "flat"


# ---- filter: human_number ----


def test_human_number_thousands():
    assert human_number(12500) == "12.5K"


def test_human_number_millions():
    # 3_250_000 / 1e6 = 3.25 -> "3.2M" with 1 digit (banker's rounding).
    assert human_number(3_250_000) == "3.2M"
    # But 3_500_000 clearly rounds up.
    assert human_number(3_500_000) == "3.5M"


def test_human_number_billions():
    assert human_number(1_700_000_000) == "1.7B"


def test_human_number_small_value():
    assert human_number(42) == "42"


# ---- render ----


def test_render_basic_substitution():
    assert render("Hello {{ name }}", {"name": "world"}) == "Hello world"


def test_render_applies_custom_filters():
    assert render("Revenue: {{ value|currency }}", {"value": 4321.5}) == "Revenue: $4,321.50"


def test_render_uses_strict_undefined():
    with pytest.raises(TemplateError, match="neme"):
        render("{{ card.neme }}", {"card": {"name": "x"}})


def test_render_syntax_error_wraps_as_template_error():
    with pytest.raises(TemplateError):
        render("{% for x in %}", {})


def test_render_autoescape_toggle_off_by_default():
    # HTML should pass through unescaped when autoescape=False (default).
    out = render("<b>{{ x }}</b>", {"x": "<i>raw</i>"})
    assert out == "<b><i>raw</i></b>"


def test_render_autoescape_on():
    out = render("<b>{{ x }}</b>", {"x": "<i>raw</i>"}, autoescape=True)
    assert "&lt;i&gt;raw&lt;/i&gt;" in out


def test_render_extra_filter():
    out = render(
        "{{ 'yo'|shout }}",
        {},
        extra_filters=[("shout", lambda s: s.upper() + "!")],
    )
    assert out == "YO!"


# ---- render_safe ----


def test_render_safe_returns_fallback_on_error():
    assert render_safe("{{ card.neme }}", {"card": {"name": "x"}}, fallback="--") == "--"


def test_render_safe_returns_template_when_no_fallback_and_error():
    template = "{{ card.neme }}"
    assert render_safe(template, {"card": {"name": "x"}}) == template


def test_render_safe_normal_render():
    out = render_safe("{{ name }}", {"name": "Revenue"}, fallback="--")
    assert out == "Revenue"


# ---- environment ----


def test_build_environment_registers_filters():
    env = build_environment()
    for f in ("currency", "pct", "delta", "human_number"):
        assert f in env.filters


def test_build_environment_has_strict_undefined():
    from jinja2 import StrictUndefined

    env = build_environment()
    assert env.undefined is StrictUndefined


# ---- integration: destinations respect templates ----


def test_slack_comment_template_renders(tmp_path):
    from unittest.mock import MagicMock

    from app.destinations.base import DestinationContext
    from app.destinations.slack import SlackDestination

    image = tmp_path / "c.png"
    image.write_bytes(b"x")
    dest = SlackDestination(
        channel_name="data",
        comment_template="Hello {{ card.name }} - page {{ page_name }}",
    )
    # Fake the Slack client so we can intercept initial_comment.
    fake_client = MagicMock()
    fake_client.files_upload_v2.return_value = {"file": {"id": "F1"}}
    dest._client = fake_client
    dest._channel_id = "C1"

    dest.send_image(
        DestinationContext(
            image_path=str(image),
            card_name="Revenue",
            card_url="https://x",
            page_name="Sales",
        )
    )
    kwargs = fake_client.files_upload_v2.call_args.kwargs
    assert kwargs["initial_comment"] == "Hello Revenue - page Sales"


def test_teams_graph_caption_rendered_in_body_html():
    from app.destinations.base import DestinationContext
    from app.destinations.teams import TeamsGraphDestination

    dest = TeamsGraphDestination(
        team_name="T",
        channel_name="C",
        caption_template="Snapshot for {{ today }}",
    )
    html = dest._render_caption(DestinationContext("p.png", "Revenue", "https://x", "Sales"))
    assert "Snapshot for" in html
    assert "<p>" in html


def test_email_subject_uses_templates_and_filters(tmp_path):
    from unittest.mock import MagicMock, patch

    from app.destinations.base import DestinationContext
    from app.destinations.email import EmailDestination

    dest = EmailDestination(
        to_addrs=["a@b.c"],
        from_addr="b@b.c",
        subject_template="Rev {{ 1234.5|currency }}",
    )
    dest.prepare()
    image = tmp_path / "c.png"
    image.write_bytes(b"x")
    dest.send_image(DestinationContext(str(image), "Rev", "https://x", "Page"))
    smtp = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = smtp
    cm.__exit__.return_value = False
    with patch("app.destinations.email.smtplib.SMTP", return_value=cm):
        dest.teardown()
    msg = smtp.send_message.call_args.args[0]
    assert msg["Subject"] == "Rev $1,234.50"


def test_services_caption_renders_jinja(monkeypatch):
    from app.services.base import _resolve_caption

    item = {
        "card_name": "Revenue",
        "card_url": "https://x",
        "page_name": "Sales",
        "overrides": {"caption_text": "{{ card.name }} on {{ today }}"},
    }
    out = _resolve_caption(item, "Daily KPIs")
    assert out.startswith("Revenue on ")
    assert out != "{{ card.name }} on {{ today }}"


def test_services_caption_static_text_preserved():
    from app.services.base import _resolve_caption

    item = {
        "card_name": "Revenue",
        "card_url": "https://x",
        "page_name": "Sales",
        "overrides": {"caption_text": "Plain string with no jinja"},
    }
    assert _resolve_caption(item, "R") == "Plain string with no jinja"


def test_services_caption_falls_back_to_card_name_on_error():
    from app.services.base import _resolve_caption

    item = {
        "card_name": "Revenue",
        "overrides": {"caption_text": "{{ card.neme }}"},
    }
    # render_safe returns the fallback (card_name) when the template fails.
    assert _resolve_caption(item, "R") == "Revenue"
