# MCP server — to be built in Step 2

The Reo MCP server (FastMCP + Python) will live here. See DECISIONS.md for the
5-tool list and ranking rules.

Structure (to be created in Step 2):
  reo-mcp/
    server.py           # FastMCP entry point, auth middleware
    reo_client.py       # HTTP client for integration.reo.dev
    web3_domains.py     # allow-list frozenset (seeded from docs/samples/web3_allowlist_seed.txt)
    tools/
      activity.py       # list_segments, get_top_intent_accounts, get_account_activity_detail, get_active_developers
      contacts.py       # get_key_contacts
    tests/
      test_ranking.py
      test_reo_client.py (with responses-mocked fixtures)
    requirements.txt

