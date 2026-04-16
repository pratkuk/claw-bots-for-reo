"""Tests for the ReoClient HTTP wrapper.

Uses respx to mock httpx at the network layer. We want to lock in the
error-handling contract that the tool layer depends on:
- 401/403 → ReoAuthError
- 404 → ReoNotFoundError
- 429 → retry honouring Retry-After, then ReoRateLimitError
- 5xx → retry with exp backoff, then ReoServerError
- Pagination walker stops on partial page, capped by PAGE_HARD_CAP
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from reo_mcp.reo_client import (
    ReoAuthError,
    ReoClient,
    ReoClientError,
    ReoNotFoundError,
    ReoRateLimitError,
    ReoServerError,
)

BASE = "https://integration.reo.dev"


@pytest.fixture
def client() -> ReoClient:
    return ReoClient(api_key="test-key", base_url=BASE, max_retries=2)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise time.sleep so retry tests run in milliseconds."""
    monkeypatch.setattr("reo_mcp.reo_client.time.sleep", lambda _: None)


# ─────────────────────────────────────────────────────────────
# Constructor
# ─────────────────────────────────────────────────────────────


def test_missing_api_key_raises() -> None:
    with pytest.raises(ValueError):
        ReoClient(api_key="")


def test_base_url_trailing_slash_stripped() -> None:
    c = ReoClient(api_key="k", base_url="https://example.com/")
    assert c._base_url == "https://example.com"


# ─────────────────────────────────────────────────────────────
# Happy paths
# ─────────────────────────────────────────────────────────────


@respx.mock
def test_list_segments_returns_data_array(client: ReoClient) -> None:
    respx.get(f"{BASE}/segments").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "s1", "name": "Web3"}]})
    )
    result = client.list_segments()
    assert result == [{"id": "s1", "name": "Web3"}]


@respx.mock
def test_list_accounts_in_segment_passes_id_in_path(client: ReoClient) -> None:
    route = respx.get(f"{BASE}/segment/abc-123/accounts").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    client.list_accounts_in_segment("abc-123")
    assert route.called


# ─────────────────────────────────────────────────────────────
# Error mapping
# ─────────────────────────────────────────────────────────────


@respx.mock
def test_401_raises_auth_error(client: ReoClient) -> None:
    respx.get(f"{BASE}/segments").mock(return_value=httpx.Response(401, json={}))
    with pytest.raises(ReoAuthError):
        client.list_segments()


@respx.mock
def test_403_raises_auth_error(client: ReoClient) -> None:
    respx.get(f"{BASE}/segments").mock(return_value=httpx.Response(403, json={}))
    with pytest.raises(ReoAuthError):
        client.list_segments()


@respx.mock
def test_404_raises_not_found(client: ReoClient) -> None:
    respx.get(f"{BASE}/segment/bad/accounts").mock(return_value=httpx.Response(404, json={}))
    with pytest.raises(ReoNotFoundError):
        client.list_accounts_in_segment("bad")


@respx.mock
def test_non_json_response_raises_generic_client_error(client: ReoClient) -> None:
    respx.get(f"{BASE}/segments").mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )
    with pytest.raises(ReoClientError):
        client.list_segments()


@respx.mock
def test_missing_data_key_raises_client_error(client: ReoClient) -> None:
    respx.get(f"{BASE}/segments").mock(return_value=httpx.Response(200, json={"wrong_key": []}))
    with pytest.raises(ReoClientError):
        client.list_segments()


# ─────────────────────────────────────────────────────────────
# 429 retry + backoff
# ─────────────────────────────────────────────────────────────


@respx.mock
def test_429_retries_then_succeeds(client: ReoClient) -> None:
    # First call: 429 with Retry-After: 0. Second: 200.
    respx.get(f"{BASE}/segments").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"data": [{"id": "s1"}]}),
        ]
    )
    result = client.list_segments()
    assert result == [{"id": "s1"}]


@respx.mock
def test_429_exhausts_retries_raises(client: ReoClient) -> None:
    # max_retries=2 → 3 total attempts, all 429.
    respx.get(f"{BASE}/segments").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )
    with pytest.raises(ReoRateLimitError):
        client.list_segments()


# ─────────────────────────────────────────────────────────────
# 5xx retry
# ─────────────────────────────────────────────────────────────


@respx.mock
def test_500_retries_then_succeeds(client: ReoClient) -> None:
    respx.get(f"{BASE}/segments").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"data": []}),
        ]
    )
    assert client.list_segments() == []


@respx.mock
def test_500_exhausts_retries_raises(client: ReoClient) -> None:
    respx.get(f"{BASE}/segments").mock(return_value=httpx.Response(502))
    with pytest.raises(ReoServerError):
        client.list_segments()


# ─────────────────────────────────────────────────────────────
# Pagination walker
# ─────────────────────────────────────────────────────────────


def _full_page(seed: int) -> list[dict[str, Any]]:
    return [{"id": f"row-{seed}-{i}"} for i in range(100)]


@respx.mock
def test_paginate_all_stops_on_partial_page(client: ReoClient) -> None:
    # page=1 → full (100 rows); page=2 → partial (42 rows) → stop.
    respx.get(f"{BASE}/segments", params={"page": "1"}).mock(
        return_value=httpx.Response(200, json={"data": _full_page(1)})
    )
    respx.get(f"{BASE}/segments", params={"page": "2"}).mock(
        return_value=httpx.Response(200, json={"data": [{"id": f"row-2-{i}"} for i in range(42)]})
    )
    rows = client.list_all_segments()
    assert len(rows) == 142


@respx.mock
def test_paginate_all_single_page(client: ReoClient) -> None:
    # First page already partial → stop immediately.
    respx.get(f"{BASE}/segments", params={"page": "1"}).mock(
        return_value=httpx.Response(200, json={"data": [{"id": "s1"}]})
    )
    rows = client.list_all_segments()
    assert rows == [{"id": "s1"}]
