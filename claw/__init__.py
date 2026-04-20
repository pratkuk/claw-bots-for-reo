"""Host-side package: Slack app, config store, scheduler.

Separate from ``claw_mcp`` (the FastMCP server). Per AGENTS.md §1, the
MCP server never reads or writes config — the host loads config here
and hands it to the agent at run time.
"""
