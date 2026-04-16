# Decision Log

> Compact log of locked-in calls. Newest first.
> For the full rationale behind any decision, see `../reo_pinata_agent_context.md`
> (master context) or `docs/api-exploration.md` (API surface evidence).

---

## 2026-04-16 — Pre-build decisions

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
- **File:** `workspace/projects/reo-mcp/web3_domains.py` (frozenset)

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

- **Pinata promo code** — Drew to deliver; blocks only the final deploy test, not build
- **Reo key rotation** — user to verify whether the 19-char key is complete or truncated (still pending reply)
- **Marketplace listing copy** — draft after v1.0 tag, before submission

---

## Changelog of this file

- **2026-04-16 v1** — initial write after pre-build alignment complete
