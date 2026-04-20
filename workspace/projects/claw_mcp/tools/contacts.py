"""Contacts tool — filter the developer list by function and seniority.

The Reo API returns the full developer list per account; this tool applies
client-side filtering on `designation` substring matches. Reo does not
expose a structured "function" or "seniority" field, so we pattern-match
against the free-text designation.

Keywords chosen for GTM relevance: "VP", "Head", "Director", "Lead" for
seniority; engineering/devops/platform terms for function. Tuned after the
live integration test — easy to adjust based on what the data actually shows.
"""

from __future__ import annotations

from typing import Any

from ..reo_client import ReoClient
from .activity import _slim_developer  # internal module boundary is fine here

# Keyword groups for client-side matching. Case-insensitive. Order matters
# only for readability — all groups are OR'd within, AND'd across.
SENIORITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "vp": ("vp", "vice president"),
    "c-level": ("cto", "cio", "ceo", "chief "),
    "director": ("director",),
    "head": ("head of",),
    "lead": ("lead ", " lead", "principal"),
    "senior": ("senior ", "sr. ", "sr ", "staff "),
}

FUNCTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "engineering": ("engineer", "engineering", "developer", "sde"),
    "devops": ("devops", "platform", "sre", "reliability", "infrastructure"),
    "data": ("data ", "analytics", "ml ", "machine learning"),
    "security": ("security", "infosec", "appsec"),
    "product": ("product manager", "product management", "pm "),
    "leadership": ("vp", "head of", "director", "cto", "chief"),
}


def _normalise(keyword_set: str | None) -> tuple[str, ...]:
    """Resolve a user-supplied filter name to its keyword tuple."""
    if not keyword_set:
        return ()
    key = keyword_set.strip().lower()
    return SENIORITY_KEYWORDS.get(key, ()) + FUNCTION_KEYWORDS.get(key, ())


def _matches(designation: str | None, keywords: tuple[str, ...]) -> bool:
    if not keywords:
        return True  # no filter → pass-through
    if not designation:
        return False
    haystack = designation.lower()
    return any(kw in haystack for kw in keywords)


def get_key_contacts(
    client: ReoClient,
    account_id: str,
    function: str | None = None,
    seniority: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Return developers at an account filtered by role.

    Args:
        client: Authenticated Reo client.
        account_id: Account UUID.
        function: Optional function filter. One of: engineering, devops,
            data, security, product, leadership. Case-insensitive.
            Unknown values become no-op (not an error — agent may pass
            free-form strings).
        seniority: Optional seniority filter. One of: vp, c-level,
            director, head, lead, senior. Same no-op behaviour for unknowns.
        limit: Max contacts to return (default 10, max 50).

    Returns:
        `{ "account_id", "filter", "matched_count", "developers": [...] }`
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    limit = min(limit, 50)

    func_kw = _normalise(function)
    sen_kw = _normalise(seniority)

    rows = client.list_account_developers(account_id, page=1)

    # AND across filter groups. Empty group = pass.
    matched = [
        d
        for d in rows
        if _matches(d.get("designation"), func_kw) and _matches(d.get("designation"), sen_kw)
    ]
    matched.sort(
        key=lambda d: d.get("activity_score_numeric") or 0.0,
        reverse=True,
    )

    return {
        "account_id": account_id,
        "filter": {"function": function, "seniority": seniority},
        "matched_count": len(matched),
        "developers": [_slim_developer(d) for d in matched[:limit]],
    }
