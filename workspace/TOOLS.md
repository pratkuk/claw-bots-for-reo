# Tools & Environment

> OpenClaw convention: TOOLS.md documents the agent's environment —
> MCP endpoints, external services, device nicknames, etc. Agent reads this
> to know where it's running and what it has access to.

<!-- TO BE AUTHORED IN STEP 4. Must list:

     MCP server:
       - URL: (runtime-resolved via Pinata port-forwarding; path /mcp)
       - Auth: x-internal-token header with REO_MCP_INTERNAL_TOKEN
       - 5 tools: list_segments, get_top_intent_accounts,
                  get_account_activity_detail, get_active_developers,
                  get_key_contacts
       - See docs/api-exploration.md for input/output shapes

     Reo (via MCP — agent never calls Reo REST directly):
       - Base URL: https://integration.reo.dev
       - Auth: x-api-key header
       - Rate limit: honour X-RateLimit-* headers, backoff on 429

     Slack:
       - Provisioned via Pinata channels.slack pairing
       - Post to channel stored in USER.md
       - DM policy: pairing (only paired user can interact)
-->
