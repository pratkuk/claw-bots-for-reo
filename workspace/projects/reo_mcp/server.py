"""FastMCP server entry point — exposes 5 Reo tools to the OpenClaw agent.

Run (Pinata hosts):
    python3 server.py --host 0.0.0.0 --port 8787

Run (local dev):
    python3 server.py              # defaults to 127.0.0.1:8787 for safety

Env vars (loaded from .env at repo root):
    REO_API_KEY                required
    REO_API_BASE_URL           optional, defaults to https://integration.reo.dev
    REO_MCP_INTERNAL_TOKEN     required when serving over HTTP — shared secret
                               with the OpenClaw agent for the /mcp route
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP

# Allow running as a script: `python3 server.py` from inside reo-mcp/.
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

# ruff: noqa: E402 — imports after sys.path manipulation, intentional.
from reo_mcp.reo_client import ReoClient  # type: ignore[import-not-found]
from reo_mcp.tools.activity import (  # type: ignore[import-not-found]
    get_account_activity_detail as _get_account_activity_detail,
)
from reo_mcp.tools.activity import (  # type: ignore[import-not-found]
    get_active_developers as _get_active_developers,
)
from reo_mcp.tools.activity import (  # type: ignore[import-not-found]
    get_top_intent_accounts as _get_top_intent_accounts,
)
from reo_mcp.tools.activity import (  # type: ignore[import-not-found]
    list_segments as _list_segments,
)
from reo_mcp.tools.contacts import (  # type: ignore[import-not-found]
    get_key_contacts as _get_key_contacts,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Env / client bootstrap
# ─────────────────────────────────────────────────────────────


def _load_env() -> tuple[str, str, str | None]:
    """Find .env by walking up from this file, load it, return (key, base, token)."""
    for candidate in (_HERE, *_HERE.parents):
        env_file = candidate / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
            break

    api_key = os.environ.get("REO_API_KEY", "").strip()
    if not api_key or api_key.startswith("replace_with"):
        sys.exit("FATAL: REO_API_KEY is not set — check .env at repo root")

    base_url = os.environ.get("REO_API_BASE_URL", "https://integration.reo.dev").strip().rstrip("/")
    internal_token = os.environ.get("REO_MCP_INTERNAL_TOKEN") or None
    return api_key, base_url, internal_token


# Module-level client — one httpx.Client pooled across tool calls.
# Rebuilt in tests via dependency injection (see tests/conftest.py).
_CLIENT: ReoClient | None = None


def _get_client() -> ReoClient:
    global _CLIENT
    if _CLIENT is None:
        api_key, base_url, _ = _load_env()
        _CLIENT = ReoClient(api_key=api_key, base_url=base_url)
    return _CLIENT


# ─────────────────────────────────────────────────────────────
# FastMCP server + tool registration
# ─────────────────────────────────────────────────────────────

mcp: FastMCP = FastMCP(
    name="reo-mcp",
    instructions=(
        "Tools for Reo.Dev revenue intelligence. Use list_segments to discover "
        "available segments, then get_top_intent_accounts to rank accounts "
        "within a segment. Follow up with get_account_activity_detail, "
        "get_active_developers, or get_key_contacts for per-account drill-down."
    ),
)


@mcp.tool
def list_segments(account_type_only: bool = True) -> list[dict]:
    """List segments available to the current Reo API key.

    Args:
        account_type_only: If True (default), return only ACCOUNT-type segments
            (which is what the digest workflow operates on). BUYER-type and
            other segments are filtered out.

    Returns:
        A list of `{id, name, type, owner}` dicts. Use the `id` as the
        `segment_id` for get_top_intent_accounts.
    """
    return _list_segments(_get_client(), account_type_only=account_type_only)


@mcp.tool
def get_top_intent_accounts(
    segment_id: str,
    limit: int = 10,
    web3_only: bool = True,
) -> dict:
    """Return the top-N accounts in a segment, ranked by developer intent.

    Ranking: HIGH > MEDIUM > LOW > empty developer_activity; tie-break by
    active_developers_count (descending). Each returned account carries a
    `confidence` tag (high/medium/low) — the agent decides whether to
    include low-confidence rows in the digest.

    Args:
        segment_id: ACCOUNT-type segment UUID (from list_segments).
        limit: Max accounts to return (1-50, default 10).
        web3_only: If True (default), filter to the shipped Web3 allow-list.

    Returns:
        `{segment_id, total_scanned, filtered_out, accounts}` where each
        account has {account_id, account_name, account_domain,
        developer_activity, active_developers_count, customer_fit, industry,
        country, annual_revenue, last_activity_date, tech_functions_count,
        confidence}.
    """
    return _get_top_intent_accounts(
        _get_client(),
        segment_id=segment_id,
        limit=limit,
        web3_only=web3_only,
    )


@mcp.tool
def get_account_activity_detail(account_id: str, days: int = 7) -> dict:
    """Return activity events at an account within the last `days`.

    Args:
        account_id: Account UUID (from get_top_intent_accounts).
        days: Lookback window in days (default 7).

    Returns:
        `{account_id, window_days, event_count, by_type, by_source, events}`.
        `by_type` counts PAGE_VISIT, GITHUB, COPY_COMMAND, IDENTITY_CAPTURE etc.
        `events` is ordered newest-first with developer attribution.
    """
    return _get_account_activity_detail(_get_client(), account_id=account_id, days=days)


@mcp.tool
def get_active_developers(account_id: str, limit: int = 5) -> dict:
    """Return the most active developers at an account.

    Args:
        account_id: Account UUID.
        limit: Developers to return (1-20, default 5), ordered by
            activity_score_numeric descending.

    Returns:
        `{account_id, developer_count, developers}` with contacts including
        LinkedIn URL, business email (when available), designation, and
        city/state/country.
    """
    return _get_active_developers(_get_client(), account_id=account_id, limit=limit)


@mcp.tool
def get_key_contacts(
    account_id: str,
    function: str | None = None,
    seniority: str | None = None,
    limit: int = 10,
) -> dict:
    """Filter developers at an account by function and/or seniority.

    Both filters match substrings in the developer's `designation` field
    (Reo has no structured function/seniority enum).

    Args:
        account_id: Account UUID.
        function: One of "engineering", "devops", "data", "security",
            "product", "leadership". Unknown values pass through as no-op.
        seniority: One of "vp", "c-level", "director", "head", "lead",
            "senior". Unknown values pass through as no-op.
        limit: Max contacts (1-50, default 10).

    Returns:
        `{account_id, filter, matched_count, developers}`.
    """
    return _get_key_contacts(
        _get_client(),
        account_id=account_id,
        function=function,
        seniority=seniority,
        limit=limit,
    )


# ─────────────────────────────────────────────────────────────
# HTTP entrypoint
# ─────────────────────────────────────────────────────────────


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    parser = argparse.ArgumentParser(description="Reo MCP server")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address (use 0.0.0.0 inside Pinata container)",
    )
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--transport",
        default="http",
        choices=["http", "stdio"],
        help="http for Pinata routes, stdio for local MCP-client testing",
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="HTTP path prefix (Pinata gateway rewrites this away)",
    )
    args = parser.parse_args()

    # Sanity: validate the API key exists before binding the port.
    _load_env()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        logger.info("starting Reo MCP server on %s:%d%s", args.host, args.port, args.path)
        mcp.run(
            transport="http",
            host=args.host,
            port=args.port,
            path=args.path,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
