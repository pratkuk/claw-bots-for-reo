"""Reo error mapping — every error path produces a short Slack-safe message."""

from __future__ import annotations

import httpx
import pytest
from claw_mcp.reo_client import (
    ReoAuthError,
    ReoClientError,
    ReoNotFoundError,
    ReoRateLimitError,
    ReoServerError,
)

from claw.errors import map_reo_error


@pytest.mark.parametrize(
    "exc,expected_substr",
    [
        (ReoAuthError("401"), "Invalid Reo API key"),
        (ReoNotFoundError("404"), "couldn't be found"),
        (ReoRateLimitError("429"), "rate-limiting"),
        (ReoServerError("500"), "having trouble"),
        (httpx.TimeoutException("slow"), "didn't respond in time"),
        (ReoClientError("generic"), "Couldn't reach Reo"),
        (RuntimeError("surprise"), "Something went wrong"),
    ],
)
def test_map_reo_error_messages(exc: BaseException, expected_substr: str) -> None:
    msg = map_reo_error(exc)
    assert expected_substr in msg
    # Never leak internals.
    assert "Traceback" not in msg
    assert "\n" not in msg, "messages must fit on one Slack line"


def test_map_reo_error_order_specific_before_base() -> None:
    # ReoAuthError is-a ReoClientError; check we get the specific message.
    assert "Invalid" in map_reo_error(ReoAuthError("x"))
