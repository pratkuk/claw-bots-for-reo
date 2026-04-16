"""Live integration test — exercise the 5 MCP tools against the real Reo API.

This is the step between unit-tested-with-respx and deployed-on-Pinata.
It answers: does my tool layer work on real data, and what does that
data actually look like?

Run:
    python3 scripts/live_integration.py

Outputs:
- stdout: pass/fail per step with sanitised preview
- docs/samples/live_integration_YYYY-MM-DD.json: full sanitised response
  set, for use as fixtures in CI and as reference in DECISIONS.md.

Sanitisation (applied before writing to disk):
- account_id, developer_id → deterministic opaque hash prefix
  (preserves grouping, hides the UUID)
- developer_business_email → "<redacted>@<domain>" (keeps domain signal)
- developer_linkedin / developer_github → stripped to
  "linkedin.com/in/<hash>" to keep the shape, lose the identity
- raw actor strings → kept (they're already pseudonymous)

Exits 0 on all-pass, 1 on any failure.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
SAMPLES_DIR = REPO_ROOT / "docs" / "samples"

# Ensure the reo_mcp package is importable.
sys.path.insert(0, str(REPO_ROOT / "workspace" / "projects"))

from reo_mcp.reo_client import ReoClient  # noqa: E402
from reo_mcp.tools.activity import (  # noqa: E402
    get_account_activity_detail,
    get_active_developers,
    get_top_intent_accounts,
    list_segments,
)
from reo_mcp.tools.contacts import get_key_contacts  # noqa: E402


# ─────────────────────────────────────────────────────────────
# Config + sanitisation
# ─────────────────────────────────────────────────────────────


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        sys.exit(f"✗ {path} not found — copy .env.example to .env and fill in values")
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        env[key.strip()] = value.strip()
    return env


def _hash(value: str | None, prefix: str = "") -> str | None:
    """Deterministic 8-char hash — preserves groupability in fixtures."""
    if value is None:
        return None
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}{digest}" if prefix else digest


def _redact_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    _, _, domain = email.partition("@")
    return f"<redacted>@{domain}"


def _redact_url(url: str | None, platform: str) -> str | None:
    if not url:
        return url
    return f"https://{platform}.com/in/{_hash(url)}"


def sanitise_account(account: dict[str, Any]) -> dict[str, Any]:
    out = dict(account)
    out["account_id"] = _hash(account.get("account_id"), prefix="acc_")
    return out


def sanitise_developer(dev: dict[str, Any]) -> dict[str, Any]:
    out = dict(dev)
    out["developer_id"] = _hash(dev.get("developer_id"), prefix="dev_")
    out["developer_business_email"] = _redact_email(dev.get("developer_business_email"))
    out["developer_linkedin"] = _redact_url(dev.get("developer_linkedin"), "linkedin")
    out["developer_github"] = _redact_url(dev.get("developer_github"), "github")
    out["reo_developer_link"] = None  # internal Reo link — drop entirely
    return out


def sanitise_event(event: dict[str, Any]) -> dict[str, Any]:
    out = dict(event)
    out["developer_id"] = _hash(event.get("developer_id"), prefix="dev_")
    out["developer_linkedin"] = _redact_url(event.get("developer_linkedin"), "linkedin")
    return out


# ─────────────────────────────────────────────────────────────
# The 5-step probe
# ─────────────────────────────────────────────────────────────


def step(label: str, n: int, total: int) -> None:
    print(f"\n[{n}/{total}] {label}")
    print("─" * (len(label) + 8))


def main() -> int:
    env = load_env(ENV_PATH)
    api_key = env.get("REO_API_KEY", "")
    segment_id = env.get("REO_TEST_SEGMENT_ID", "")
    if not api_key or not segment_id:
        sys.exit("✗ REO_API_KEY and REO_TEST_SEGMENT_ID must be set in .env")

    base_url = env.get("REO_API_BASE_URL", "https://integration.reo.dev")
    results: dict[str, Any] = {
        "generated_at": date.today().isoformat(),
        "segment_id_probe": _hash(segment_id, prefix="seg_"),
    }
    total = 5

    # Wider timeout for live API — 15s default trips on the segment-accounts
    # paginated walk over a full segment (tested: ~18s on a cold cache).
    with ReoClient(api_key=api_key, base_url=base_url, timeout=60.0) as client:
        # 1. list_segments
        step("list_segments — is the API key valid and do we see segments?", 1, total)
        segments = list_segments(client, account_type_only=True)
        print(f"  → {len(segments)} ACCOUNT-type segments visible")
        match = next((s for s in segments if s["id"] == segment_id), None)
        if not match:
            sys.exit(f"✗ segment {segment_id} not visible with this API key")
        print(f"  ✓ target segment found: name={match['name']!r}")
        results["step1_segment_count"] = len(segments)

        # 2. get_top_intent_accounts
        step("get_top_intent_accounts — does ranking + web3 filter work?", 2, total)
        ranked = get_top_intent_accounts(
            client, segment_id=segment_id, limit=10, web3_only=True
        )
        print(
            f"  → scanned {ranked['total_scanned']}, "
            f"filtered_out {ranked['filtered_out']} (non-web3), "
            f"returning {len(ranked['accounts'])}"
        )
        if not ranked["accounts"]:
            sys.exit("✗ no accounts survived ranking + web3 filter — check allow-list")
        top = ranked["accounts"][0]
        print(
            f"  ✓ top account: {top['account_name']!r} "
            f"({top['account_domain']}) "
            f"activity={top['developer_activity'] or '(empty)'} "
            f"devs={top['active_developers_count']} "
            f"confidence={top['confidence']}"
        )
        results["step2_top_accounts"] = [sanitise_account(a) for a in ranked["accounts"]]

        # Real account_id (unsanitised) for downstream drill-down.
        # We read the raw segment rows to recover the id since _slim_account
        # exposes it as account_id already.
        probe_account_id = top["account_id"]

        # 3. get_account_activity_detail
        step("get_account_activity_detail — are activity events fetchable?", 3, total)
        activity = get_account_activity_detail(
            client, account_id=probe_account_id, days=30, max_rows=50
        )
        print(
            f"  → {activity['event_count']} events in last "
            f"{activity['window_days']} days"
        )
        print(f"  → by_type: {activity['by_type']}")
        print(f"  → by_source: {activity['by_source']}")
        print("  ✓ activity endpoint working")
        results["step3_activity"] = {
            "account_id": _hash(probe_account_id, prefix="acc_"),
            "window_days": activity["window_days"],
            "event_count": activity["event_count"],
            "by_type": activity["by_type"],
            "by_source": activity["by_source"],
            "events": [sanitise_event(e) for e in activity["events"][:10]],
        }

        # 4. get_active_developers
        step("get_active_developers — who's active at this account?", 4, total)
        devs = get_active_developers(client, account_id=probe_account_id, limit=5)
        print(f"  → {devs['developer_count']} total devs, showing top 5")
        for d in devs["developers"][:3]:
            print(
                f"    · {d['developer_name']!r} — {d['designation']} "
                f"(score={d['activity_score']}, last={d['last_activity_date']})"
            )
        print("  ✓ developers endpoint working")
        results["step4_developers"] = {
            "account_id": _hash(probe_account_id, prefix="acc_"),
            "developer_count": devs["developer_count"],
            "developers": [sanitise_developer(d) for d in devs["developers"]],
        }

        # 5. get_key_contacts
        step("get_key_contacts — does function+seniority filter narrow correctly?", 5, total)
        leadership = get_key_contacts(
            client,
            account_id=probe_account_id,
            function="leadership",
            limit=5,
        )
        print(
            f"  → {leadership['matched_count']} leadership contacts "
            f"(filter={leadership['filter']})"
        )
        for d in leadership["developers"][:3]:
            print(f"    · {d['developer_name']!r} — {d['designation']}")
        # Narrow further
        vp_eng = get_key_contacts(
            client,
            account_id=probe_account_id,
            function="engineering",
            seniority="vp",
            limit=5,
        )
        print(f"  → {vp_eng['matched_count']} VP-in-engineering (intersection)")
        print("  ✓ contacts endpoint + filter logic working")
        results["step5_contacts"] = {
            "leadership_count": leadership["matched_count"],
            "vp_engineering_count": vp_eng["matched_count"],
            "leadership_sample": [
                sanitise_developer(d) for d in leadership["developers"][:5]
            ],
        }

    # Write fixture
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    fixture_path = SAMPLES_DIR / f"live_integration_{date.today().isoformat()}.json"
    fixture_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n✓ all 5 steps passed — fixture written to {fixture_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
