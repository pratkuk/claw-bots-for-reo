# Heartbeat

> OpenClaw convention: HEARTBEAT.md describes the agent's scheduled/periodic tasks.
> The manifest.json `tasks` array references these by name.

<!-- TO BE AUTHORED IN STEP 4. The single v1.0 task:

     Task name: "Daily intent digest"
     Schedule:  "0 14 * * *" (14:00 UTC daily, per DECISIONS.md)
     Prompt:    see context doc §5 — the end-to-end workflow
                1. get_top_intent_accounts(segment_id=<from USER.md>, limit=10, web3_only=true)
                2. For top 5: activity detail + active developers + key contacts
                3. Synthesise per account: summary + top contact + drafted message
                4. Post to Slack per docs/sample-digest.md format

     Expected output: Slack message matching docs/sample-digest.md structure
-->
