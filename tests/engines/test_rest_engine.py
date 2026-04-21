"""Tests for the native REST Domo engine.

Uses the ``responses`` library to mock the Domo HTTP API. We don't talk to
any real network -- every request is intercepted.
"""

from __future__ import annotations

import responses

from app.engines.rest import RestEngine

TOKEN_URL = "https://api.domo.com/oauth/token"


def _make_engine() -> RestEngine:
    return RestEngine(client_id="id", client_secret="secret", api_host="api.domo.com")


def _stub_token(rsps: responses.RequestsMock, expires_in: int = 3600) -> None:
    rsps.add(
        responses.GET,
        TOKEN_URL,
        json={"access_token": "tok-1", "expires_in": expires_in},
        status=200,
    )


@responses.activate
def test_token_is_acquired_via_get_with_basic_auth():
    _stub_token(responses)
    engine = _make_engine()
    token = engine._token()
    assert token == "tok-1"

    request = responses.calls[0].request
    assert "Authorization" in request.headers
    assert request.headers["Authorization"].startswith("Basic ")
    assert "client_credentials" in request.url


@responses.activate
def test_token_is_cached_until_expiry():
    _stub_token(responses, expires_in=3600)
    engine = _make_engine()
    engine._token()
    engine._token()
    # Only the first call hit the token endpoint.
    assert sum(1 for c in responses.calls if c.request.url.startswith(TOKEN_URL)) == 1


@responses.activate
def test_export_dataset_streams_response_to_file(tmp_path):
    _stub_token(responses)
    csv_payload = b"col_a,col_b\n1,2\n3,4\n"
    responses.add(
        responses.GET,
        "https://api.domo.com/v1/datasets/abc/data",
        body=csv_payload,
        status=200,
        content_type="text/csv",
    )

    out = tmp_path / "out.csv"
    engine = _make_engine()
    engine.export_dataset("abc", str(out))

    assert out.read_bytes() == csv_payload


@responses.activate
def test_generate_card_image_posts_render_payload(tmp_path):
    _stub_token(responses)
    png_bytes = b"\x89PNG fake card image"
    responses.add(
        responses.POST,
        "https://api.domo.com/v1/cards/42/render",
        body=png_bytes,
        status=200,
        content_type="image/png",
    )

    out = tmp_path / "card.png"
    engine = _make_engine()
    engine.generate_card_image(42, str(out), width=800, height=600)

    assert out.read_bytes() == png_bytes
    render_call = next(c for c in responses.calls if c.request.url.endswith("/render"))
    assert render_call.request.body  # JSON sent in body


@responses.activate
def test_retry_on_429_then_success(tmp_path):
    _stub_token(responses)
    responses.add(
        responses.GET,
        "https://api.domo.com/v1/datasets/x/data",
        json={"error": "rate limited"},
        status=429,
    )
    responses.add(
        responses.GET,
        "https://api.domo.com/v1/datasets/x/data",
        body=b"hello",
        status=200,
    )

    out = tmp_path / "out.csv"
    engine = _make_engine()
    engine.export_dataset("x", str(out))
    assert out.read_bytes() == b"hello"


@responses.activate
def test_4xx_other_than_401_raises():
    _stub_token(responses)
    responses.add(
        responses.GET,
        "https://api.domo.com/v1/cards/9",
        json={"error": "not found"},
        status=404,
    )
    engine = _make_engine()
    import pytest

    from app.engines.rest import RestEngineError

    with pytest.raises(RestEngineError, match="404"):
        engine.get_card_metadata(9)


@responses.activate
def test_list_cards_paginates_and_filters():
    _stub_token(responses)
    page_one = [
        {"id": 1, "title": "A", "tags": ["daily"], "pages": [{"id": 7, "title": "Sales"}]},
        {"id": 2, "title": "B", "tags": ["wip"], "pages": [{"id": 7, "title": "Sales"}]},
    ]
    page_two = [
        {"id": 3, "title": "C", "tags": ["daily", "kpi"], "pages": [{"id": 7, "title": "Sales"}]},
    ]
    # Response 1 returns 2 (== limit if we set it small), but default limit is 50.
    # Easier: have only one page response that's smaller than the page size.
    responses.add(
        responses.GET,
        "https://api.domo.com/v1/cards",
        json=page_one + page_two,
        status=200,
    )

    engine = _make_engine()
    results = engine.list_cards(page="Sales", tags=["daily"], exclude_tags=["wip"])
    ids = sorted(r.card_id for r in results)
    assert ids == [1, 3]


@responses.activate
def test_url_helper_handles_missing_scheme():
    _stub_token(responses)
    engine = RestEngine(client_id="id", client_secret="s", api_host="custom.domo.com")
    assert engine._url("/v1/datasets") == "https://custom.domo.com/v1/datasets"
