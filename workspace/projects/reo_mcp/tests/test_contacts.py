"""Tests for the get_key_contacts filter.

Reo doesn't expose structured role fields — we pattern-match on the free-text
`designation`. That makes correctness easy to regress, so the tests lock in:
- empty filter = pass-through
- function + seniority are AND'd (both must match)
- unknown filter values no-op rather than return zero rows
- sort order is by activity_score_numeric desc
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from reo_mcp.tools.contacts import _matches, _normalise, get_key_contacts

# ─────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────


def test_normalise_unknown_returns_empty() -> None:
    assert _normalise(None) == ()
    assert _normalise("") == ()
    assert _normalise("nonsense") == ()


def test_normalise_case_insensitive() -> None:
    assert _normalise("VP") == _normalise("vp") == _normalise("  Vp  ")


def test_matches_empty_keywords_passes_through() -> None:
    # No filter means every row passes — including rows without a designation.
    assert _matches("anything", ()) is True
    assert _matches(None, ()) is True


def test_matches_none_designation_with_filter_fails() -> None:
    assert _matches(None, ("director",)) is False


def test_matches_is_case_insensitive() -> None:
    assert _matches("Head Of Engineering", ("head of",)) is True
    assert _matches("DIRECTOR OF DATA", ("director",)) is True


# ─────────────────────────────────────────────────────────────
# get_key_contacts — filter + sort behaviour
# ─────────────────────────────────────────────────────────────


def _make_client(devs: list[dict[str, Any]]) -> MagicMock:
    """Build a MagicMock ReoClient returning the given developer list."""
    client = MagicMock()
    client.list_account_developers.return_value = devs
    return client


def test_no_filter_returns_all_sorted() -> None:
    devs = [
        {"id": "d1", "designation": "Engineer", "activity_score_numeric": 1.0},
        {"id": "d2", "designation": "VP Engineering", "activity_score_numeric": 9.0},
        {"id": "d3", "designation": "Director of Data", "activity_score_numeric": 5.0},
    ]
    result = get_key_contacts(_make_client(devs), "acc-1")
    assert result["matched_count"] == 3
    # Sort is by activity_score_numeric desc.
    ids = [d["developer_id"] for d in result["developers"]]
    assert ids == ["d2", "d3", "d1"]


def test_function_filter_narrows_to_engineering() -> None:
    devs = [
        {"id": "d1", "designation": "VP Engineering", "activity_score_numeric": 1.0},
        {"id": "d2", "designation": "Director of Marketing", "activity_score_numeric": 9.0},
        {"id": "d3", "designation": "Senior Software Engineer", "activity_score_numeric": 5.0},
    ]
    result = get_key_contacts(_make_client(devs), "acc-1", function="engineering")
    ids = {d["developer_id"] for d in result["developers"]}
    assert ids == {"d1", "d3"}


def test_function_and_seniority_are_and_combined() -> None:
    devs = [
        {"id": "d1", "designation": "VP Engineering", "activity_score_numeric": 3.0},
        {"id": "d2", "designation": "VP Marketing", "activity_score_numeric": 9.0},
        {"id": "d3", "designation": "Junior Software Engineer", "activity_score_numeric": 5.0},
    ]
    # Must be BOTH a VP AND in engineering → only d1.
    result = get_key_contacts(
        _make_client(devs),
        "acc-1",
        function="engineering",
        seniority="vp",
    )
    ids = [d["developer_id"] for d in result["developers"]]
    assert ids == ["d1"]


def test_unknown_filter_is_noop_not_error() -> None:
    # Agent may pass free-form strings; unknown values shouldn't crash or
    # zero out results — they're treated as "no filter".
    devs = [
        {"id": "d1", "designation": "Engineer", "activity_score_numeric": 1.0},
        {"id": "d2", "designation": "Director", "activity_score_numeric": 2.0},
    ]
    result = get_key_contacts(_make_client(devs), "acc-1", function="hallucination")
    assert result["matched_count"] == 2


def test_limit_is_applied() -> None:
    devs = [
        {"id": f"d{i}", "designation": "Engineer", "activity_score_numeric": float(i)}
        for i in range(20)
    ]
    result = get_key_contacts(_make_client(devs), "acc-1", limit=3)
    assert len(result["developers"]) == 3
    # Sort desc → top three are 19, 18, 17.
    assert [d["developer_id"] for d in result["developers"]] == ["d19", "d18", "d17"]


def test_limit_validation() -> None:
    import pytest

    with pytest.raises(ValueError):
        get_key_contacts(_make_client([]), "acc-1", limit=0)


def test_filter_metadata_is_echoed() -> None:
    # The agent uses this to explain its reasoning in the digest.
    result = get_key_contacts(
        _make_client([]),
        "acc-1",
        function="engineering",
        seniority="vp",
    )
    assert result["filter"] == {"function": "engineering", "seniority": "vp"}
