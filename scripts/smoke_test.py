"""Reo API smoke test — verify .env credentials + map the endpoint surface.

Run:  python3 scripts/smoke_test.py
Needs: .env at repo root with REO_API_KEY filled in.

Exits 0 on success, 1 on any failed probe. Safe to re-run.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import urllib.request
import urllib.error

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"


def load_env(path: Path) -> dict[str, str]:
    """Lightweight .env loader — no dependency on python-dotenv."""
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


def get(url: str, api_key: str) -> tuple[int, Any]:
    """GET a Reo endpoint. Returns (status, parsed_json | raw_text)."""
    req = urllib.request.Request(url, headers={"x-api-key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        return 0, f"network error: {e}"
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, body


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "✓" if ok else "✗"
    print(f"{mark} {label}" + (f" — {detail}" if detail else ""))


def main() -> int:
    print(f"Loading env from {ENV_PATH}")
    env = load_env(ENV_PATH)

    api_key = env.get("REO_API_KEY", "")
    base = env.get("REO_API_BASE_URL", "https://integration.reo.dev").rstrip("/")

    if not api_key or api_key.startswith("replace_with"):
        sys.exit("✗ REO_API_KEY is empty or still a placeholder in .env")

    failures: list[str] = []

    # Probe 1: auth works + list segments
    print("\n── Probe 1: GET /segments ──")
    status, body = get(f"{base}/segments?page=1", api_key)
    ok = status == 200 and isinstance(body, dict) and "data" in body
    check("auth + /segments", ok, f"status={status}")
    if not ok:
        failures.append("/segments")
        print(json.dumps(body, indent=2)[:400] if isinstance(body, dict) else str(body)[:400])
        return _finish(failures)

    segments = body["data"]
    account_segs = [s for s in segments if s.get("type") == "ACCOUNT"]
    print(f"  → {len(segments)} segments total, {len(account_segs)} ACCOUNT-type")

    if not account_segs:
        print("  ⚠ no ACCOUNT-type segments — create one in Reo UI before building further")
        return _finish(failures)

    target_seg = account_segs[0]
    seg_id = target_seg["id"]
    print(f"  → using segment '{target_seg['name']}' ({seg_id})")

    # Probe 2: accounts in that segment
    print(f"\n── Probe 2: GET /segment/{{id}}/accounts ──")
    status, body = get(f"{base}/segment/{seg_id}/accounts?page=1", api_key)
    ok = status == 200 and isinstance(body, dict) and body.get("data")
    check("/segment/{id}/accounts", ok, f"status={status}")
    if not ok:
        failures.append("/segment/{id}/accounts")
        return _finish(failures)

    accounts = body["data"]
    print(f"  → {len(accounts)} accounts in this segment")
    top = accounts[0]
    acct_id = top["id"]
    print(f"  → top account: {top.get('account_name')} ({top.get('account_domain')})")
    print(f"    dev_activity={top.get('developer_activity')} "
          f"active_devs={top.get('active_developers_count')} "
          f"industry={top.get('industry')!r}")

    # Probe 3: activities for that account
    print(f"\n── Probe 3: GET /account/{{id}}/activities ──")
    status, body = get(f"{base}/account/{acct_id}/activities?page=1", api_key)
    ok = status == 200 and isinstance(body, dict) and "data" in body
    check("/account/{id}/activities", ok, f"status={status}, {len(body.get('data', [])) if ok else 0} rows")
    if not ok:
        failures.append("/account/{id}/activities")

    # Probe 4: developers at that account
    print(f"\n── Probe 4: GET /account/{{id}}/developers ──")
    status, body = get(f"{base}/account/{acct_id}/developers?page=1", api_key)
    ok = status == 200 and isinstance(body, dict) and "data" in body
    check("/account/{id}/developers", ok, f"status={status}, {len(body.get('data', [])) if ok else 0} rows")
    if not ok:
        failures.append("/account/{id}/developers")

    # Probe 5: can we find any of REO_TEST_DOMAINS in the segment?
    test_domains = [d.strip() for d in env.get("REO_TEST_DOMAINS", "").split(",") if d.strip()]
    if test_domains:
        print(f"\n── Probe 5: test domains in first segment ──")
        matched = [a for a in accounts if a.get("account_domain") in test_domains]
        if matched:
            for a in matched:
                print(f"  ✓ {a['account_domain']} — present "
                      f"(dev_activity={a.get('developer_activity')}, "
                      f"active_devs={a.get('active_developers_count')})")
        else:
            print(f"  ⚠ none of {test_domains} are in this segment")
            print(f"    (this is expected — they may live in a different segment)")

    return _finish(failures)


def _finish(failures: list[str]) -> int:
    print()
    if failures:
        print(f"✗ {len(failures)} probe(s) failed: {failures}")
        return 1
    print("✓ all probes passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
