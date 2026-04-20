# Heartbeat — scheduled tasks

> The host process's scheduler (APScheduler, one job per configured
> workspace) invokes the tasks below at their configured times. If a
> task isn't listed here, it doesn't run.

## Task 1 — Daily intent digest

**Name:** `daily-intent-digest`
**Schedule:** per-workspace, from `config.schedule` (cron + tz). If
the workspace's schedule is null, the task runs manual-only.
**Enabled by default:** no — the host creates the scheduled job only
after the user completes `/setup` with a schedule selected.

### Preconditions

- The host loaded a complete per-workspace config (AGENTS.md §1).
- `config.paused` is false (AGENTS.md §7 `/pause` / `/resume`).
- Claw MCP server can be spawned as a stdio child.

If any precondition fails, abort silently — do not post an error
every day to the user's Slack. Post only on the first failure, then
stay quiet until fixed.

### Prompt

You are running the daily intent digest. Use the per-workspace config
that was passed to you, then:

1. Call `get_top_intent_accounts` with:
   - `segment_id = config.default_segment_id`
   - `limit = config.digest_limit` (default 10 if unset)
   - `web3_only = config.web3_only` (default true)
   - `extra_web3_domains = config.web3_domains_extensions` (if any)

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
   - Footer: command hints (`/run-digest`, `/config`, `/explain`).

5. Return the post body to the host, which posts it to
   `config.digest_channel_id`. If the host's post fails, it retries
   once after 30s; on second failure it logs and moves on.

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
| Claw MCP spawn fails | Host posts once (per AGENTS.md §8), skips digest for today |
| Reo auth error | Host posts once, marks workspace as needing re-config |
| All accounts return `confidence: "low"` | Post the "nothing urgent" message from AGENTS.md §3 |
| Slack post fails twice | Host logs the body and continues silently |

## Task 2 — (reserved, v1.1)

Will hold a weekly "signal quality" retrospective. Not enabled in v1.0.
