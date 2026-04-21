"""Native HTTPS Domo engine.

Talks to the public Domo REST API (https://developer.domo.com) using
OAuth client-credentials. No JRE required, much faster cold start, and
the same interface as the JAR engine so swapping is transparent.

Endpoints used:
    * ``POST /oauth/token``                     -- bearer token
    * ``GET  /v1/datasets/{id}/data``           -- export dataset to CSV
    * ``POST /v1/cards/{id}/render``            -- render PNG of a card
    * ``GET  /v1/cards``                        -- paginated card list
    * ``GET  /v1/cards/{id}``                   -- single-card metadata

Endpoints with non-standard paths (Domo occasionally lives behind your
``DOMO_INSTANCE`` host instead of ``api.domo.com``) can be redirected via
``DOMO_API_HOST``.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any
from urllib.parse import urljoin

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.configuration.settings import get_env
from app.engines.base import (
    CardImageRequest,
    CardSummary,
    DomoEngine,
    DomoEngineError,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


_DEFAULT_API_HOST = "api.domo.com"
_TOKEN_PATH = "/oauth/token"
_TOKEN_REFRESH_BUFFER_SECONDS = 60
_DEFAULT_PAGE_LIMIT = 50


class RestEngineError(DomoEngineError):
    """Raised on REST API failures."""


class _RetryableRestError(RestEngineError):
    """Internal: lets tenacity know an error is worth retrying."""


class RestEngine(DomoEngine):
    """Domo engine that uses the public REST API."""

    key = "rest"
    label = "Domo REST API"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        api_host: str | None = None,
        scopes: Sequence[str] | None = None,
        request_timeout: int = 60,
        session: requests.Session | None = None,
    ) -> None:
        self._client_id_override = client_id
        self._client_secret_override = client_secret
        self._api_host = api_host or get_env("DOMO_API_HOST", default=_DEFAULT_API_HOST)
        self._scopes = list(scopes) if scopes else ["data", "user", "dashboard"]
        self._request_timeout = request_timeout
        self._session = session or requests.Session()
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0

    # ---- DomoEngine: required ----

    def export_dataset(self, dataset_id: str, output_path: str) -> None:
        """Stream the dataset's CSV export to disk."""

        url = self._url(f"/v1/datasets/{dataset_id}/data")
        params = {"includeHeader": "true", "fileName": f"{dataset_id}.csv"}
        response = self._http(
            "GET", url, params=params, headers={"Accept": "text/csv"}, stream=True
        )
        with open(output_path, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    fh.write(chunk)
        logger.info("REST engine exported dataset %s -> %s", dataset_id, output_path)

    def generate_card_image(
        self,
        card_id: int,
        output_path: str,
        width: int = 1100,
        height: int = 700,
        **opts: Any,
    ) -> None:
        """Render a card to PNG via the cards/render endpoint."""

        url = self._url(f"/v1/cards/{card_id}/render")
        payload = {
            "format": "png",
            "width": width,
            "height": height,
            **opts,
        }
        response = self._http(
            "POST",
            url,
            json=payload,
            headers={"Accept": "image/png"},
            stream=True,
        )
        with open(output_path, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    fh.write(chunk)

    def generate_card_images(self, requests_seq: Sequence[CardImageRequest]) -> None:
        """No batching savings on REST; HTTP keep-alive does the work."""

        for req in requests_seq:
            self.generate_card_image(req.card_id, req.output_path)

    # ---- DomoEngine: discovery ----

    def list_cards(
        self,
        page: str | None = None,
        tags: Sequence[str] | None = None,
        exclude_tags: Sequence[str] | None = None,
    ) -> list[CardSummary]:
        """List cards visible to the authenticated client."""

        url = self._url("/v1/cards")
        results: list[CardSummary] = []
        offset = 0
        limit = _DEFAULT_PAGE_LIMIT
        while True:
            response = self._http(
                "GET",
                url,
                params={"limit": limit, "offset": offset},
                headers={"Accept": "application/json"},
            )
            batch = response.json()
            if not batch:
                break
            for raw in batch:
                summary = _card_summary_from_payload(raw)
                if not _matches_filters(summary, page, tags, exclude_tags):
                    continue
                results.append(summary)
            if len(batch) < limit:
                break
            offset += limit
        return results

    def get_card_metadata(self, card_id: int) -> dict[str, Any]:
        url = self._url(f"/v1/cards/{card_id}")
        response = self._http("GET", url, headers={"Accept": "application/json"})
        return response.json()

    # ---- DomoEngine: health ----

    def _self_test(self) -> None:
        # Force a token fetch; cheap canary that auth + host are wired up.
        self._token()

    # ---- HTTP / auth ----

    def _client_id(self) -> str:
        return self._client_id_override or get_env("DOMO_CLIENT_ID", required=True)

    def _client_secret(self) -> str:
        return self._client_secret_override or get_env("DOMO_CLIENT_SECRET", required=True)

    def _url(self, path: str) -> str:
        host = self._api_host
        if not host.startswith("http"):
            host = f"https://{host}"
        if not host.endswith("/"):
            host = host + "/"
        return urljoin(host, path.lstrip("/"))

    def _token(self) -> str:
        """Return a valid access token, refreshing if it's about to expire."""

        now = time.time()
        if (
            self._access_token
            and now < self._access_token_expires_at - _TOKEN_REFRESH_BUFFER_SECONDS
        ):
            return self._access_token

        token_url = self._url(_TOKEN_PATH)
        scope = " ".join(self._scopes)
        try:
            response = self._session.get(
                token_url,
                params={"grant_type": "client_credentials", "scope": scope},
                auth=(self._client_id(), self._client_secret()),
                timeout=self._request_timeout,
            )
        except requests.RequestException as exc:
            raise RestEngineError(f"Token request failed: {exc}") from exc

        if response.status_code >= 400:
            raise RestEngineError(
                f"Token endpoint returned {response.status_code}: {response.text}"
            )
        data = response.json()
        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._access_token_expires_at = now + expires_in
        logger.debug("REST engine acquired bearer token, expires in %ss", expires_in)
        return self._access_token

    @retry(
        retry=retry_if_exception_type(_RetryableRestError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _http(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        merged = {"Authorization": f"Bearer {self._token()}"}
        if headers:
            merged.update(headers)
        try:
            response = self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers=merged,
                timeout=self._request_timeout,
                stream=stream,
            )
        except requests.RequestException as exc:
            raise _RetryableRestError(f"{method} {url} failed: {exc}") from exc

        # Treat 401 as token expiry: clear and retry.
        if response.status_code == 401:
            self._access_token = None
            raise _RetryableRestError(f"{method} {url} returned 401 (token expired)")
        if response.status_code in {429, 500, 502, 503, 504}:
            raise _RetryableRestError(
                f"{method} {url} returned {response.status_code}: {response.text[:300]}"
            )
        if response.status_code >= 400:
            raise RestEngineError(
                f"{method} {url} returned {response.status_code}: {response.text[:500]}"
            )
        return response


def _card_summary_from_payload(raw: dict[str, Any]) -> CardSummary:
    """Best-effort mapping from the REST card payload to :class:`CardSummary`."""

    pages = raw.get("pages") or []
    page_id = page_name = None
    if pages:
        page_id = str(pages[0].get("id", "")) or None
        page_name = pages[0].get("title")
    return CardSummary(
        card_id=int(raw.get("id", 0)),
        card_name=raw.get("title", "") or raw.get("name", ""),
        page_id=page_id,
        page_name=page_name,
        card_url=raw.get("urn") or raw.get("url"),
        tags=list(raw.get("tags", []) or []),
        extras=raw,
    )


def _matches_filters(
    summary: CardSummary,
    page: str | None,
    tags: Sequence[str] | None,
    exclude_tags: Sequence[str] | None,
) -> bool:
    if page and summary.page_name != page:
        return False
    if tags:
        if not all(t in summary.tags for t in tags):
            return False
    if exclude_tags:
        if any(t in summary.tags for t in exclude_tags):
            return False
    return True
