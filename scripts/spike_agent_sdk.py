"""Phase 0 spike: prove Claude Agent SDK + Reo FastMCP stdio handshake works end-to-end.

Launches the existing Claw MCP server as a stdio child of the Agent SDK, loads the
workspace markdown as a system prompt, and asks Claude to call list_segments —
the safest read-only tool — then asserts the tool actually fired.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

REPO = Path(__file__).resolve().parent.parent
WORKSPACE = REPO / "workspace"
MCP_DIR = WORKSPACE / "projects" / "claw_mcp"
VENV_PYTHON = REPO / ".venv" / "bin" / "python3"


def load_system_prompt() -> str:
    parts = []
    for name in ["IDENTITY.md", "SOUL.md", "AGENTS.md", "TOOLS.md"]:
        parts.append(f"# === {name} ===\n{(WORKSPACE / name).read_text()}")
    return "\n\n".join(parts)


async def main() -> int:
    system_prompt = load_system_prompt()
    print(f"System prompt loaded: {len(system_prompt)} chars")

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers={
            "claw": {
                "type": "stdio",
                "command": str(VENV_PYTHON),
                "args": [str(MCP_DIR / "server.py"), "--transport", "stdio"],
                "cwd": str(MCP_DIR),
            },
        },
        allowed_tools=["mcp__claw__list_segments"],
        disallowed_tools=["ToolSearch", "Bash", "Read", "Write", "Edit", "Glob", "Grep"],
        max_turns=8,
        permission_mode="bypassPermissions",
        setting_sources=[],
    )

    tool_fired = False
    tool_result_seen = False

    async with ClaudeSDKClient(options=options) as client:
        await client.query(
            "Call list_segments with account_type_only=True. "
            "Then reply with just the integer count of segments you got back. "
            "No other text."
        )

        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        print(f"→ TOOL CALL: {block.name}({block.input})")
                        if block.name == "mcp__claw__list_segments":
                            tool_fired = True
                    elif isinstance(block, TextBlock):
                        print(f"CLAUDE: {block.text}")
            elif isinstance(msg, UserMessage):
                for block in msg.content:
                    if isinstance(block, ToolResultBlock):
                        snippet = str(block.content)[:200]
                        print(f"← TOOL RESULT: {snippet}")
                        tool_result_seen = True
            elif isinstance(msg, ResultMessage):
                print(
                    f"RESULT: turns={msg.num_turns} "
                    f"cost=${msg.total_cost_usd:.4f} "
                    f"err={msg.is_error}"
                )

    print()
    print("=" * 50)
    print(f"V2 tool_call_fired:   {tool_fired}")
    print(f"V2 tool_result_back:  {tool_result_seen}")
    ok = tool_fired and tool_result_seen
    print(f"V2 SPIKE {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
