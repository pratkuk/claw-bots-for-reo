# Onboarding & Multi-Tenant Config — Build Plan (v1)

Status: steps 1–4 shipped 2026-04-21 on `feat/onboarding-v1` (verified
live against real Slack + real Reo). Steps 5–10 + step 10 first-run DM
tweak remain. See `DECISIONS.md` 2026-04-21 for live-test lessons that
the remaining steps must honour.
Owner: pratyush.kukreja@gmail.com
Supersedes: nothing (new doc)

## Goal

Turn the current single-tenant spike (`scripts/spike_slack_live.py`, hardcoded
`.env` creds, one segment, no schedule) into a multi-tenant Slack app where
any workspace can install Claw, configure their own Reo credentials + digest
preferences, and run manual or scheduled digests — without ever touching the
server.

## Shipping decisions (locked)

| # | Decision | Chosen |
|---|----------|--------|
| 1 | Setup surface | **Slack modal** (not hosted web page) |
| 2 | Config granularity | **Per-workspace** (per-user deferred to v1.1) |
| 3 | Segment model | **Default segment + per-run switch.** One "Default segment" stored in config, used by cron. `/run-digest` opens a modal with that default pre-selected; user can switch; successful runs update the default silently. No separate pinning concept in v1. |
| 4 | Secret storage | File perms 600 + env-derived Fernet key for encryption at rest. Upgrade to a secrets manager if/when we go hosted. |
| 5 | Permission model | Installer-only for v1. Admin/ACL model deferred. |
| 6 | Multi-segment support | Yes — pick any segment per run. Multi-segment *scheduling* (multiple crons with different segments) is v1.1. |

## Per-workspace config schema

One file per `team_id` on the Railway volume, alongside the Slack installation
record.

```
workspace/.claw_configs/{team_id}.json
```

Fields:

```jsonc
{
  "team_id": "T_XXXX",
  "installer_user_id": "U_XXXX",
  "reo_api_key_encrypted": "gAAAAA...",   // Fernet-encrypted
  "tenant_id": "...",
  "default_segment_id": "da8416c8-...",    // used by cron; updated after each manual run
  "digest_channel_id": "C_XXXX",
  "schedule": {                            // null = manual-only
    "cron": "0 9 * * *",
    "tz": "America/Los_Angeles"
  },
  "digest_limit": 5,
  "web3_only": true,
  "paused": false,
  "created_at": "...",
  "updated_at": "..."
}
```

Fernet key source: `CLAW_CONFIG_ENCRYPTION_KEY` env var on Railway (generate
once with `Fernet.generate_key()`, never rotate without re-encrypting files).

## Build order

### 1. Config store module ✅ (shipped)
- `claw/config.py`: `load_config(team_id)`, `save_config(team_id, config)`,
  `delete_config(team_id)`.
- Fernet encrypt/decrypt on `reo_api_key` field only.
- Files written with `os.open(..., 0o600)` to enforce perms.
- Unit tests with a tmpdir volume.

### 2. `/setup` command + Slack modal ✅ (shipped — two-step, async loader between steps; ACCOUNT-type filter; 100-option cap with default pinned)
- Slash command `/setup` opens a modal with fields:
  - Reo API key (password input)
  - Tenant ID (plain text)
  - Segment (`static_select` populated via live `list_segments` call after
    the API key field loses focus — or, simpler v1: two-step modal, key
    first, then segment picker on step 2)
  - Digest channel (`channels_select`)
  - Schedule time + timezone (two `static_select` elements; "manual only"
    is a valid choice)
  - Digest limit (numeric; default 5)
  - Web3 filter (checkbox; default on)
- On submit: validate API key against Reo (ping `list_segments`), save config,
  ack modal. If validation fails, re-open modal with inline error.

### 3. Credential validation + error mapping ✅ (shipped — `claw/errors.py::map_reo_error` + `list_segments_safe`)
- Wrap every Reo call in a helper that maps:
  - 401/403 → "Invalid API key — double-check it in Reo's dashboard."
  - 404 → "That segment / tenant couldn't be found. Did it get deleted?"
  - 429 → "Reo is rate-limiting us. Try again in a minute."
  - 5xx → "Reo's API is having trouble. Try again shortly."
  - timeout → "Reo didn't respond in time. Try again."
- Never expose tracebacks or raw error bodies to Slack.

### 4. Refactor `/run-digest` ✅ (shipped — picks from configured channel, updates default on change, per-workspace Reo key forwarded to MCP subprocess via stdio `env`; auto-join + DM fallback on `not_in_channel`)
- Load config by `team_id` from `body["team_id"]`.
- If no config → "Run `/setup` first."
- Open segment-picker modal pre-filled with `default_segment_id`, live-load
  options via `list_segments`.
- On submit, run the digest against chosen segment, post to
  `digest_channel_id` (not the channel the command was run from), update
  `default_segment_id = chosen`.

### 5. Cron wiring (APScheduler, same process)
- One `BackgroundScheduler` at startup.
- On startup: load all configs, register one job per non-null schedule.
- Job fires → call the same `trigger()` entrypoint used by `/run-digest`,
  using `default_segment_id`.
- On config save/delete/pause → reschedule/remove the job live.

### 6. `/config` command
- Same modal as `/setup`, pre-filled with current values.
- API key field shows `••••••` placeholder; empty-on-submit means "keep
  existing," any value means "replace."

### 7. `/pause` and `/resume`
- Toggle `paused` flag in config; scheduler checks the flag before firing.
- `/pause` replies with "Paused. Run `/resume` to re-enable scheduled
  digests. Manual `/run-digest` still works."

### 8. Uninstall handler
- Subscribe to Slack `app_uninstalled` event.
- On fire: cancel scheduled job for that team, delete config file, delete
  Slack installation record.

### 9. Post-install welcome DM
- On OAuth completion, `chat.postMessage` to the installer (as DM):
  "Welcome to Claw. Run `/setup` in any channel to get started — takes ~1
  minute."

### 10. First-run test digest
- End of `/setup` modal submit flow: run one digest immediately against the
  chosen segment, post the result as a DM to the installer (NOT the
  configured public channel), with a header: "Here's what your daily digest
  will look like. Scheduled runs start tomorrow at 9 AM PT."

## Deferred to v1.1+

- Per-user config (different people in a workspace wanting different digests)
- Multi-segment scheduling (one workspace running crons against 2+ segments)
- Pinned segment override (prevent default drift)
- Outreach style / POV preferences (spice level, economic-buyer rules)
- Admin-level ACL beyond installer-only
- Hosted web setup page (needed if Reo ever adds OAuth)
- Secrets-manager-backed storage (needed if going multi-tenant hosted)
- Weekly signal-quality retrospective (already in CHANGELOG as v1.1)

## Open infra questions (not blockers for v1)

- Railway volume path: confirm `/data` mount convention.
- Where does `CLAW_CONFIG_ENCRYPTION_KEY` live — Railway env, or same mount?
  (Env.)
- What timezone list do we show in the schedule picker? (Probably the IANA
  short list: America/LA, America/NY, Europe/London, Europe/Berlin, Asia/SG,
  Asia/Tokyo, Asia/Kolkata. Extend on request.)

## Success criteria

A new workspace can:
1. Click install, get the welcome DM
2. Run `/setup`, fill 6 fields, submit
3. Get a sample digest in DM within 2 minutes
4. See the scheduled digest post to the configured channel the next morning

...all without any code change or server touch from us.
