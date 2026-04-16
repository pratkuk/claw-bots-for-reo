"""Tests for the Web3 domain allow-list filter.

Focus areas:
- Case-insensitivity and whitespace handling (Reo returns domains as-entered;
  we don't want "Uniswap.ORG " to miss).
- Empty / None inputs must return False (never raise).
- Runtime extras must merge with the shipped seed, not replace it.
"""

from __future__ import annotations

from reo_mcp.web3_domains import SEED_WEB3_DOMAINS, is_web3_domain


def test_seed_loaded_non_empty() -> None:
    # If the seed file is missing at deploy time we fall back to empty,
    # but in the repo it must be populated — guard against regressions
    # where the seed file moves and loading silently returns frozenset().
    assert len(SEED_WEB3_DOMAINS) > 100


def test_empty_and_none_return_false() -> None:
    assert is_web3_domain(None) is False
    assert is_web3_domain("") is False
    assert is_web3_domain("   ") is False


def test_case_insensitive_match() -> None:
    # Pick any known seed entry and check upper/mixed case pass through.
    sample = next(iter(SEED_WEB3_DOMAINS))
    assert is_web3_domain(sample.upper()) is True
    assert is_web3_domain(f"  {sample}  ") is True


def test_non_web3_domain_returns_false() -> None:
    assert is_web3_domain("microsoft.com") is False
    assert is_web3_domain("example.invalid") is False


def test_extras_merge_with_seed() -> None:
    # Runtime extension → True even if not in seed.
    assert is_web3_domain("novel-web3-startup.xyz") is False
    assert (
        is_web3_domain(
            "novel-web3-startup.xyz",
            extra={"novel-web3-startup.xyz"},
        )
        is True
    )


def test_extras_are_case_normalised() -> None:
    # USER.md may store extras however the user typed them; we should still
    # match regardless of case.
    assert is_web3_domain("Foo.Bar", extra={"FOO.BAR"}) is True
    assert is_web3_domain("foo.bar", extra={"  FOO.BAR  "}) is True


def test_extras_do_not_shadow_seed() -> None:
    sample = next(iter(SEED_WEB3_DOMAINS))
    # Even when extras are passed, a seeded domain should still match.
    assert is_web3_domain(sample, extra={"unrelated.xyz"}) is True
