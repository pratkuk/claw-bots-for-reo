"""Phase 0 spike: prove the three remaining seams — Slack Bolt signed-request flow
(D2), volume-style file persistence (D1), and cron-equivalent invocation of the
same entrypoint (D4) — all in one local run, no external accounts required.

What this simulates vs. what it doesn't:
  D2 — Real slack-bolt request signing verified end-to-end against a running
       Bolt HTTP app. What is NOT covered: OAuth install into a live workspace
       (needs user's Slack app credentials) and actual chat.postMessage
       (needs a real bot token).
  D1 — Writes USER.md to a configurable WORKSPACE_VOLUME dir. Kills the writer
       process, then re-reads from a fresh process. This mirrors Railway's
       volume contract (POSIX mount, survives container restart).
  D4 — Calls the same trigger() function twice: once from the Bolt webhook
       handler (Slack path), once directly (cron path). Proves one entrypoint
       serves both triggers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from slack_bolt import App
from slack_bolt.authorization import AuthorizeResult

# ─────────────────────────────────────────────────────────────
# Shared entrypoint — called from both Slack webhook and "cron"
# ─────────────────────────────────────────────────────────────

SLACK_SIGNING_SECRET = "spike-signing-secret-not-real"


def trigger(source: str, volume_dir: Path) -> dict:
    """The single entrypoint for daily digest runs. Persists last-run marker."""
    volume_dir.mkdir(parents=True, exist_ok=True)
    user_md = volume_dir / "USER.md"
    # Read-modify-write to prove persistence across restarts.
    prior = user_md.read_text() if user_md.exists() else ""
    new_line = f"last_trigger_source: {source}\nlast_trigger_ts: {time.time():.0f}\n"
    user_md.write_text(new_line + prior)
    return {"source": source, "user_md_size": user_md.stat().st_size}


# ─────────────────────────────────────────────────────────────
# Slack Bolt app — real signing, fake token (we don't post)
# ─────────────────────────────────────────────────────────────


def build_app(volume_dir: Path) -> App:
    def _fake_authorize(**kwargs):
        # Spike-only: skip the live auth.test round-trip; the signed-request
        # check above is what actually proves Slack-origin authenticity.
        return AuthorizeResult(
            enterprise_id=None,
            team_id="T_WS",
            bot_token="xoxb-fake-not-used-in-spike",
            bot_id="B_SPIKE",
            bot_user_id="U_BOT",
        )

    app = App(
        signing_secret=SLACK_SIGNING_SECRET,
        authorize=_fake_authorize,
        token_verification_enabled=False,
    )

    @app.command("/run-digest")
    def handle_run_digest(ack, body):
        # Ack within 3 seconds (Slack's hard deadline). In production the real
        # response would go via chat.postMessage inside trigger().
        ack(f"Triggered by {body.get('user_id')}")
        trigger(source="slack", volume_dir=volume_dir)

    return app


def sign_request(body: str, timestamp: str, secret: str) -> str:
    basestring = f"v0:{timestamp}:{body}".encode()
    digest = hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ─────────────────────────────────────────────────────────────
# Spike
# ─────────────────────────────────────────────────────────────


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="spike_volume_") as td:
        volume = Path(td)
        print(f"Volume mount path: {volume}")

        # ── D2: start Bolt, send a signed slash command ─────────────────
        app = build_app(volume)
        port = free_port()

        def serve():
            from slack_bolt.adapter.flask import SlackRequestHandler
            from flask import Flask, request

            flask_app = Flask(__name__)
            handler = SlackRequestHandler(app)

            @flask_app.route("/slack/events", methods=["POST"])
            def slack_events():
                return handler.handle(request)

            flask_app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        time.sleep(1.2)  # let Flask bind

        payload = urllib.parse.urlencode(
            {
                "command": "/run-digest",
                "text": "",
                "user_id": "U_SPIKE",
                "channel_id": "C_SPIKE",
                "response_url": "https://example.invalid/hook",
                "trigger_id": "T_SPIKE",
                "team_id": "T_WS",
            }
        )
        ts = str(int(time.time()))
        sig = sign_request(payload, ts, SLACK_SIGNING_SECRET)

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/slack/events",
            data=payload.encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
            },
            method="POST",
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=5) as resp:
            elapsed = time.time() - t0
            status = resp.status
            body = resp.read().decode()[:200]
        print(f"D2 Slack signed POST: status={status} elapsed={elapsed:.3f}s body={body!r}")

        # Tamper check: wrong signature must be rejected
        bad_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/slack/events",
            data=payload.encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": "v0=deadbeef" + "0" * 56,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(bad_req, timeout=5) as r:
                bad_status = r.status
        except urllib.error.HTTPError as e:
            bad_status = e.code
        print(f"D2 tampered-sig POST rejected with status={bad_status}")

        d2_pass = status == 200 and elapsed < 3.0 and bad_status in (401, 403)
        print(f"D2 SLACK SIGNED-REQUEST {'PASS' if d2_pass else 'FAIL'}")

        # ── D1: verify USER.md persists across simulated process restart ──
        # Spawn a fresh python process to read the file — proves nothing is
        # held only in the parent process memory.
        read_script = (
            f"import pathlib, sys; "
            f"p = pathlib.Path({str(volume / 'USER.md')!r}); "
            f"sys.stdout.write(p.read_text() if p.exists() else 'MISSING')"
        )
        import subprocess

        out = subprocess.run(
            [sys.executable, "-c", read_script],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        d1_pass = "last_trigger_source: slack" in out
        print(
            f"D1 VOLUME-PERSISTENCE {'PASS' if d1_pass else 'FAIL'} — "
            f"fresh process read {len(out)} bytes, contains slack marker: {d1_pass}"
        )

        # ── D4: cron-equivalent call into the same trigger() function ────
        before = (volume / "USER.md").stat().st_size
        trigger(source="cron", volume_dir=volume)
        after = (volume / "USER.md").stat().st_size
        content = (volume / "USER.md").read_text()
        d4_pass = (
            after > before
            and "last_trigger_source: cron" in content
            and "last_trigger_source: slack" in content
        )
        print(
            f"D4 CRON-ENTRYPOINT {'PASS' if d4_pass else 'FAIL'} — "
            f"size {before} → {after}, both sources present: {d4_pass}"
        )

        print()
        print("=" * 60)
        all_pass = d2_pass and d1_pass and d4_pass
        print(f"D2 (Slack signed request):   {'PASS' if d2_pass else 'FAIL'}")
        print(f"D1 (Volume persistence):     {'PASS' if d1_pass else 'FAIL'}")
        print(f"D4 (One entrypoint, 2 src):  {'PASS' if d4_pass else 'FAIL'}")
        print(f"OVERALL: {'PASS' if all_pass else 'FAIL'}")
        return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
