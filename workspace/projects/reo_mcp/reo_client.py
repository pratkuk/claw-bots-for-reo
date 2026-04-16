"""Thin HTTP client for the Reo REST API.

Design goals:
- One place for auth, retry, rate-limit handling — tool modules stay focused
  on shaping responses for the agent, not on HTTP mechanics.
- Honest errors: every failure path raises a typed exception with an
  actionable message. Tool layer decides how to surface to the agent.
- No silent fallbacks. If Reo returns 404 or 403, the caller sees it.

Endpoints used (per docs/api-exploration.md):
  GET /segments
  GET /segment/{id}/accounts
  GET /account/{id}/activities
  GET /account/{id}/developers
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────


class ReoClientError(Exception):
    """Base for all Reo client failures."""


class ReoAuthError(ReoClientError):
    """401/403 — API key missing, wrong, or insufficient access."""


class ReoNotFoundError(ReoClientError):
    """404 — resource does not exist (bad segment ID, bad account ID)."""


class ReoRateLimitError(ReoClientError):
    """429 — rate limit exceeded after all retries."""


class ReoServerError(ReoClientError):
    """5xx — Reo-side failure; caller should back off and retry later."""


# ─────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────


class ReoClient:
    """Synchronous HTTP client for Reo's integration API.

    Sync (not async) because:
    - FastMCP tools are simple request/response; async adds ceremony.
    - The OpenClaw runtime calls one tool at a time per agent turn.
    - Trivial to swap to httpx.AsyncClient later if concurrency helps.
    """

    DEFAULT_TIMEOUT = 15.0
    DEFAULT_MAX_RETRIES = 3
    PAGE_HARD_CAP = 50  # safety net for paginate_all

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://integration.reo.dev",
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"x-api-key": api_key},
            base_url=self._base_url,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ReoClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ─────────────────────────────────────────────────────────
    # Public endpoint wrappers
    # ─────────────────────────────────────────────────────────

    def list_segments(self, page: int = 1) -> list[dict[str, Any]]:
        """`GET /segments` — returns one page of segments."""
        return self._get_data(f"/segments?page={page}")

    def list_all_segments(self) -> list[dict[str, Any]]:
        """Walk pagination and return every segment."""
        return self._paginate_all("/segments")

    def list_accounts_in_segment(self, segment_id: str, page: int = 1) -> list[dict[str, Any]]:
        """`GET /segment/{id}/accounts` — single page."""
        return self._get_data(f"/segment/{segment_id}/accounts?page={page}")

    def list_all_accounts_in_segment(self, segment_id: str) -> list[dict[str, Any]]:
        """Walk pagination across all pages for a segment."""
        return self._paginate_all(f"/segment/{segment_id}/accounts")

    def list_account_activities(self, account_id: str, page: int = 1) -> list[dict[str, Any]]:
        """`GET /account/{id}/activities` — one page of activity events."""
        return self._get_data(f"/account/{account_id}/activities?page={page}")

    def list_account_developers(self, account_id: str, page: int = 1) -> list[dict[str, Any]]:
        """`GET /account/{id}/developers` — one page of developers."""
        return self._get_data(f"/account/{account_id}/developers?page={page}")

    # ─────────────────────────────────────────────────────────
    # Low-level
    # ─────────────────────────────────────────────────────────

    def _get(self, path: str) -> httpx.Response:
        """GET with retry on 429 (honouring Retry-After) and 5xx."""
        for attempt in range(self._max_retries + 1):
            response = self._client.get(path)

            if response.status_code == 429:
                if attempt == self._max_retries:
                    raise ReoRateLimitError(
                        f"rate-limited on {path} after {self._max_retries} retries"
                    )
                sleep_for = self._retry_after_seconds(response, attempt)
                logger.warning(
                    "rate-limited on %s (attempt %d/%d) — sleeping %.1fs",
                    path,
                    attempt + 1,
                    self._max_retries,
                    sleep_for,
                )
                time.sleep(sleep_for)
                continue

            if 500 <= response.status_code < 600:
                if attempt == self._max_retries:
                    raise ReoServerError(f"server error {response.status_code} on {path}")
                sleep_for = min(2**attempt, 10)
                logger.warning(
                    "server error %d on %s (attempt %d/%d) — sleeping %ds",
                    response.status_code,
                    path,
                    attempt + 1,
                    self._max_retries,
                    sleep_for,
                )
                time.sleep(sleep_for)
                continue

            return response

        # Unreachable — loop above always either returns or raises.
        raise ReoClientError("retry loop exited unexpectedly")  # pragma: no cover

    def _get_data(self, path: str) -> list[dict[str, Any]]:
        """GET, raise on auth/404, return the `data` array."""
        response = self._get(path)

        if response.status_code in (401, 403):
            raise ReoAuthError(
                f"{response.status_code} on {path}: check REO_API_KEY is set and valid"
            )
        if response.status_code == 404:
            raise ReoNotFoundError(f"404 on {path}: resource not found")
        if response.status_code >= 400:
            raise ReoClientError(
                f"unexpected status {response.status_code} on {path}: {response.text[:200]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ReoClientError(f"non-JSON response from {path}") from exc

        data = body.get("data")
        if not isinstance(data, list):
            raise ReoClientError(f"response from {path} missing 'data' list")
        return data

    def _paginate_all(self, base_path: str) -> list[dict[str, Any]]:
        """Walk pages until one returns < a full page of rows.

        Reo uses `?page=N`; responses include `total_pages`. We use the
        response-size heuristic as a safety net since pagination details
        aren't guaranteed stable across endpoints.
        """
        joiner = "&" if "?" in base_path else "?"
        all_rows: list[dict[str, Any]] = []
        for page in range(1, self.PAGE_HARD_CAP + 1):
            rows = self._get_data(f"{base_path}{joiner}page={page}")
            all_rows.extend(rows)
            if len(rows) < 100:  # last partial page
                return all_rows
        logger.warning(
            "paginate_all hit hard cap %d on %s — returning partial result",
            self.PAGE_HARD_CAP,
            base_path,
        )
        return all_rows

    @staticmethod
    def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
        """Compute backoff from Retry-After or X-RateLimit-Reset, else exp."""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass

        reset = response.headers.get("X-RateLimit-Reset")
        if reset:
            try:
                # Reset header may be epoch seconds or delta seconds —
                # treat numbers > now as epoch, else delta.
                reset_val = float(reset)
                now = time.time()
                delta = reset_val - now if reset_val > now else reset_val
                return max(delta, 1.0)
            except ValueError:
                pass

        return float(min(2**attempt, 30))
