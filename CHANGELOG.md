# Changelog

All notable changes to this template are documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) •
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned for v1.1
- Extract `reo_mcp` into a standalone ClawHub skill for reuse in
  other templates.
- `get_hiring_signals` tool (needs Reo per-account jobs endpoint).
- Weekly signal-quality retrospective as Task 2 in HEARTBEAT.md.
- Telegram channel support (Web3 GTM teams are Telegram-heavy).
- Native Web3 tagging if Reo adds a first-class field (retire the
  297-domain allow-list).

## [1.0.0-rc1] — 2026-04-16

First release candidate. Functionally complete, pending live deploy
against Pinata's marketplace runtime.

### Added
- `workspace/projects/reo_mcp/` — FastMCP server with 5 typed tools
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
- OpenClaw workspace contracts: `IDENTITY.md`, `SOUL.md`,
  `AGENTS.md`, `BOOTSTRAP.md`, `HEARTBEAT.md`, `TOOLS.md`, `USER.md`.
- `manifest.json` — binds the agent runtime: Slack pairing, daily cron
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
