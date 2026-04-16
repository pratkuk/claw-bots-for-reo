# Reo API — Exploration Findings

> Captured 16 Apr 2026. Probing `integration.reo.dev` with a live API key.
> All endpoints below tested and confirmed. Docs at https://developers.reo.dev.

## Base URL & auth

- **Base:** `https://integration.reo.dev`
- **Auth:** single header — `x-api-key: <key>`
- **No tenant ID** needed — API key is the only scoping.

## Confirmed endpoints

| Method | Path | Returns | Notes |
|---|---|---|---|
| `GET` | `/segments` | List of segments (ACCOUNT, BUYER type) with `id`, `name`, `type`, `owner` | Paginated with `?page=` |
| `GET` | `/audiences` | List of audiences with `filter` objects (location, tech_function, …) | Audiences wrap segments with extra filters |
| `GET` | `/segment/{id}/accounts` | Rich account rows — see shape below | **Singular** `/segment/` not `/segments/` |
| `GET` | `/account/{id}/activities` | Per-developer activity stream at an account | Requires account UUID, not domain |
| `GET` | `/account/{id}/developers` | Developers at an account with contacts + activity score | Requires account UUID |

## Endpoints that **do not exist** (tested, 404)

- `GET /accounts`, `GET /account` — no global list. Accounts are reachable only via a segment.
- `GET /account/by-domain/{domain}`, `/accounts/lookup?domain=…` — **no domain → account lookup**.
- `GET /account/{id}/jobs`, `/hiring`, `/linkedin`, `/profiles`, `/tech-stack`, `/contacts`, `/buyers` — none exist.
- `GET /buyers`, `/lists`, `/developers`, `/activities` (unscoped) — none exist.
- No `/openapi.json` / `/swagger.json` — docs are a ReDoc-rendered SPA with the spec embedded in JS state.

## Response shapes

### `GET /segments` (sample row)
```json
{
  "id": "1c40e853-…",
  "name": "adi-accSanity",
  "type": "ACCOUNT",
  "owner": "aditya@reo.dev"
}
```

### `GET /segment/{id}/accounts` (sample row — **the richest single endpoint**)
```json
{
  "id": "0f0fc88e-…",
  "account_name": "Aerospike",
  "account_domain": "aerospike.com",
  "country": "United States",
  "industry": "Computer Software",
  "active_developers_count": 58,
  "developer_activity": "HIGH",        // enum: HIGH | MEDIUM | LOW (likely)
  "customer_fit": "STRONG",             // enum: STRONG | … (likely)
  "first_activity_date": "2024-02-29",
  "last_activity_date": "2026-04-15",
  "annual_revenue": "$10M-$50M",
  "tags": "Solutions Page,Buyer Active,Product Sign-up,…",
  "tech_functions_count": {
    "ai_ml_count": 0,
    "backend_engineering_count": 83,
    "cloud_infrastructure_count": 39,
    "data_analytics_count": 5,
    "devops_platform_reliability_count": 18,
    "engineering_count": 0,
    …
  }
}
```

### `GET /account/{id}/activities` (sample row)
```json
{
  "actor": "Gaurav Deshpande",
  "page": "Reo.dev | Revenue Intel Tool",
  "activity_type": "PAGE_VISIT",       // also: GITHUB, COPY_COMMAND, IDENTITY_CAPTURE, …
  "activity_source": "PRODUCT_JS",
  "copied_text": null,
  "developer_designation": "Chief Marketing Officer",
  "country": "United States",
  "activity_date": "2026-04-16",
  "developer_linkedin": "https://www.linkedin.com/in/gauravdeshpande",
  "activity_info": "https://…",
  "developer_id": "d0ed5421-…"
}
```

### `GET /account/{id}/developers` (sample row)
```json
{
  "id": "44218493-…",
  "org_id": "0f0fc88e-…",
  "developer_name": "paria sheshpari",
  "developer_first_name": "paria",
  "developer_last_name": "sheshpari",
  "developer_linkedin": "https://www.linkedin.com/in/pariasheshpari",
  "developer_github": "",
  "developer_business_email": "psheshpari@aerospike.com",
  "first_activity_date": "2025-09-02",
  "last_activity_date": "2026-04-15",
  "tags": "Product Login",
  "city": "Austin",
  "state": "Texas",
  "country": "United States",
  "designation": "Enterprise Account Executive",
  "activity_score": "LOW",             // enum: HIGH | MEDIUM | LOW
  "activity_score_numeric": 16.43,
  "agent_tags": "",
  "employee_count_range": "251-1K",
  "reo_developer_link": "https://web.reo.dev/dashboard/developers?devId=…"
}
```

## Architectural implications

### 1. The template operates **within a segment**, not globally.
The agent can't "find top Web3 accounts across your whole Reo workspace" because there's no global account list. The user must:
- Pre-create an ACCOUNT segment in Reo's UI (e.g. "Q2 Outbound Targets")
- Provide its `segment_id` to the agent during bootstrap
- The agent then ranks accounts **within that segment** by `developer_activity` + `active_developers_count`

This is a UX constraint but actually a feature: it matches how Reo customers already work (segments are their existing workflow).

### 2. Web3 classification is **heuristic**, not native.
Sampled industries in the test segment: `Computer Software`, `Financial Services`, `Internet`, `Marketing & Advertising`, `Hospital & Health Care`, etc. No `Web3`, `Blockchain`, or `Cryptocurrency` values observed. Tags are **user-defined**, so cannot be relied on either.

Options for `web3_only` filter:
- **Allow-list** — maintained list of ~500 known Web3 org domains (good: simple, predictable; bad: misses new entrants)
- **Heuristic** — domain suffix patterns (`.xyz`, `.crypto`, `.eth`) + known-keyword industry check (`Blockchain Services` if it appears) + GitHub activity on topic-tagged repos
- **User-configurable** — ship an allow-list baked in, expose `/config web3-domains +foo.bar` slash command

Recommend: **allow-list with override**. v1.0 ships a ~200-domain curated list; users can extend it.

### 3. `get_hiring_signals` from context §3 is **not available** via public REST.
No per-account jobs endpoint. Either:
- **Drop from v1** (ship 4 MCP tools, add hiring in v1.1 when Reo exposes it)
- **Use LinkedIn enrichment** — infer hiring intent from developer `designation` changes in `/account/{id}/developers` history (weak signal)
- **Scrape job boards** (complex, out of scope)

Recommend: **drop from v1**, note it clearly in README as "coming in v1.1."

## v1.0 MCP tool list — final

| # | Tool | Wraps | Notes |
|---|---|---|---|
| 1 | `list_segments()` | `GET /segments` | Bootstrap helper; filters to `type=ACCOUNT` client-side |
| 2 | `get_top_intent_accounts(segment_id, limit=10, web3_only=True)` | `GET /segment/{id}/accounts` | Applies ranking + `web3_only` allow-list filter |
| 3 | `get_account_activity_detail(account_id, days=7)` | `GET /account/{id}/activities` | Client-side filter on `activity_date` window |
| 4 | `get_active_developers(account_id, limit=3)` | `GET /account/{id}/developers` | Ordered by `activity_score_numeric` desc |
| 5 | `get_key_contacts(account_id, function=None, seniority=None)` | `GET /account/{id}/developers` (client-side filter) | Filters by `designation` substring matches |

~~`get_hiring_signals`~~ — **deferred to v1.1.** No per-account jobs endpoint in public REST.

## Ranking rule for `get_top_intent_accounts` (v1.0, locked)

```python
ACTIVITY_WEIGHT = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "": 0, None: 0}

def rank_key(acct: dict) -> tuple[int, int]:
    return (
        ACTIVITY_WEIGHT.get(acct.get("developer_activity"), 0),
        acct.get("active_developers_count") or 0,
    )

# sorted(accounts, key=rank_key, reverse=True)
```

Deterministic + explainable. No weighted score magic until we have usage data.

### Empty `developer_activity` — handling

The Reo seed segment (297 accounts) showed:

| `developer_activity` | Count |
|---|---|
| `HIGH` | 2 |
| `MEDIUM` | 2 |
| `LOW` | 132 |
| `""` (empty) | 161 |

Empty values sort below `LOW` but accounts are still returned — the digest may show them if the segment is thin on HIGH/MEDIUM signals. The tool response includes the raw `developer_activity` field so the agent can label each row accurately (no silent gap-filling).

## Web3 allow-list — seed

File: [`docs/samples/web3_allowlist_seed.txt`](samples/web3_allowlist_seed.txt) — 297 unique domains from the user's Reo segment `da8416c8-7dc1-4ab9-9fca-d921620dbce3` ("Web3 Enrich" per the dashboard).

Sample entries: `a16z.com`, `circle.com`, `blockchain.com`, `chainalysis.com`, `stellar.org`, `ockam.io`, `crusoeenergy.com`, `merklescience.com`, `falconx.io`.

In the MCP server this ships as `workspace/projects/reo-mcp/web3_domains.py` with a frozenset for O(1) lookups. Users can extend via `/web3-domains +foo.xyz` at runtime.

## Segment ID bootstrap flow

The agent accepts either:
1. Full dashboard URL: `https://web.reo.dev/dashboard/accounts?segId=<UUID>` (agent parses UUID out)
2. Bare UUID

It then calls `list_segments()` to resolve the UUID → segment name for user confirmation, and persists it in `workspace/USER.md` as:

```yaml
default_segment_id: da8416c8-7dc1-4ab9-9fca-d921620dbce3
default_segment_name: Web3 Enrich
```


## Rate limiting (from docs)

- 429 when exceeded
- Response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`
- **Implementation note:** MCP server must honour these; add exponential backoff wrapper around the HTTP client.

## Pagination

- Query param: `page` (integer)
- Response includes: `total_pages`, `next_page`
- List insertion limit: 1000 rows per call
