# Claw Bots for Reo

> A 1-click deployable OpenClaw agent template that surfaces the Web3
> developers showing buying intent for your tool — with drafted outreach
> messages — in your Slack every morning.

**Status:** v1.0.0-rc1 (release candidate). See
[DECISIONS.md](DECISIONS.md) for what's locked in.

---

## What this template does

Every morning, the agent:

1. Scans the accounts in a Reo segment you pre-created (your Web3 target list).
2. Ranks them: `developer_activity` tier (HIGH > MEDIUM > LOW > empty),
   tie-broken by `active_developers_count` descending.
3. Applies a Web3 allow-list of 297 seed domains (extendable at runtime).
4. For the top 5 accounts, pulls activity detail + most-active contacts.
5. Drafts a personalised first-touch message referencing the exact signals.
6. Posts a prioritised digest to a Slack channel you pair during bootstrap.

Runs autonomously. Configurable via slash commands (`/run-digest`,
`/adjust schedule`, `/explain <domain>`, `/segment <url>`).

## Who it's for

**Web3 devtool GTM teams** — infra, SDKs, indexers, wallets, chain
companies — using [Reo.Dev](https://reo.dev) for revenue intelligence.

It's also useful for Web2 teams with a Reo account: toggle
`/adjust web3_only=false` and it ranks your full segment.

## What you'll need before deploying

- A **Reo.Dev** account + API key ([contact@reo.dev](mailto:contact@reo.dev)
  or see [developers.reo.dev](https://developers.reo.dev)).
- An **ACCOUNT-type segment** pre-created in the Reo dashboard
  (`https://web.reo.dev/dashboard/segments`) — the agent ranks accounts
  _within_ a segment. It doesn't crawl Reo's full universe.
- A **Slack workspace** where the agent can post.
- A **Pinata agents account** at [agents.pinata.cloud](https://agents.pinata.cloud).

## Deploy (1-click)

1. Click **Deploy** on the [Pinata marketplace listing](https://agents.pinata.cloud)
   _(link live post-launch)_.
2. Enter secrets: `REO_API_KEY`, `REO_MCP_INTERNAL_TOKEN` (generate any
   32+ char random string).
3. The agent's bootstrap DMs you in Slack — paste your segment URL
   when prompted (it extracts the UUID).
4. Pair your Slack channel (Pinata walks you through it).
5. Run `/run-digest` to test immediately, or wait for the first
   scheduled run at 14:00 UTC.

Full first-run flow is documented in
[workspace/BOOTSTRAP.md](workspace/BOOTSTRAP.md).

## Configuration (slash commands)

| Command | Effect |
| --- | --- |
| `/run-digest` | Run the digest right now |
| `/adjust web3_only=false` | Broaden to all accounts in the segment |
| `/adjust limit=10` | Change how many accounts appear in the digest |
| `/adjust schedule "0 14 * * 1-5"` | Change the cron (e.g. weekday mornings) |
| `/web3-domains +foo.xyz` | Add a domain to the Web3 allow-list at runtime |
| `/web3-domains -foo.xyz` | Remove a user-added domain |
| `/explain <domain>` | Full signal breakdown for one account |
| `/contacts <domain> [function=X] [seniority=Y]` | Just the contacts |
| `/segment <url-or-uuid>` | Change which segment the agent monitors |

Preferences persist in [workspace/USER.md](workspace/USER.md). Rule set
lives in [workspace/AGENTS.md](workspace/AGENTS.md).

## Example output

See [docs/sample-digest.md](docs/sample-digest.md) for the target Slack
output shape.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Digest is empty | Check your segment has accounts and they have recent activity — `/explain <domain>` reveals raw signals |
| Slack messages not arriving | Re-run Slack pairing during bootstrap |
| Agent says "segment not visible" | The segment URL/UUID is wrong or the API key can't see it — open the Reo dashboard, copy the URL after `?segId=` |
| `Reo API key rejected` | Rotate the key in Reo Settings → API, update the `REO_API_KEY` secret in the agent's secret store |
| Rate-limited (429) | The MCP server auto-retries with backoff; if persistent, reduce `digest_limit` |
| "MCP server down — will retry tomorrow" | Check `scripts.start` logs in the Pinata agent console |

## Development

```bash
git clone https://github.com/pratkuk/claw-bots-for-reo.git
cd claw-bots-for-reo

# Create venv + install deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r workspace/projects/reo_mcp/requirements.txt

# Fill in REO_API_KEY and REO_TEST_SEGMENT_ID
cp .env.example .env
$EDITOR .env

# Unit tests (49 passing)
python -m pytest workspace/projects/reo_mcp/tests -v

# Lint + format
python -m ruff check workspace/projects/reo_mcp/
python -m ruff format workspace/projects/reo_mcp/

# Smoke test against live Reo API (auth probe only)
python scripts/smoke_test.py

# End-to-end integration against your segment + write sanitised fixture
python scripts/live_integration.py
```

See [docs/api-exploration.md](docs/api-exploration.md) for the
endpoint surface and response shapes, and [DECISIONS.md](DECISIONS.md)
for ranking, filter, and architecture calls.

## Architecture

- `manifest.json` — Pinata / OpenClaw agent config.
- `workspace/*.md` — agent identity, voice, operating rules, scheduled tasks.
- `workspace/projects/reo_mcp/` — local FastMCP server that wraps Reo's
  REST API behind 5 typed tools:
  - `list_segments` (bootstrap)
  - `get_top_intent_accounts` (entry point for the daily digest)
  - `get_account_activity_detail`
  - `get_active_developers`
  - `get_key_contacts` (function + seniority filter)

The MCP server runs inside the Pinata container (via `scripts.start`)
and is exposed on port 8787 at path `/mcp`. The agent calls it over
HTTP with a shared-secret header (`x-internal-token`).

## Support

- Reo: [contact@reo.dev](mailto:contact@reo.dev)
- Pinata: [agents.pinata.cloud](https://agents.pinata.cloud)
- Issues with this template: [GitHub Issues](https://github.com/pratkuk/claw-bots-for-reo/issues)

## License

[MIT](LICENSE) © 2026 Pratyush Kukreja
