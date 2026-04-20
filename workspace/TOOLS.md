# Tools & environment

## The Claw MCP server (the only data source)

A FastMCP server at `workspace/projects/claw_mcp/` is launched as a
**stdio child process** of the Claude Agent SDK at runtime. All Reo data
flows through it. I do not call Reo's REST API directly — credentials
live only in the MCP process.

- **Transport:** stdio (no port, no HTTP auth). The SDK spawns the
  server and talks to it over the child process's stdin/stdout.
- **Process model:** one MCP server instance per digest run. It reads
  the workspace's Reo API key from the loaded per-workspace config at
  spawn time (env vars passed by the parent Python process).
- **Availability:** if the server fails to spawn or errors during
  startup, follow AGENTS.md §8 (post once, retry tomorrow) — never
  hot-loop.

### Tools exposed (5 total, v1.0)

| Tool | Primary use | Key args |
| --- | --- | --- |
| `list_segments` | Configuration UI; confirm a segment ID resolves to a name | `account_type_only=True` |
| `get_top_intent_accounts` | Entry point for the daily digest | `segment_id`, `limit=10`, `web3_only=True`, `extra_web3_domains` |
| `get_account_activity_detail` | Per-account signal stream | `account_id`, `days=7`, `max_rows=200` |
| `get_active_developers` | Most active devs at an account | `account_id`, `limit=5` |
| `get_key_contacts` | Filter devs by function + seniority | `account_id`, `function`, `seniority`, `limit=10` |

In my tool call list these appear as `mcp__claw__list_segments`,
`mcp__claw__get_top_intent_accounts`, etc. — the `mcp__claw__` prefix
is how the Agent SDK namespaces this server.

Response shapes are documented inline in each tool's docstring and
cross-referenced in `docs/api-exploration.md`. Every response has been
through the `_slim_*` projection — no raw Reo fields leak through.

### What each tool returns (summary — full shape in the docstring)

- `get_top_intent_accounts` → `{segment_id, total_scanned, filtered_out, accounts: [...]}`
  each account has a `confidence: "high" | "medium" | "low"` tag.
- `get_account_activity_detail` → `{event_count, by_type, by_source, events: [...]}`
- `get_active_developers` → `{developer_count, developers: [...]}`
- `get_key_contacts` → `{matched_count, filter: {...}, developers: [...]}`

### Pagination contract (for the record)

- `/segments` ignores `?page=N`, returns every row on page 1 with
  `total_pages: null`. The walker stops after page 1.
- `/segment/{id}/accounts` honours pagination, reports integer
  `total_pages`. Walked in full, up to the 50-page hard cap.

## Reo API (reachable only through the Claw MCP server above)

- **Base URL:** `https://integration.reo.dev`
- **Auth:** `x-api-key: <REO_API_KEY>` on every request. The key is
  per-workspace, loaded from the workspace's encrypted config.
- **Rate limits:** honour `Retry-After` and `X-RateLimit-Reset`; the
  MCP server retries up to 3 times with exponential backoff. On
  exhaustion it raises `ReoRateLimitError` — I surface it once and stop.

## Slack (outbound channel)

- Provisioned through Slack OAuth at install time. The host Python
  process (Slack Bolt) owns the bot token and does `chat.postMessage`
  on my behalf — I never hold a Slack token directly.
- **Destination channel:** per-workspace `digest_channel_id` from the
  loaded config.
- **Formatting:** Slack mrkdwn (not full Markdown). Blockquotes via
  `>`, bold via `*text*`, code via backticks. Avoid tables — they
  don't render in Slack.

## Filesystem

I do **not** write to the filesystem. All state lives in the host
Python process's per-workspace config store, which is managed by code
outside the agent loop. The MCP server code in
`workspace/projects/claw_mcp/` is not mine to modify at runtime.

## What I do not have

- No internet browsing.
- No direct Reo REST access.
- No write access to Reo — I'm read-only via the MCP tools.
- No ability to send messages on the user's behalf; I only draft.
- No access to the user's inbox, CRM, or calendar in v1.0.

If a user asks for any of the above, say so plainly and suggest the
closest thing I can do.
