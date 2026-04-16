# Claw Bots for Reo

> A 1-click deployable OpenClaw agent template that surfaces the Web3 developers showing buying intent for your tool — with drafted outreach messages — in your Slack every morning.

**Status:** v0.1 (pre-release). See [DECISIONS.md](DECISIONS.md) for what's locked in.

---

## What this template does

Every morning, the agent:

1. Scans the accounts in a Reo segment you pre-created (your Web3 target list)
2. Ranks them by developer activity intensity, then dev count
3. For the top 5 accounts, pulls activity detail + most-active contacts
4. Drafts a personalised first-touch message referencing the exact signals
5. Posts a prioritised digest to a Slack channel you pair during bootstrap

Runs autonomously, configurable via slash commands (`/run-digest`, `/adjust schedule`, `/explain <domain>`).

## Who it's for

**Web3 devtool GTM teams** — infra, SDKs, indexers, wallets, chain companies — using [Reo.Dev](https://reo.dev) for revenue intelligence.

It's also useful for Web2 teams with a Reo account: toggle `web3_only=false` and it ranks your full segment.

## What you'll need before deploying

- A **Reo.Dev** account + API key ([request here](mailto:contact@reo.dev) or see [developers.reo.dev](https://developers.reo.dev))
- An ACCOUNT-type **segment** pre-created in the Reo dashboard (`https://web.reo.dev/dashboard/segments`) — the agent ranks accounts within this segment
- A **Slack workspace** where the agent can post
- A **Pinata agents account** at [agents.pinata.cloud](https://agents.pinata.cloud) — promo code if provided by partner

## Deploy (1-click)

1. Click **Deploy** on the [Pinata marketplace listing](https://agents.pinata.cloud) _(link live post-launch)_
2. Enter secrets: `REO_API_KEY`
3. Paste your segment URL when prompted (the agent extracts the UUID)
4. Pair your Slack channel (Pinata walks you through it)
5. Run `/run-digest` to test immediately, or wait for the first scheduled run at 14:00 UTC

## Configuration

| Slash command | What it does |
|---|---|
| `/run-digest` | Run the digest right now |
| `/adjust web3_only=false` | Broaden to all accounts in the segment (turn off allow-list filter) |
| `/adjust limit=10` | Change how many accounts appear in the digest |
| `/adjust schedule "0 14 * * 1-5"` | Change the cron (this example: weekday mornings) |
| `/web3-domains +foo.xyz` | Add a domain to the Web3 allow-list at runtime |
| `/explain <domain>` | Get the full signal breakdown for one account |
| `/set-segment <url-or-uuid>` | Change which segment the agent monitors |

## Example output

See [docs/sample-digest.md](docs/sample-digest.md) for a full sample of what lands in Slack.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Digest is empty | Check your segment has accounts (`list_segments` tool) and they have recent activity |
| Slack messages not arriving | Re-run Slack pairing during bootstrap |
| Agent says "Invalid Segment" | The segment URL/UUID is wrong — open the Reo dashboard, copy the URL after `?segId=` |
| API key rejected | Verify the key in Reo dashboard → Settings → API; rotate if exposed |
| Rate-limited (429) | The server auto-retries with backoff; if persistent, reduce digest frequency |

## Development

```bash
git clone https://github.com/pratkuk/claw-bots-for-reo.git
cd claw-bots-for-reo
cp .env.example .env    # fill in REO_API_KEY
python3 scripts/smoke_test.py
```

See [docs/api-exploration.md](docs/api-exploration.md) for the endpoint surface and response shapes.

## Architecture

- `manifest.json` — Pinata/OpenClaw agent config
- `workspace/` — agent personality, operating rules, scheduled tasks
- `workspace/projects/reo-mcp/` — local FastMCP server wrapping the Reo REST API

## Support

- Reo: [contact@reo.dev](mailto:contact@reo.dev)
- Pinata: [agents.pinata.cloud](https://agents.pinata.cloud)
- Issues with this template: [GitHub Issues](https://github.com/pratkuk/claw-bots-for-reo/issues)

## License

[MIT](LICENSE) © 2026 Pratyush Kukreja
