# Tools & environment

## The local MCP server (the only data source)

A FastMCP server starts alongside the agent (`scripts.start`) and serves
on the forwarded route `/mcp`. All Reo data flows through it. I do not
call Reo's REST API directly — credentials live only in the MCP process.

- **Transport:** HTTP, path `/mcp`, port 8787 inside the container.
- **Auth:** `x-internal-token` header, value from the
  `REO_MCP_INTERNAL_TOKEN` manifest secret (shared between agent and MCP).
- **Availability:** if the server isn't reachable, follow AGENTS.md §8
  (post once, retry tomorrow) — never hot-loop.

### Tools exposed (5 total, v1.0)

| Tool | Primary use | Key args |
| --- | --- | --- |
| `list_segments` | Bootstrap only; confirm a segment ID resolves to a name | `account_type_only=True` |
| `get_top_intent_accounts` | Entry point for the daily digest | `segment_id`, `limit=10`, `web3_only=True`, `extra_web3_domains` |
| `get_account_activity_detail` | Per-account signal stream | `account_id`, `days=7`, `max_rows=200` |
| `get_active_developers` | Most active devs at an account | `account_id`, `limit=5` |
| `get_key_contacts` | Filter devs by function + seniority | `account_id`, `function`, `seniority`, `limit=10` |

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

## Reo API (reachable only through the MCP server above)

- **Base URL:** `https://integration.reo.dev`
- **Auth:** `x-api-key: <REO_API_KEY>` on every request.
- **Rate limits:** honour `Retry-After` and `X-RateLimit-Reset`; the
  MCP server retries up to 3 times with exponential backoff. On
  exhaustion it raises `ReoRateLimitError` — I surface it once and stop.

## Slack (outbound channel)

- Provisioned through Pinata's `channels.slack` pairing. OAuth and
  token lifecycle are platform concerns, not mine.
- **Destination channel:** `USER.md:slack_channel` (set during bootstrap).
- **DM policy:** `pairing` — only the paired workspace+user can interact.
- **Formatting:** Slack mrkdwn (not full Markdown). Blockquotes via
  `>`, bold via `*text*`, code via backticks. Avoid tables — they don't
  render in Slack.

## Filesystem I may write to

- `workspace/USER.md` — user preferences and memory (AGENTS.md §1).
- `workspace/last-failed-digest.md` — body of any digest that couldn't
  be posted; overwritten on each failure.
- I do **not** write to files outside `workspace/`. The MCP server code
  in `workspace/projects/reo_mcp/` is not mine to modify at runtime.

## What I do not have

- No internet browsing.
- No direct Reo REST access.
- No write access to Reo — I'm read-only via the MCP tools.
- No ability to send messages on the user's behalf; I only draft.
- No access to the user's inbox, CRM, or calendar in v1.0.

If a user asks for any of the above, say so plainly and suggest the
closest thing I can do.
