# Decision Log

> Compact log of locked-in calls. Newest first.
> Entries below 2026-04-20 describe the original Pinata-hosted design.
> That design has been **superseded** — see the 2026-04-20 pivot section.
> Historical entries are kept for context on ranking rules, filter
> calibration, and API findings, which still apply.

---

## 2026-04-20 — Pivot: Pinata → self-hosted Agent SDK on Railway

Pinata's support could not unblock the deploy timeline. We pivoted to a
self-hosted architecture that keeps every agentic capability and drops
the marketplace dependency. The D1–D4 decisions below are locked.

### D0 — Drop Pinata entirely
- The repo no longer targets `agents.pinata.cloud`. `manifest.json`,
  `BOOTSTRAP.md`, and `USER.md` (all Pinata runtime contracts) have been
  deleted. Any file still referencing Pinata is stale.

### D1 — Storage: volume + file
- Per-workspace state lives on a persistent volume (Railway volume or
  equivalent) as one encrypted `config.json` per `team_id`.
- Fernet-encrypt the `reo_api_key` field only; key source is env var
  `CLAW_CONFIG_ENCRYPTION_KEY`. File perms `0600`.
- Proven locally via `scripts/spike_slack_volume_cron.py` (D1 PASS).

### D2 — Slack: via slack-bolt (not Pinata's pairing)
- Slack Bolt handles OAuth install, signed-request verification, and
  `chat.postMessage`. Installations persist via `FileInstallationStore`
  on the same volume as the config store.
- Proven locally via `scripts/spike_slack_volume_cron.py` (D2 PASS:
  signed request 200ms, tamper → 401) and end-to-end via
  `scripts/spike_slack_live.py` (real OAuth install + `/run-digest` → real
  digest posted to #reo-intel-test on 2026-04-20).

### D3 — Agent: self-hosted Claude Agent SDK
- Stack: `claude-agent-sdk` (Python) + `ClaudeSDKClient` +
  `ClaudeAgentOptions(mcp_servers=..., system_prompt=..., permission_mode=bypassPermissions, setting_sources=[])`.
- Critical config lesson: must set `setting_sources=[]` and an explicit
  `disallowed_tools` list (`["ToolSearch", "Bash", "Read", "Write",
  "Edit", "Glob", "Grep"]`) to prevent the Claude CLI default tool
  probing from burning turns.
- Tool results arrive as `UserMessage` with `ToolResultBlock` — NOT
  `AssistantMessage`. First spike missed this.
- Proven via `scripts/spike_agent_sdk.py` (V2 PASS: real tool call +
  real tool result round-trip against the live Reo API).

### D4 — One process, two triggers
- Single Python process. Slack slash commands and APScheduler cron
  both invoke the same `trigger()` entrypoint.
- Proven locally via `scripts/spike_slack_volume_cron.py` (D4 PASS: one
  entrypoint served both Slack and cron-equivalent calls, state
  persisted across a subprocess boundary).

### MCP rename: "Reo MCP" → "Claw MCP"
- "Reo MCP" inside the company refers to the official Reo-built MCP
  (`mcp-remote https://mcp.internal.reo.dev`, VPN-only). Our FastMCP
  server is separate and was renamed to avoid confusion.
- Directory: `workspace/projects/claw_mcp/`. Package: `claw_mcp`.
  MCP identifier in `ClaudeAgentOptions.mcp_servers`: `"claw"`. Tool
  namespace: `mcp__claw__*`. FastMCP server name: `claw-mcp`.
- 49/49 unit tests pass post-rename.

### Onboarding architecture locked
- Full spec in `docs/onboarding-plan.md`.
- **Setup surface:** Slack modal (not hosted web page).
- **Granularity:** per-workspace (per-user deferred to v1.1).
- **Segment model:** one `default_segment_id` per workspace used by
  cron; `/run-digest` opens a picker pre-selected to the default and
  updates it on each manual run. No separate "pinning" concept in v1.
- **Secrets:** Fernet encryption at rest + file perms 0600; upgrade to
  a secrets manager only if/when going hosted multi-tenant.
- **Permissions:** installer-only for v1; ACL deferred.

### What carries over unchanged
- Ranking rules (HIGH > MEDIUM > LOW > empty, tie-break on dev count).
- Web3 allow-list approach (seed + per-workspace extensions).
- 5-tool MCP surface.
- Confidence tagging + digest voice rules in SOUL.md / AGENTS.md.
- Pagination contract (`/segments` single-page, `/segment/{id}/accounts`
  paginates).
- Leadership-filter calibration (prefer `engineering + vp`).

---

## 2026-04-16 — Pre-build decisions

**Superseded by the 2026-04-20 pivot above.** Deployment specifics
(Pinata hosting, manifest secrets, `scripts.start`, HTTP transport
for the MCP, shared `REO_MCP_INTERNAL_TOKEN`) no longer apply. The
ranking, filter, API, and channel decisions in this section still
apply.

### Repo
- **Name:** `claw-bots-for-reo`
- **Host:** `github.com/pratkuk/claw-bots-for-reo` (personal, not reo-dev org)
- **License:** MIT (default, minimal friction, matches ecosystem norms)
- **Base template reference:** `PinataCloud/agent-templates` (plural — `agent-template` singular is deprecated)

### Reo API integration
- **Surface:** public REST at `https://integration.reo.dev` — option B from prior round
- **Auth:** `x-api-key` header, single key, no tenant ID
- **Endpoints used (4):** `/segments`, `/segment/{id}/accounts`, `/account/{id}/activities`, `/account/{id}/developers`
- **No global `/accounts` list** — agent operates within a user-selected segment
- **No domain → account lookup** — all traversal starts from a segment

### MCP server (v1.0)
- **Stack:** Python + FastMCP (recommendation from v1 context; unchanged)
- **Deployment:** local inside Pinata container, exposed via `scripts.start` + `routes` on port 8787 path `/mcp`
- **Tool count:** 5 — `list_segments`, `get_top_intent_accounts`, `get_account_activity_detail`, `get_active_developers`, `get_key_contacts`
- **Dropped from v1.0:** `get_hiring_signals` (endpoint doesn't exist publicly; revisit v1.1)

### Ranking (`get_top_intent_accounts`)
- **Rule:** lexicographic by `developer_activity` (`HIGH=3 > MEDIUM=2 > LOW=1 > empty=0`), tie-break by `active_developers_count` desc
- **Empty-activity handling:** sorts below `LOW`, still returned (161/297 of seed segment have empty activity — not a bug)
- **Not doing:** weighted scoring, ML ranking, user-tunable weights — pending real usage data

### Web3 filter (`web3_only` flag)
- **Approach:** curated domain allow-list (heuristic — no native Web3 field in Reo's industry enum)
- **Seed source:** user's existing Reo segment `da8416c8-7dc1-4ab9-9fca-d921620dbce3`, 297 unique domains
- **Extensibility:** `/web3-domains +foo.xyz` slash command at runtime
- **File:** `workspace/projects/claw_mcp/web3_domains.py` (frozenset; Python package names can't have hyphens)

### Bootstrap flow
- User pastes Reo segment URL (or bare UUID) on first run
- Agent extracts UUID, calls `list_segments`, confirms the segment name back to user
- Persists in `workspace/USER.md` as `default_segment_id` + `default_segment_name`

### Channels
- **v1.0:** Slack only, `dmPolicy: "pairing"`
- Target workspace: `reodevworkspace.slack.com`, channel `#reo-intel-test` for build validation
- Telegram/Discord: v1.1 if demand surfaces

### Schedule
- Cron: `0 14 * * *` (14:00 UTC daily) — global async default
- Adjustable at deploy time; user-facing slash command `/adjust schedule "<cron>"`

### Secrets
- Values in `.env` (gitignored); schema in `.env.example` (committed)
- Auto-generated `REO_MCP_INTERNAL_TOKEN` (token shared between agent + local MCP)
- `.env` never committed; rotation plan documented in README troubleshooting

### Coding + repo hygiene (per §1.1 of context doc)
- Python type hints on all public functions
- Pinned dependencies (`requirements.txt`)
- `ruff` for lint + format (config in `pyproject.toml`)
- Conventional-commit messages
- Small commits per step (not one "initial dump")
- `main` always deployable; feature branches + PR even solo
- Semver release tags

---

## Still open / to revisit

- **Reo key rotation** — user to verify whether the 19-char key is complete or truncated (still pending reply)
- **Railway deployment** — not yet proven end-to-end; needs Railway account + `ANTHROPIC_API_KEY` on the hosted environment. Local spike is the current proof.
- **Encryption key management** — `CLAW_CONFIG_ENCRYPTION_KEY` rotation strategy is undefined; if rotated, all existing workspace configs must be re-encrypted.

---

## 2026-04-16 — Post-live-integration findings (Step 3)

Live end-to-end run against segment `da8416c8-...` produced the following
observations. Kept in this log because they influence digest UX decisions
that haven't been made yet.

### Pagination — two contracts on the same API
- `/segments` returns every row on page 1, `total_pages: null`, subsequent
  `?page=N` values are ignored (return same 571 rows).
- `/segment/{id}/accounts` honours `?page=N` and reports integer `total_pages`.
- `_paginate_all` now walks using `total_pages`; falls back to "single page"
  when null. Regression locked in by
  `test_paginate_all_stops_when_total_pages_null`.

### Data quality in the Crypto-keyword segment (n=297)
- 362 ACCOUNT-type segments visible to this API key (cleaner than prior
  18 100 figure which was pagination duplication).
- Top account `Crusoe` (HIGH, 2 devs) had **0 activity events in the last
  30 days** — intent tagged HIGH from older signal. Implication: digest
  should widen the activity lookback window or caveat the recency of the
  HIGH score.
- Only 2 developers total at `crusoeenergy.com`; insufficient for a
  function+seniority filter to produce meaningful intersections.

### Leadership filter over-captures "Head of Sales"
- `FUNCTION_KEYWORDS["leadership"]` includes `"head of"`, which matched
  `Head of Sales Development` at the top-ranked account. For a GTM
  workflow targeting dev buyers, this is probably wrong.
- **Not fixing in v1.0** — the agent prompt in `AGENTS.md` will be told
  to prefer `function=engineering` + `seniority=vp` over the bare
  `function=leadership`. Revisit in v1.1 if data shows the keyword set
  still over-captures.

### Sanitisation strategy for fixtures
- All `account_id` / `developer_id` hashed to 8-char prefix (`acc_`/`dev_`).
- Emails: `<redacted>@<domain>` — domain kept as Web3 signal.
- LinkedIn/GitHub URLs: replaced with hashed slug, platform preserved.
- Internal `reo_developer_link` dropped entirely.
- Script: `scripts/live_integration.py` (reusable, deterministic).

---

## Changelog of this file

- **2026-04-20 v3** — pivot from Pinata to self-hosted Agent SDK on Railway (D0-D4), Claw MCP rename, onboarding architecture locked
- **2026-04-16 v2** — post-live-run observations (pagination fix, data quality, filter calibration)
- **2026-04-16 v1** — initial write after pre-build alignment complete
