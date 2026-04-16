"""Tests for the intent ranking rule and confidence tagging.

The ranking rule is a locked-in decision (DECISIONS.md §ranking):
    weight: HIGH=3 > MEDIUM=2 > LOW=1 > ""=0
    tie-break: active_developers_count descending

The subtle case is empty `developer_activity` — 161 of 297 accounts in the
seed segment had empty activity, so this isn't an edge case; it's the norm.
Tests lock the behaviour that empty sorts below LOW but is still returned
with a `confidence: "low"` tag (Option 3 from the design conversation).
"""

from __future__ import annotations

from reo_mcp.tools.activity import (
    _confidence,
    _rank_key,
    _slim_account,
)

# ─────────────────────────────────────────────────────────────
# _rank_key
# ─────────────────────────────────────────────────────────────


def test_rank_key_high_beats_medium() -> None:
    assert _rank_key({"developer_activity": "HIGH", "active_developers_count": 1}) > _rank_key(
        {"developer_activity": "MEDIUM", "active_developers_count": 50}
    )


def test_rank_key_medium_beats_low() -> None:
    assert _rank_key({"developer_activity": "MEDIUM", "active_developers_count": 0}) > _rank_key(
        {"developer_activity": "LOW", "active_developers_count": 999}
    )


def test_rank_key_low_beats_empty() -> None:
    assert _rank_key({"developer_activity": "LOW", "active_developers_count": 0}) > _rank_key(
        {"developer_activity": "", "active_developers_count": 999}
    )


def test_rank_key_tiebreak_by_dev_count() -> None:
    hi_big = {"developer_activity": "HIGH", "active_developers_count": 23}
    hi_small = {"developer_activity": "HIGH", "active_developers_count": 2}
    assert _rank_key(hi_big) > _rank_key(hi_small)


def test_rank_key_missing_fields_treated_as_empty() -> None:
    # Real API sometimes returns accounts with neither field; must not crash.
    assert _rank_key({}) == (0, 0)
    assert _rank_key({"developer_activity": None}) == (0, 0)
    assert _rank_key({"active_developers_count": None}) == (0, 0)


def test_rank_key_unknown_activity_value_falls_back_to_zero() -> None:
    # Defensive — if Reo ever adds a new tier we don't know, sort it at the
    # bottom rather than crash.
    assert _rank_key({"developer_activity": "EXTREME", "active_developers_count": 5}) == (0, 5)


# ─────────────────────────────────────────────────────────────
# _confidence
# ─────────────────────────────────────────────────────────────


def test_confidence_high_for_high_activity_with_devs() -> None:
    assert _confidence({"developer_activity": "HIGH", "active_developers_count": 3}) == "high"


def test_confidence_high_for_medium_activity_with_devs() -> None:
    assert _confidence({"developer_activity": "MEDIUM", "active_developers_count": 1}) == "high"


def test_confidence_medium_for_low_activity_with_devs() -> None:
    assert _confidence({"developer_activity": "LOW", "active_developers_count": 1}) == "medium"


def test_confidence_low_when_activity_empty() -> None:
    assert _confidence({"developer_activity": "", "active_developers_count": 10}) == "low"


def test_confidence_low_when_zero_devs() -> None:
    # High activity but zero active devs → weak signal; agent should probably
    # de-prioritise but we still return the row.
    assert _confidence({"developer_activity": "HIGH", "active_developers_count": 0}) == "low"


# ─────────────────────────────────────────────────────────────
# _slim_account
# ─────────────────────────────────────────────────────────────


def test_slim_account_projects_expected_fields() -> None:
    raw = {
        "id": "acc-1",
        "account_name": "Uniswap Labs",
        "account_domain": "uniswap.org",
        "developer_activity": "HIGH",
        "active_developers_count": 12,
        "customer_fit": "STRONG",
        "industry": "Financial Services",
        "country": "United States",
        "annual_revenue": "100M-500M",
        "last_activity_date": "2026-04-15",
        "tech_functions_count": {"engineering": 8},
        "extra_noise": "should be dropped",
    }
    slim = _slim_account(raw)
    assert slim["account_id"] == "acc-1"
    assert slim["account_name"] == "Uniswap Labs"
    assert slim["confidence"] == "high"
    assert "extra_noise" not in slim


def test_slim_account_handles_nulls() -> None:
    slim = _slim_account({"id": "acc-2"})
    assert slim["developer_activity"] == ""
    assert slim["active_developers_count"] == 0
    assert slim["tech_functions_count"] == {}
    assert slim["confidence"] == "low"
