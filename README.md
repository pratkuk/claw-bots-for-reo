# Claw Bots for Reo

> A self-hosted Slack app that surfaces the Web3 developers showing
> buying intent for your tool — with drafted outreach messages — in
> your Slack every morning. Built on the Claude Agent SDK.

**Status:** multi-tenant onboarding in progress. The single-tenant
spike (`scripts/spike_slack_live.py`) is live end-to-end; the next
build is the real multi-workspace service defined in
[docs/onboarding-plan.md](docs/onboarding-plan.md).

---

## What this app does

Every morning, for each installed Slack workspace:

1. Scans accounts in the Reo segment that workspace configured (their
   Web3 target list).
2. Ranks them: `developer_activity` tier (HIGH > MEDIUM > LOW > empty),
   tie-broken by `active_developers_count` descending.
3. Applies a Web3 allow-list of 297 seed domains (extendable per
   workspace).
4. For the top 5 accounts, pulls activity detail + most-active contacts.
5. Drafts a personalised first-touch message referencing the exact signals.
6. Posts a prioritised digest to the Slack channel that workspace picked
   during `/setup`.

Runs autonomously on a per-workspace schedule. Configurable via Slack
slash commands (`/setup`, `/config`, `/run-digest`, `/pause`, `/resume`).

## Who it's for

**Web3 devtool GTM teams** — infra, SDKs, indexers, wallets, chain
companies — using [Reo.Dev](https://reo.dev) for revenue intelligence.

Also useful for Web2 teams with a Reo account: toggle `web3_only=false`
in `/config` and it ranks your full segment.

## Architecture (short version)

- **Host:** single Python process running Flask + slack-bolt + APScheduler.
- **Agent loop:** Claude Agent SDK (`claude-agent-sdk`) spawned per
  digest run; it drives the prompt workflow in `workspace/HEARTBEAT.md`.
- **Tools:** a local FastMCP server (Claw MCP) at
  `workspace/projects/claw_mcp/` launched as a **stdio child** of the
  Agent SDK; it wraps Reo's REST API behind 5 typed tools.
- **Per-workspace state:** one encrypted `config.json` per `team_id`
  on a persistent volume (Railway volume or equivalent).
- **Slack:** OAuth install + slash commands; bot tokens stored by the
  host's `FileInstallationStore`.

See [docs/onboarding-plan.md](docs/onboarding-plan.md) for the in-flight
multi-tenant build and [DECISIONS.md](DECISIONS.md) for the locked
architectural calls.

## Install flow (target, once v1 ships)

1. Click the install link for your Slack workspace (OAuth).
2. Installer gets a welcome DM: "Run `/setup` to get started."
3. `/setup` opens a Slack modal — paste Reo API key, pick tenant,
   pick segment from a live dropdown, pick channel, pick schedule.
4. The host validates the key, saves config, runs a test digest to the
   installer's DM so they see the shape.
5. Daily scheduled digests start posting to the chosen channel.

## Configuration (slash commands)

| Command | Effect |
| --- | --- |
| `/setup` | First-time config (modal) |
| `/config` | Edit existing config (same modal, pre-filled) |
| `/run-digest` | Run the digest right now (segment picker pre-fills to default) |
| `/pause` | Pause scheduled digests |
| `/resume` | Re-enable scheduled digests |
| `/explain <domain>` | Full signal breakdown for one account |
| `/contacts <domain> [function=X] [seniority=Y]` | Just the contacts |

## Example output

See [docs/sample-digest.md](docs/sample-digest.md) for the target Slack
output shape.

## Development

```bash
git clone https://github.com/pratkuk/claw-bots-for-reo.git
cd claw-bots-for-reo

python3 -m venv .venv
source .venv/bin/activate
pip install -r workspace/projects/claw_mcp/requirements.txt
pip install claude-agent-sdk slack-bolt flask python-dotenv

cp .env.example .env
$EDITOR .env   # fill in REO_API_KEY, Slack app creds, REO_TEST_SEGMENT_ID

# Unit tests for the Claw MCP (49 passing)
python -m pytest workspace/projects/claw_mcp/tests -v

# Lint + format
python -m ruff check workspace/projects/claw_mcp/
python -m ruff format workspace/projects/claw_mcp/

# End-to-end integration against your segment + write sanitised fixture
python scripts/live_integration.py

# Full single-tenant spike (Slack OAuth install + /run-digest → real digest)
# Requires an ngrok tunnel for the Slack webhook.
python scripts/spike_slack_live.py
```

See [docs/api-exploration.md](docs/api-exploration.md) for the Reo
endpoint surface and response shapes.

## Architecture (files)

- `scripts/spike_slack_live.py` — current single-tenant spike (end-to-end
  proof; being refactored into the multi-tenant service per
  `docs/onboarding-plan.md`).
- `workspace/*.md` — agent identity, voice, operating rules, scheduled
  tasks. Loaded as the Agent SDK system prompt.
- `workspace/projects/claw_mcp/` — local FastMCP server wrapping Reo's
  REST API behind 5 typed tools:
  - `list_segments`
  - `get_top_intent_accounts`
  - `get_account_activity_detail`
  - `get_active_developers`
  - `get_key_contacts`

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Digest is empty | Check your segment has accounts with recent activity — `/explain <domain>` reveals raw signals |
| Slack messages not arriving | Confirm the bot was added to the configured channel |
| "segment not visible" | The segment UUID is wrong or the API key can't see it — run `/config` and pick again |
| `Reo API key rejected` | Rotate the key in Reo Settings → API, update it via `/config` |
| Rate-limited (429) | The MCP server auto-retries with backoff; if persistent, lower `digest_limit` in `/config` |

## Support

- Reo: [contact@reo.dev](mailto:contact@reo.dev)
- Issues with this project: [GitHub Issues](https://github.com/pratkuk/claw-bots-for-reo/issues)

## License

[MIT](LICENSE) © 2026 Pratyush Kukreja
