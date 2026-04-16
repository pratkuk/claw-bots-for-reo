"""Web3 domain allow-list, loaded once at import time.

Reo has no native Web3 classification, so `web3_only=True` on
`get_top_intent_accounts` filters by domain against this list.

Source: docs/samples/web3_allowlist_seed.txt — seeded from the user's
own Reo segment (297 real Web3 orgs as of 2026-04-16). Users can
extend at runtime via the `/web3-domains +foo.xyz` slash command
(runtime extensions live in USER.md, not here).
"""

from __future__ import annotations

from pathlib import Path

_SEED_FILE = Path(__file__).resolve().parents[3] / "docs" / "samples" / "web3_allowlist_seed.txt"


def _load_seed() -> frozenset[str]:
    if not _SEED_FILE.exists():
        # Non-fatal — means the MCP server was deployed without the
        # seed file (shouldn't happen, but don't crash the agent).
        return frozenset()
    domains: set[str] = set()
    for line in _SEED_FILE.read_text().splitlines():
        stripped = line.strip().lower()
        if stripped and not stripped.startswith("#"):
            domains.add(stripped)
    return frozenset(domains)


SEED_WEB3_DOMAINS: frozenset[str] = _load_seed()


def is_web3_domain(
    domain: str | None,
    extra: frozenset[str] | set[str] | None = None,
) -> bool:
    """Return True if `domain` is in the allow-list (seed + optional extras).

    Case-insensitive. Trailing/leading whitespace stripped. Empty/None → False.

    `extra` is the user's runtime extensions (from USER.md), merged on top
    of the shipped seed.
    """
    if not domain:
        return False
    needle = domain.strip().lower()
    if needle in SEED_WEB3_DOMAINS:
        return True
    return bool(extra) and needle in {d.strip().lower() for d in extra}
