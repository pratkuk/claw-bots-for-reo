# Operating Rules

> OpenClaw convention: AGENTS.md is the agent's operating manual.
> Memory conventions, safety rails, output formats, tool-use discipline.
>
> **Distinct from SOUL.md** — AGENTS.md governs behaviour; SOUL.md governs voice.
> When they conflict, AGENTS.md wins (rules trump voice).

<!-- TO BE AUTHORED IN STEP 4. Must cover:
     1. Memory conventions
        - USER.md schema: default_segment_id, default_segment_name, tz, slack_channel
        - What to save vs. not save (see parent CLAUDE.md memory guidelines)
     2. Tool-use discipline
        - Which MCP tools to call for which intent
        - Pagination + retry behaviour
        - Rate-limit handling: stop & surface rather than thrash
     3. Output format rules
        - Digest Slack post structure (see docs/sample-digest.md)
        - One draft message per top-5 account
        - Never output raw API responses; always synthesise
     4. Safety
        - No PII to public channels (only to paired Slack)
        - No email/LinkedIn URLs in messages that get logged externally
        - Refuse if a user asks for a "cold blast" across hundreds of contacts
     5. Bootstrap flow
        - First run: walk user through API key → segment URL → Slack pair → test digest
        - Parse segId UUID from pasted Reo dashboard URL
-->
