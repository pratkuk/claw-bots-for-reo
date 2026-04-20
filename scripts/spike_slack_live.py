"""Phase 0 live spike: real Slack OAuth install + real /run-digest → real
Claude Agent SDK run → real chat.postMessage back to the channel.

Runs a Flask app on port 3000 behind an ngrok tunnel. Provides:
  GET  /slack/install           — kicks off the OAuth flow
  GET  /slack/oauth_redirect    — receives the code, exchanges for bot token,
                                  persists to workspace/installations.json
  POST /slack/events            — slash command entry (signed by Slack)

On /run-digest: acks immediately, then in a background thread loads the
workspace markdown as a system prompt, spawns the Claw MCP server as a stdio
child of the Claude Agent SDK, asks Claude to call list_segments and report
the count, and posts the answer back to the originating channel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import threading
import traceback
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt.oauth.oauth_settings import OAuthSettings
from slack_sdk import WebClient
from slack_sdk.oauth.installation_store import Installation
from slack_sdk.oauth.installation_store.file import FileInstallationStore
from slack_sdk.oauth.state_store.file import FileOAuthStateStore

REPO = Path(__file__).resolve().parent.parent
WORKSPACE = REPO / "workspace"
MCP_DIR = WORKSPACE / "projects" / "claw_mcp"
VENV_PYTHON = REPO / ".venv" / "bin" / "python3"
INSTALL_DIR = WORKSPACE / ".slack_installations"
STATE_DIR = WORKSPACE / ".slack_oauth_state"

load_dotenv(REPO / ".env")

LOG_FILE = REPO / "workspace" / "spike_live.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("spike")

CLAUDE_CLI = shutil.which("claude") or "/Users/pratyushkukreja/.local/bin/claude"
log.info("Claude CLI resolved to: %s", CLAUDE_CLI)

SLACK_CLIENT_ID = os.environ["SLACK_CLIENT_ID"]
SLACK_CLIENT_SECRET = os.environ["SLACK_CLIENT_SECRET"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]


# ─────────────────────────────────────────────────────────────
# Agent runner — identical shape to what goes to Railway
# ─────────────────────────────────────────────────────────────


def load_system_prompt() -> str:
    parts = []
    for name in ["IDENTITY.md", "SOUL.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md"]:
        parts.append(f"# === {name} ===\n{(WORKSPACE / name).read_text()}")
    return "\n\n".join(parts)


DIGEST_PROMPT = """Execute the daily intent digest per HEARTBEAT.md §Task 1.

Config (use in place of USER.md since bootstrap hasn't run):
- default_segment_id: {segment_id}
- digest_limit: 5
- web3_only: true
- slack_channel: #reo-intel-test
- today's date: {today}

Rules:
- Follow the 5 steps in HEARTBEAT.md exactly.
- Produce ONLY the final Slack post, formatted in Slack mrkdwn (not full
  Markdown): `*bold*` not `**bold**`, `>` for blockquotes, no tables.
- No preamble, no tool-call narration, no "here is the digest" header.
- If fewer than 5 high/medium-confidence accounts, follow AGENTS.md §3.
- Match the shape in docs/sample-digest.md, adapted for Slack mrkdwn.
"""


async def run_agent(user_question: str, progress_cb=None) -> str:
    """Call Claude via Agent SDK + Claw MCP, return a single-string answer."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        TextBlock,
        ToolUseBlock,
        ResultMessage,
    )

    log.info("run_agent start; loading system prompt")
    options = ClaudeAgentOptions(
        system_prompt=load_system_prompt(),
        mcp_servers={
            "claw": {
                "type": "stdio",
                "command": str(VENV_PYTHON),
                "args": [str(MCP_DIR / "server.py"), "--transport", "stdio"],
                "cwd": str(MCP_DIR),
            },
        },
        allowed_tools=[
            "mcp__claw__list_segments",
            "mcp__claw__get_top_intent_accounts",
            "mcp__claw__get_account_activity_detail",
            "mcp__claw__get_active_developers",
            "mcp__claw__get_key_contacts",
        ],
        disallowed_tools=["ToolSearch", "Bash", "Read", "Write", "Edit", "Glob", "Grep"],
        max_turns=30,
        permission_mode="bypassPermissions",
        setting_sources=[],
    )

    reply_parts: list[str] = []
    log.info("spawning Claude CLI + Claw MCP stdio child")
    async with ClaudeSDKClient(options=options) as client:
        log.info("CLI up; sending query")
        await client.query(user_question)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        reply_parts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        log.info("tool call: %s(%s)", block.name, block.input)
                        if progress_cb:
                            try:
                                progress_cb(block.name, block.input)
                            except Exception:
                                log.exception("progress_cb failed")
            elif isinstance(msg, ResultMessage):
                log.info(
                    "result: turns=%s cost=$%.4f err=%s",
                    msg.num_turns,
                    msg.total_cost_usd,
                    msg.is_error,
                )

    answer = "\n".join(reply_parts).strip() or "(agent returned no text)"
    log.info("run_agent done; reply length=%d", len(answer))
    return answer


def handle_run_digest_async(bot_token: str, channel: str, user_id: str) -> None:
    """Runs in a background thread. Posts to Slack when done."""
    client = WebClient(token=bot_token)
    log.info("digest handler start: channel=%s user=%s", channel, user_id)
    try:
        client.chat_postMessage(
            channel=channel,
            text=f":radar: <@{user_id}> triggered a digest. Running the full HEARTBEAT workflow — expect 10–20 min.",
        )

        def progress(tool_name: str, tool_input: dict) -> None:
            short = tool_name.replace("mcp__claw__", "")
            key_arg = ""
            for k in ("account_domain", "account", "segment_id", "limit"):
                if k in tool_input:
                    key_arg = f" {k}={tool_input[k]}"
                    break
            client.chat_postMessage(channel=channel, text=f":gear: `{short}`{key_arg}")

        prompt = DIGEST_PROMPT.format(
            segment_id=os.environ["REO_TEST_SEGMENT_ID"],
            today=date.today().isoformat(),
        )
        answer = asyncio.run(run_agent(prompt, progress_cb=progress))
        client.chat_postMessage(channel=channel, text=answer)
        log.info("digest handler done; posted answer of length=%d", len(answer))
    except Exception as e:
        log.error("digest handler FAILED:\n%s", traceback.format_exc())
        try:
            client.chat_postMessage(
                channel=channel,
                text=f":warning: Agent run failed: `{type(e).__name__}: {e}`",
            )
        except Exception:
            log.error("also failed to post error message to Slack")


# ─────────────────────────────────────────────────────────────
# Slack Bolt app (OAuth + slash command)
# ─────────────────────────────────────────────────────────────

INSTALL_DIR.mkdir(exist_ok=True)
STATE_DIR.mkdir(exist_ok=True)

oauth_settings = OAuthSettings(
    client_id=SLACK_CLIENT_ID,
    client_secret=SLACK_CLIENT_SECRET,
    scopes=["chat:write", "commands", "channels:read", "channels:history"],
    installation_store=FileInstallationStore(base_dir=str(INSTALL_DIR)),
    state_store=FileOAuthStateStore(expiration_seconds=600, base_dir=str(STATE_DIR)),
)

app = App(signing_secret=SLACK_SIGNING_SECRET, oauth_settings=oauth_settings)


@app.command("/run-digest")
def handle_run_digest(ack, body, context):
    ack(":radar: triggered — I'll post back in a moment.")
    bot_token = context["bot_token"]
    channel = body["channel_id"]
    user_id = body["user_id"]
    t = threading.Thread(
        target=handle_run_digest_async,
        args=(bot_token, channel, user_id),
        daemon=True,
    )
    t.start()


handler = SlackRequestHandler(app)
flask_app = Flask(__name__)


@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)


@flask_app.route("/slack/install", methods=["GET"])
def slack_install():
    return handler.handle(request)


@flask_app.route("/slack/oauth_redirect", methods=["GET"])
def slack_oauth_redirect():
    return handler.handle(request)


@flask_app.route("/", methods=["GET"])
def root():
    installs = list(INSTALL_DIR.glob("*/*/installer-latest"))
    return (
        "<h2>Reo Intel (dev) spike</h2>"
        f"<p>Installs on disk: {len(installs)}</p>"
        '<p><a href="/slack/install">Install to Slack workspace</a></p>'
    )


if __name__ == "__main__":
    print("Starting spike server on http://127.0.0.1:3000")
    print("Install URL: https://pauper-chlorine-twisting.ngrok-free.dev/slack/install")
    flask_app.run(host="127.0.0.1", port=3000, debug=False, use_reloader=False)
