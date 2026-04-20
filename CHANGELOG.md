# Changelog

All notable changes to this template are documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) •
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (2026-04-20) — Pivot from Pinata to self-hosted

- **Architecture:** dropped Pinata / OpenClaw runtime entirely.
  Replaced with a single self-hosted Python process (Flask +
  slack-bolt + APScheduler) on Railway, driving the Claude Agent SDK
  per digest run. The Agent SDK spawns the Claw MCP as a stdio child.
- **Storage:** per-workspace encrypted `config.json` on a persistent
  volume (Fernet, perms 0600), keyed by Slack `team_id`. Replaces the
  single-tenant `workspace/USER.md` model.
- **Slack:** slack-bolt OAuth install + signed-request verification +
  `chat.postMessage`. Replaces Pinata's `channels.slack` pairing.
- **MCP transport:** stdio child of the Agent SDK. Replaces HTTP on
  port 8787 via Pinata's `routes`.
- **MCP rename:** `workspace/projects/reo_mcp/` → `claw_mcp/`. Tool
  namespace `mcp__reo__*` → `mcp__claw__*`. FastMCP server name
  `reo-mcp` → `claw-mcp`. The name "Reo MCP" inside the company
  refers to Reo's official internal MCP; our server is "Claw MCP".
- **Deleted files:** `manifest.json`, `workspace/BOOTSTRAP.md`,
  `workspace/USER.md` (all Pinata/OpenClaw runtime contracts).
- **Rewritten context docs:** `README.md`, `workspace/TOOLS.md`,
  `workspace/AGENTS.md`, `workspace/HEARTBEAT.md`, `DECISIONS.md`.
- **New docs:** `docs/onboarding-plan.md` — locked spec for the
  multi-tenant `/setup` + `/config` modal flow, config schema,
  build order, and v1 / v1.1 scope.

### Proven (2026-04-20) — via local spikes

- `scripts/spike_agent_sdk.py` — V2 PASS: Claude Agent SDK spawns
  Claw MCP as stdio child, tool call fires, tool result round-trips.
- `scripts/spike_slack_volume_cron.py` — D1 + D2 + D4 PASS: signed
  Slack request handling, volume-persistent state across process
  restart, one entrypoint serving both Slack and cron triggers.
- `scripts/spike_slack_live.py` — end-to-end live: Slack OAuth
  install into a real workspace + `/run-digest` → real Reo API pulls
  + real drafted digest posted back to #reo-intel-test.

### Planned for v1.0 ship (in progress)

See `docs/onboarding-plan.md` for the full 10-step build order.
Summary: per-workspace config store → `/setup` modal → credential
validation → refactor `/run-digest` → APScheduler cron →
`/config` / `/pause` / `/resume` → uninstall handler → welcome DM →
first-run test digest.

### Planned for v1.1

- Per-user configs within a workspace.
- Multi-segment scheduling (one workspace, multiple crons, different
  segments each).
- Pinned-segment override to prevent `default_segment_id` drift on
  manual runs.
- Outreach style / POV preferences (spice level, economic-buyer rules).
- Hosted web setup page (needed if Reo ever adds OAuth).
- Secrets-manager-backed storage (needed for hosted multi-tenant).
- `get_hiring_signals` tool (needs Reo per-account jobs endpoint).
- Weekly signal-quality retrospective as Task 2 in HEARTBEAT.md.
- Telegram channel support.
- Native Web3 tagging if Reo adds a first-class field (retire the
  297-domain allow-list).

## [1.0.0-rc1] — 2026-04-16

First release candidate. Functionally complete, originally targeted
at Pinata's marketplace runtime — that target was abandoned on
2026-04-20 (see Unreleased section above).

### Added
- `workspace/projects/claw_mcp/` — FastMCP server with 5 typed tools
  (`list_segments`, `get_top_intent_accounts`,
  `get_account_activity_detail`, `get_active_developers`,
  `get_key_contacts`).
- `ReoClient` — sync `httpx` wrapper with typed exceptions, 429
  retry honouring `Retry-After`, 5xx exponential backoff, and a
  pagination walker that honours `total_pages` (falls back to
  single-page when the server returns `null`).
- 49-test unit suite covering ranking edge cases, HTTP error
  mapping, pagination walker, Web3 filter case-handling, and
  contact-filter AND semantics.
- `scripts/live_integration.py` — exercises all 5 tools against
  the real Reo API and writes a sanitised fixture to `docs/samples/`.
- Web3 allow-list seeded from 297 real domains in the Reo crypto
  segment. Runtime extension via `/web3-domains +foo.xyz`.
- Workspace agent contracts: `IDENTITY.md`, `SOUL.md`, `AGENTS.md`,
  `HEARTBEAT.md`, `TOOLS.md`. (`BOOTSTRAP.md` and `USER.md` were
  deleted in the 2026-04-20 pivot.)
- `manifest.json` (deleted 2026-04-20) — originally bound the agent
  runtime to Pinata's marketplace: Slack pairing, daily cron
  `0 14 * * *`, MCP server on port 8787 at `/mcp`.
- User-facing `README.md` and this `CHANGELOG.md`.
- MIT license, `.env.example`, ruff config, pinned dependencies.

### Locked-in decisions (see `DECISIONS.md`)
- Ranking: lexicographic `HIGH>MEDIUM>LOW>empty`, tie-break by
  `active_developers_count` desc.
- Confidence tagging: `high` / `medium` / `low` returned with every
  account; agent decides render-time priority (Option 3 from the
  design conversation).
- Agent operates _within_ a user-selected segment — no global account
  crawl, no domain-to-account lookup.
- Slack only in v1.0; Telegram/Discord parked for v1.1.
- Single MCP server ships inside the template repo; ClawHub
  extraction deferred to post-adoption.

### Known limitations
- `/segments` endpoint returns every row on page 1 with
  `total_pages: null` and ignores `?page=N`; walker handles this as
  a single-page contract.
- `get_key_contacts(function="leadership")` over-captures on
  "Head of Sales"-style titles. Agent prompt works around it by
  preferring `function=engineering + seniority=vp`; revisit in v1.1
  if filter calibration proves insufficient on real data.
- 161/297 accounts in the reference Web3 segment have empty
  `developer_activity` — returned with `confidence: "low"` and
  de-prioritised, not hidden.

[Unreleased]: https://github.com/pratkuk/claw-bots-for-reo/compare/v1.0.0-rc1...HEAD
[1.0.0-rc1]: https://github.com/pratkuk/claw-bots-for-reo/releases/tag/v1.0.0-rc1
