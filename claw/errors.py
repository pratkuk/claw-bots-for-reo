"""Map Reo client errors to user-facing Slack strings.

The MCP server (``claw_mcp/reo_client.py``) raises typed exceptions for
every Reo failure mode. The host translates them into short, actionable
messages the user sees in Slack. Tracebacks and raw response bodies
never leak into Slack.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Import the MCP server's Reo client exceptions. The package lives under
# workspace/projects/claw_mcp so we add that dir to sys.path once.
_PROJECTS = Path(__file__).resolve().parents[1] / "workspace" / "projects"
if str(_PROJECTS) not in sys.path:
    sys.path.insert(0, str(_PROJECTS))

import httpx  # noqa: E402
from claw_mcp.reo_client import (  # noqa: E402
    ReoAuthError,
    ReoClient,
    ReoClientError,
    ReoNotFoundError,
    ReoRateLimitError,
    ReoServerError,
)


def map_reo_error(exc: BaseException) -> str:
    """Return a single-line user-facing message for ``exc``.

    Never includes stack traces, URLs, or the raw response body.
    """
    if isinstance(exc, ReoAuthError):
        return "Invalid Reo API key — double-check it in Reo's dashboard."
    if isinstance(exc, ReoNotFoundError):
        return "That segment or tenant couldn't be found. Did it get deleted?"
    if isinstance(exc, ReoRateLimitError):
        return "Reo is rate-limiting us. Try again in a minute."
    if isinstance(exc, ReoServerError):
        return "Reo's API is having trouble. Try again shortly."
    if isinstance(exc, httpx.TimeoutException):
        return "Reo didn't respond in time. Try again."
    if isinstance(exc, ReoClientError):
        return "Couldn't reach Reo. Try again."
    return "Something went wrong talking to Reo. Try again."


def validate_api_key(api_key: str) -> None:
    """Ping Reo with ``api_key`` to confirm it works.

    Raises one of the ``Reo*Error`` types on failure; returns ``None`` on
    success. ``list_segments`` is the cheapest auth-requiring call — the
    response body is discarded, we only care that it doesn't throw.
    """
    with ReoClient(api_key=api_key) as client:
        client.list_segments()


def list_segments_safe(api_key: str) -> list[dict]:
    """Return ACCOUNT-type segments for ``api_key`` (single page).

    The digest pipeline only works on ACCOUNT segments — DEVELOPER and
    BUYER segments feed different workflows. Filtering here keeps the
    Slack picker from offering segments the agent can't use. A successful
    response also proves the key is valid (no separate ping needed).
    """
    with ReoClient(api_key=api_key) as client:
        return [s for s in client.list_segments() if s.get("type") == "ACCOUNT"]
