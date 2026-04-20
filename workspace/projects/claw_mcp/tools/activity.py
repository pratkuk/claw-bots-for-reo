"""Activity-related MCP tool implementations.

Four tools:
- `list_segments` — bootstrap helper
- `get_top_intent_accounts` — ranks accounts in a segment
- `get_account_activity_detail` — per-account signal stream
- `get_active_developers` — people at an account, ordered by activity

Each function returns a plain dict/list — FastMCP handles JSON serialisation.
The agent is expected to synthesise these into the Slack digest; raw responses
are never posted back to users.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from ..reo_client import ReoClient
from ..web3_domains import is_web3_domain

# Ranking: HIGH > MEDIUM > LOW > empty. See DECISIONS.md for the call.
ACTIVITY_WEIGHT: dict[str, int] = {
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "": 0,
}

# Option-3 confidence handling: empty activity OR zero devs → "low" confidence.
# The agent decides whether to include in the digest at render time; we surface
# the signal rather than hide the row. (Per decision in conversation: data hiding
# happens at render, not data layer.)


def _rank_key(account: dict[str, Any]) -> tuple[int, int]:
    activity = account.get("developer_activity") or ""
    weight = ACTIVITY_WEIGHT.get(activity, 0)
    devs = account.get("active_developers_count") or 0
    return (weight, devs)


def _confidence(account: dict[str, Any]) -> str:
    activity = account.get("developer_activity") or ""
    devs = account.get("active_developers_count") or 0
    if activity in ("HIGH", "MEDIUM") and devs > 0:
        return "high"
    if activity == "LOW" and devs > 0:
        return "medium"
    return "low"


def _slim_account(account: dict[str, Any]) -> dict[str, Any]:
    """Project a segment-account row to the fields the agent needs.

    Reo returns ~20 fields per account; the digest uses maybe 8. Trimming
    keeps tool responses legible when the agent inspects them directly.
    """
    return {
        "account_id": account.get("id"),
        "account_name": account.get("account_name"),
        "account_domain": account.get("account_domain"),
        "developer_activity": account.get("developer_activity") or "",
        "active_developers_count": account.get("active_developers_count") or 0,
        "customer_fit": account.get("customer_fit"),
        "industry": account.get("industry"),
        "country": account.get("country"),
        "annual_revenue": account.get("annual_revenue"),
        "last_activity_date": account.get("last_activity_date"),
        "tech_functions_count": account.get("tech_functions_count") or {},
        "confidence": _confidence(account),
    }


# ─────────────────────────────────────────────────────────────
# Tool 1: list_segments
# ─────────────────────────────────────────────────────────────


def list_segments(
    client: ReoClient,
    account_type_only: bool = True,
) -> list[dict[str, Any]]:
    """List segments available to the current API key.

    Args:
        client: Authenticated Reo client.
        account_type_only: If True (default), return only ACCOUNT-type
            segments. The digest workflow only operates on ACCOUNT segments;
            BUYER segments are for a different workflow.

    Returns:
        List of `{id, name, type, owner}` dicts.
    """
    segments = client.list_all_segments()
    if account_type_only:
        segments = [s for s in segments if s.get("type") == "ACCOUNT"]
    return [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "type": s.get("type"),
            "owner": s.get("owner"),
        }
        for s in segments
    ]


# ─────────────────────────────────────────────────────────────
# Tool 2: get_top_intent_accounts
# ─────────────────────────────────────────────────────────────


def get_top_intent_accounts(
    client: ReoClient,
    segment_id: str,
    limit: int = 10,
    web3_only: bool = True,
    extra_web3_domains: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Return the top-N accounts in a segment, ranked by intent.

    Ranking (locked, per DECISIONS.md):
        1. developer_activity weight (HIGH=3 > MEDIUM=2 > LOW=1 > empty=0)
        2. tie-break: active_developers_count descending

    Args:
        client: Authenticated Reo client.
        segment_id: ACCOUNT-type segment UUID.
        limit: Max accounts to return (default 10; hard-capped at 50).
        web3_only: If True (default), filter to domains in the Web3 allow-list.
        extra_web3_domains: User's runtime allow-list extensions from USER.md.

    Returns:
        `{ "segment_id", "total_scanned", "filtered_out", "accounts": [...] }`
        where each account is the slim-projected shape with a `confidence` tag.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    limit = min(limit, 50)

    raw = client.list_all_accounts_in_segment(segment_id)
    total_scanned = len(raw)

    pool = raw
    if web3_only:
        pool = [a for a in raw if is_web3_domain(a.get("account_domain"), extra_web3_domains)]

    filtered_out = total_scanned - len(pool)
    ranked = sorted(pool, key=_rank_key, reverse=True)
    top = [_slim_account(a) for a in ranked[:limit]]

    return {
        "segment_id": segment_id,
        "total_scanned": total_scanned,
        "filtered_out": filtered_out,
        "accounts": top,
    }


# ─────────────────────────────────────────────────────────────
# Tool 3: get_account_activity_detail
# ─────────────────────────────────────────────────────────────


def get_account_activity_detail(
    client: ReoClient,
    account_id: str,
    days: int = 7,
    max_rows: int = 200,
) -> dict[str, Any]:
    """Return activity events at an account within the last `days`.

    Args:
        client: Authenticated Reo client.
        account_id: Account UUID (from `get_top_intent_accounts`).
        days: Activity lookback window (default 7).
        max_rows: Upper bound on returned activity rows (default 200).

    Returns:
        `{ "account_id", "window_days", "by_type", "by_source", "events": [...] }`
        where `events` is ordered newest-first.
    """
    if days < 1:
        raise ValueError("days must be >= 1")

    # Reo returns 100-per-page; we fetch enough pages to cover max_rows.
    pages_needed = (max_rows + 99) // 100
    rows: list[dict[str, Any]] = []
    for page in range(1, pages_needed + 1):
        chunk = client.list_account_activities(account_id, page=page)
        rows.extend(chunk)
        if len(chunk) < 100:
            break

    cutoff = date.today() - timedelta(days=days)
    filtered: list[dict[str, Any]] = []
    for r in rows:
        activity_date = _parse_iso_date(r.get("activity_date"))
        if activity_date and activity_date >= cutoff:
            filtered.append(r)
        if len(filtered) >= max_rows:
            break

    by_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for r in filtered:
        t = r.get("activity_type") or "UNKNOWN"
        s = r.get("activity_source") or "UNKNOWN"
        by_type[t] = by_type.get(t, 0) + 1
        by_source[s] = by_source.get(s, 0) + 1

    filtered.sort(key=lambda r: r.get("activity_date") or "", reverse=True)

    return {
        "account_id": account_id,
        "window_days": days,
        "event_count": len(filtered),
        "by_type": by_type,
        "by_source": by_source,
        "events": [_slim_event(e) for e in filtered],
    }


def _slim_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "actor": event.get("actor"),
        "page": event.get("page"),
        "activity_type": event.get("activity_type"),
        "activity_source": event.get("activity_source"),
        "activity_date": event.get("activity_date"),
        "copied_text": event.get("copied_text"),
        "developer_designation": event.get("developer_designation"),
        "developer_linkedin": event.get("developer_linkedin"),
        "developer_id": event.get("developer_id"),
        "country": event.get("country"),
    }


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────
# Tool 4: get_active_developers
# ─────────────────────────────────────────────────────────────


def get_active_developers(
    client: ReoClient,
    account_id: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Return the most active developers at an account, ranked by score.

    Args:
        client: Authenticated Reo client.
        account_id: Account UUID.
        limit: How many developers to return (default 5, max 20).

    Returns:
        `{ "account_id", "developer_count", "developers": [...] }` with each
        developer projected to just the fields the agent needs.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    limit = min(limit, 20)

    rows = client.list_account_developers(account_id, page=1)
    rows.sort(
        key=lambda d: d.get("activity_score_numeric") or 0.0,
        reverse=True,
    )
    top = [_slim_developer(d) for d in rows[:limit]]

    return {
        "account_id": account_id,
        "developer_count": len(rows),
        "developers": top,
    }


def _slim_developer(dev: dict[str, Any]) -> dict[str, Any]:
    return {
        "developer_id": dev.get("id"),
        "developer_name": dev.get("developer_name"),
        "designation": dev.get("designation"),
        "developer_business_email": dev.get("developer_business_email"),
        "developer_linkedin": dev.get("developer_linkedin"),
        "developer_github": dev.get("developer_github"),
        "activity_score": dev.get("activity_score"),
        "activity_score_numeric": dev.get("activity_score_numeric"),
        "last_activity_date": dev.get("last_activity_date"),
        "city": dev.get("city"),
        "state": dev.get("state"),
        "country": dev.get("country"),
        "reo_developer_link": dev.get("reo_developer_link"),
    }
