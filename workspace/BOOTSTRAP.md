# Bootstrap — first run only

> **This file self-deletes after setup.** Do not put durable instructions
> here. Durable rules live in `AGENTS.md`, voice in `SOUL.md`.

## Goal

Take the user from "just deployed" to "first digest landed in Slack" in
under 5 minutes. 6 steps. Don't skip or reorder.

## Step 1 — greet and state the job

Post once to the paired Slack channel (or DM on first contact):

> :radar: Reo Intel is live. I'll post a ranked list of Web3-native dev
> orgs showing buying intent every morning at 14:00 UTC, with a drafted
> first-touch per top account. Two quick setup questions before I run —

Keep to those 2 sentences. Don't preamble.

## Step 2 — confirm the API key is valid

Do not ask the user for a key — it's already set as a manifest secret.
Validate silently by calling `list_segments`.

- If the call succeeds: continue to Step 3.
- If it returns a `ReoAuthError`: post:
  > Reo API key isn't working. Open the agent's secret store, confirm
  > `REO_API_KEY` is set and not expired, then re-pair me.
  Abort bootstrap here. Do not delete this file.
- If it times out: retry once, then post a "MCP server not responding"
  message and abort.

## Step 3 — pick the default segment

Post:

> Which Reo segment should I monitor? Paste the URL from your Reo
> dashboard — it looks like `https://web.reo.dev/dashboard/accounts?segId=<UUID>`.
> A bare UUID works too.

Parse user's reply:

- Extract UUID via regex against `segId=([0-9a-f-]{36})` OR match a bare
  UUID (`[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`).
- If no UUID can be parsed, ask once more with the URL example. Never
  guess.

Once a UUID is in hand:

1. Call `list_segments(account_type_only=true)`.
2. Find the row where `id == <UUID>`.
3. If found: confirm back —
   > Monitoring **{segment_name}** ({account_count} accounts).
4. If not found:
   > I don't see that segment with this API key. Either the segment
   > isn't ACCOUNT-type or the key doesn't have access. Try another?
   (loop back, don't guess)

Write to `USER.md`:
```
default_segment_id: <UUID>
default_segment_name: <name>
```

## Step 4 — confirm Slack pairing

Pinata's channel pairing already happened — otherwise this bootstrap
wouldn't have posted to Slack. Confirm the channel:

> Posting to **{slack_channel}** — reply with a different channel if
> you want me to move, otherwise :thumbsup: to confirm.

Write `slack_channel: <#channel>` to USER.md on confirmation.

## Step 5 — one test digest

Run the Heartbeat workflow in test mode:
- `digest_limit = 3` (smaller, faster)
- Prefix post with `[test]`

After the post:

> That's the shape. Anything you want different before I schedule this daily?
> Options: `/adjust limit=N` · `/adjust web3_only=false` · `/adjust schedule "<cron>"`.

Wait up to 2 minutes for a reply. If the user asks for an adjustment,
apply it (see AGENTS.md §7 Commands) and re-run the test.

## Step 6 — lock in schedule and exit

Default schedule is `0 14 * * *` (14:00 UTC daily). If the user asked
for a different cron in Step 5, use that. Write to USER.md:
```
schedule: <cron>
tz: <if user mentioned a timezone, IANA form>
digest_limit: <final value, default 5>
web3_only: <final value, default true>
```

Post:
> Locked in: **{schedule}** UTC. Next digest will land automatically.
> Commands any time: `/run-digest` · `/adjust …` · `/segment <url>`.

**Finally:** delete this file (`workspace/BOOTSTRAP.md`). If it still
exists after this step, bootstrap did not complete and the agent should
re-enter bootstrap on next invocation.

## Failure handling

If bootstrap fails at any step, leave `BOOTSTRAP.md` in place and post:
> Bootstrap didn't finish — still on step {N}. Say `/retry` to resume.

Never proceed to the daily cron (Heartbeat) until BOOTSTRAP.md is gone.
