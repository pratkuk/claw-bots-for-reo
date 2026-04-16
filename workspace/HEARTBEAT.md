# Heartbeat — scheduled tasks

> The `tasks` array in `manifest.json` references these by name. If a
> task isn't listed here, it doesn't run.

## Task 1 — Daily intent digest

**Name:** `daily-intent-digest`
**Schedule:** `0 14 * * *` (14:00 UTC every day; override via `/adjust schedule`)
**Enabled by default:** yes

### Preconditions

- `workspace/BOOTSTRAP.md` does **not** exist (bootstrap complete).
- `USER.md` has `default_segment_id` and `slack_channel` set.
- MCP server reachable at `/mcp` (AGENTS.md §8 covers failure modes).

If any precondition fails, abort silently — do not post an error every
day to the user's Slack. Post only on the first failure, then stay quiet
until fixed.

### Prompt

You are running the daily intent digest. Read `USER.md` for
configuration, then:

1. Call `get_top_intent_accounts` with:
   - `segment_id = USER.md:default_segment_id`
   - `limit = USER.md:digest_limit` (default 10)
   - `web3_only = USER.md:web3_only` (default true)
   - `extra_web3_domains = USER.md:web3_domains_extensions` (if any)

2. Take the top 5 accounts by rank (the list is pre-sorted). For each,
   in parallel:
   - `get_account_activity_detail(account_id, days=7)` — if 0 events,
     widen to `days=30` once, then accept whatever comes back
   - `get_active_developers(account_id, limit=5)`
   - `get_key_contacts(account_id, function="engineering", seniority="vp")`
     — if empty, fall back to `function="leadership", limit=3` and
     filter out any title containing "sales", "marketing", "business
     development", "growth" (AGENTS.md §2).

3. For each of the 5 accounts, synthesise:
   - **One-line summary:** what signal tier they're on + the top 1-2
     concrete signals (page name, repo action, copy-command count).
   - **Top active developer:** name + designation + score + last date.
     Put contact details (email, LinkedIn) in a footnote-style line.
   - **Economic buyer (if different):** from key_contacts result.
   - **Draft first-touch message:** 3 sentences, blockquoted, addressed
     to the top active developer (not the economic buyer). Must cite a
     specific signal from step 2a. Follow SOUL.md §Drafting.

4. Build the Slack post:
   - Header: date, scanned count, filtered count, `web3_only` state.
   - 5 account sections, high-confidence first, then medium under
     "Worth a look". See `docs/sample-digest.md` for shape.
   - Footer: command hints (`/run-digest`, `/adjust`, `/explain`).

5. Post once to `USER.md:slack_channel`. If the post fails, retry once
   after 30s. If it still fails, write the digest body to
   `workspace/last-failed-digest.md` and move on.

### Output contract

- **Length:** aim ~800-1200 words. Hard cap: Slack's 40k-char block
  limit.
- **No raw JSON**, no debug output, no "I called tool X" narration.
- **Emoji:** max one per section header. Zero inside draft messages.
- **If fewer than 5 high-or-medium-confidence accounts exist**, post
  what you have and add a line: "Only {N} accounts met the confidence
  bar today — {total_scanned - filtered_out} candidates were screened."

### Failure modes

| Condition | Action |
| --- | --- |
| MCP server returns 5xx after retries | Post once (per AGENTS.md §8), skip digest for today |
| Reo auth error | Post once, disable this task until user re-pairs |
| All accounts return `confidence: "low"` | Post the "nothing urgent" message from AGENTS.md §3 |
| Slack post fails twice | Write to `last-failed-digest.md`, continue silently |

## Task 2 — (reserved, v1.1)

Will hold a weekly "signal quality" retrospective. Not enabled in v1.0.
