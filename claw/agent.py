"""Thin wrapper around the Claude Agent SDK for running digests.

Extracted from ``scripts/spike_slack_live.py`` so tests can stub
``run_digest_agent`` and so the Bolt layer doesn't import the SDK.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
WORKSPACE = _REPO / "workspace"
MCP_DIR = WORKSPACE / "projects" / "claw_mcp"
VENV_PYTHON = _REPO / ".venv" / "bin" / "python3"

log = logging.getLogger("claw.agent")

DIGEST_PROMPT_TEMPLATE = """Execute the daily intent digest per HEARTBEAT.md §Task 1.

Config:
- default_segment_id: {segment_id}
- digest_limit: 5
- web3_only: true
- today's date: {today}

Rules:
- Follow the 5 steps in HEARTBEAT.md exactly.
- Produce ONLY the final Slack post, formatted in Slack mrkdwn (not full
  Markdown): `*bold*` not `**bold**`, `>` for blockquotes, no tables.
- No preamble, no tool-call narration, no "here is the digest" header.
- If fewer than 5 high/medium-confidence accounts, follow AGENTS.md §3.
- Match the shape in docs/sample-digest.md, adapted for Slack mrkdwn.
"""


def _load_system_prompt() -> str:
    parts = []
    for name in ["IDENTITY.md", "SOUL.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md"]:
        parts.append(f"# === {name} ===\n{(WORKSPACE / name).read_text()}")
    return "\n\n".join(parts)


async def _run(prompt: str) -> str:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
    )

    options = ClaudeAgentOptions(
        system_prompt=_load_system_prompt(),
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
    parts: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                log.info(
                    "result: turns=%s cost=$%.4f err=%s",
                    msg.num_turns,
                    msg.total_cost_usd,
                    msg.is_error,
                )
    return "\n".join(parts).strip() or "(agent returned no text)"


def run_digest_agent(segment_id: str, today: str) -> str:
    """Synchronous entry point — runs the agent in a fresh event loop."""
    prompt = DIGEST_PROMPT_TEMPLATE.format(segment_id=segment_id, today=today)
    claude_cli = shutil.which("claude")
    log.info("run_digest_agent start; claude CLI=%s segment=%s", claude_cli, segment_id)
    return asyncio.run(_run(prompt))
