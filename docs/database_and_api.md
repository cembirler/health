# Database & API Reference

Single MySQL 8 database (`health`) on the host's homebrew install. Two
logical groups of tables: **pricing** (what the agent searches over,
sourced exclusively from hospital MRFs) and **chat** (orthogonal —
powers the agent UI, no FK into pricing).

Source of truth for the schema: [`packages/db/db/models.py`](../packages/db/db/models.py).
This doc explains the *why* and the query patterns. Companion: the
[ingest](../.claude/skills/ingest/SKILL.md) skill, which is the rule
book for what lands in these tables.

Schema-change flow:

```
edit models.py
  → uv run alembic revision --autogenerate -m "<msg>"
  → uv run alembic upgrade head
```

Migrations live in `packages/db/migrations/versions/`. All connections
pin to UTC at connect time (see `packages/db/db/session.py`) so MySQL
`CURRENT_TIMESTAMP` defaults produce real UTC, not server-local.

---

## Pricing data model

```
┌─────────┐                                           ┌──────────┐
│  codes  │ (reference dim — CPT/HCPCS/MS-DRG/ICD/NDC)│ mrfs_csv │ (append-only download log)
└────┬────┘                                           └────┬─────┘
     │                                                     │
     │   ┌─────────────┐    ┌────────────────┐             │
     │   │  hospitals  │ ───┤ hospital_mrfs  │ ────────────┤
     │   └────┬────────┘    │   (junction)   │             │
     │        │             └────────────────┘             │
     │        │                                            │
     │   ┌────┴───────────┐                                │
     │   │ hospital_npis  │ (1:N child of hospitals)       │
     │   └────────────────┘                                │
     │                                                     │
     │    ┌──────────────────────────────┐                 │
     │    │   hospital_code_charges      │ ────────────────┘
     │    │   (1 row per service per MRF)│
     │    │   gross / cash / min / max   │
     │    └──────────────┬───────────────┘
     │                   │
     │    ┌──────────────┴───────────────┐
     └────│ hospital_code_charge_codes   │ (M:N junction — 1-4 codes per charge)
          └──────────────────────────────┘
                         │
                         ▼  (parent charge)
          ┌──────────────────────────────┐
          │   hospital_payer_rates       │
          │   (N rows per charge —       │
          │    one per payer×plan)       │
          └──────────────────────────────┘
```

Two dims (`codes`, `hospitals` + `hospital_npis` child), one provenance
log (`mrfs_csv`), two M:N junctions (`hospital_mrfs`,
`hospital_code_charge_codes`), two facts (`hospital_code_charges`,
`hospital_payer_rates`). No canonical payer table — payer matching is
`LIKE` on `payer_name_raw`.

---

## Tables

### codes

One row per **billing code**. Reference dim joined by every charge
through `hospital_code_charge_codes`.

| column | source | notes |
|---|---|---|
| `code` | derived from `code\|N` + `code\|N\|type` (MRF row 3) | `VARCHAR(32)`, UNIQUE. Combined `<TYPE>:<value>` (e.g. `"CPT:99213"`, `"NDC:00069-0150"`, `"CDM:SUP-15000"`). Type uppercase, no whitespace. No whitelist — every code MRF publishers list lands here, including hospital-internal `LOCAL` / `CDM` / `RC`. |
| `official_description` | CMS HCPCS / DRG / ICD / NDC public files | NULL for CPT (AMA licensing) and for hospital-internal types. |
| `most_common_description` | modal `description` across hospitals | Fallback when `official_description` is NULL — and the only descriptor for internal types. |
| `gemma_description` | Gemma-generated | User-facing consumer-friendly text. |
| `category`, `typical_setting` | AHRQ CCSR + code-range rules | Optional tagging. `typical_setting` free-form `VARCHAR(32)`. |
| `source`, `source_date` | bookkeeping | Which provenance backed the descriptions. |

**Indexes**: PK on `id`, UNIQUE `idx_code` on `code`. Common reads:
exact `WHERE code = 'CPT:99213'`; type-prefix scan `WHERE code LIKE 'CPT:%'`.

### hospitals

One row per **physical location** (not system). Source of truth is the
MRF row 1-2 header — no CMS seed, no external augmentation.

| column | source | notes |
|---|---|---|
| `ein` | first 9 digits of MRF filename (§180.50) | NULLable. |
| `hospital_name` | `hospital_name` (row 1) | Often the system; equals `location_name` for single-location publishers. |
| `location_name` | v2 `hospital_location` / v3 `location_name` (row 1) | Always populated. Parser maps both names. |
| `hospital_address` | `hospital_address` (row 1) | Verbatim free-text. |
| `city`, `state`, `zip` | parsed from `hospital_address` | At ingest. |
| `lat`, `lng` | US Census Geocoder + Nominatim fallback | Populated post-ingest by `geocode_hospitals.py`. |
| `license_number`, `license_state` | `license_number\|<state>` (row 1 — **state in header**) | Cell value is the number; state lives in the column name. |

Soft identity (no natural unique key without CCN):
`(ein, license_number, license_state, location_name)`. Loader upserts on
that tuple. CCN, website, hospital_type, ownership are not tracked
because they don't appear in MRFs.

**Indexes**: PK on `id`, `idx_ein` (ingest upsert), `idx_city`, `idx_state`,
`idx_zip` (location filters), `idx_hospital_name` (autocomplete).

### hospital_npis

1:N child. One row per `(hospital, Type 2 NPI)`. Normalizes the
pipe-separated `type_2_npi` cell from MRF row 1-2.

Composite PK `(hospital_id, npi)`. `idx_npi` on `npi` for "which hospital
owns this NPI?" lookups.

### mrfs_csv

Append-only download log. **No UNIQUE on URL/filename** — re-fetches
are kept as separate snapshots distinguished by `last_updated_on`. This
gives a free price history.

| column | source | notes |
|---|---|---|
| `mrf_url` | discovery URL | `VARCHAR(768)` (InnoDB utf8mb4 index ceiling: 768 × 4 = 3072). |
| `filename` | `<ein>[-<npi>]_<slug>_standardcharges.<ext>` | Local filename only. |
| `last_updated_on` | `last_updated_on` (row 1) | `VARCHAR(10)` `YYYY-MM-DD`. Freshness key. |
| `version` | `version` (row 1) | `v2.x`, `v3.0`, CY2026 variants. |
| `attestation` | TRUE/FALSE cell value | v2: footer; v3: row 1. The ~1.5 KB legal blob is the column *header*; we store only the boolean. |
| `attester_name` | `attester_name` (row 1, v3 only) | CY2026; NULL on v2.x. |
| `contact_name`, `contact_email` | `cms-hpt.txt` discovery | Provenance from discovery feed, not the MRF body. |
| `content_sha256` | SHA-256 of bytes | `VARCHAR(64)` UNIQUE — **dedupes identical files across publishers**. |

**Indexes**: PK, UNIQUE `idx_content_sha256`, `idx_last_updated_on`.

### hospital_mrfs

M:N junction between `hospitals` and `mrfs_csv`. One MRF can cover many
hospitals (bundled system MRFs); one hospital appears in many MRFs over
time (per-campus + quarterly republishes).

Composite PK `(hospital_id, mrf_id)`. Both FKs cascade on delete.

### hospital_code_charges

First fact table. One row per **service** per MRF snapshot.
**Charge-level facts that don't vary per payer** — gross / cash /
de-identified min / de-identified max.

Codes attach via [`hospital_code_charge_codes`](#hospital_code_charge_codes),
not on this row. CMS allows up to 4 codes per MRF row (same service
expressible as CPT + HCPCS + revenue, etc.); all share the same price.

| column | source | notes |
|---|---|---|
| `hospital_id`, `mrf_id` | FK NOT NULL, cascade on delete | |
| `setting` | `setting` (row 3) | Free-form `VARCHAR(32)`. Nullable. |
| `description` | `description` (row 3) | Raw MRF text. Debug-only; agent renders `codes.*_description` instead. |
| `modifiers` | `modifiers` (row 3) | `VARCHAR(64)`. Pipe-separated when multiple. |
| `drug_unit_of_measurement` | `drug_unit_of_measurement` (row 3) | `VARCHAR(32)`. NDC rows only. |
| `drug_type_of_measurement` | `drug_type_of_measurement` (row 3) | `VARCHAR(8)`. NDC rows only. |
| `additional_generic_notes` | `additional_generic_notes` (row 3) | `TEXT`. |
| `gross_charge` | `standard_charge\|gross` (row 3) | `DECIMAL(14,2)`. |
| `discounted_cash_price` | `standard_charge\|discounted_cash` (row 3) | `DECIMAL(14,2)`. |
| `min_negotiated_charge` | `standard_charge\|min` (row 3) | De-identified summary across all payers. |
| `max_negotiated_charge` | `standard_charge\|max` (row 3) | De-identified summary. |

No UNIQUE constraint — re-ingest protection comes from
`mrfs_csv.content_sha256` UNIQUE. Snapshots remain append-only; old
rows stay as price history.

**Indexes**: `idx_hospital_id`, `idx_mrf_id`. The "cheapest for code X
near me" path runs through the junction (`idx_code_id`), not this table.

### hospital_code_charge_codes

M:N junction. 1-4 rows per charge — one per non-empty `code|N` after
type collapse.

| column | notes |
|---|---|
| `hospital_code_charge_id` | FK, cascade on delete. |
| `code_id` | FK, RESTRICT — don't orphan junction rows. |

Composite PK `(hospital_code_charge_id, code_id)`. `idx_code_id` is the
primary read path for "all charges for code X".

### hospital_payer_rates

Second fact table. One row per `(charge × payer × plan)`.
**Per-payer facts**: negotiated charges, methodology, allowed-amount
stats.

| column | source | notes |
|---|---|---|
| `hospital_code_charge_id` | FK NOT NULL, cascade on delete | |
| `mrf_id` | FK (denormalized — always = parent charge's `mrf_id`) | Lets freshness queries skip the charge→mrf join. Set by loader since 2026-05-17. |
| `payer_name_raw` | `payer_name` (row 3) | Verbatim. **No canonicalization** — agent uses multi-pattern `LIKE`. |
| `plan_name` | `plan_name` (row 3) | Verbatim per-plan within a payer's portfolio. |
| `negotiated_dollar` | `standard_charge\|negotiated_dollar` | `DECIMAL(14,2)`. At least one of (dollar, percentage, algorithm) must be set when payer/plan are populated. |
| `negotiated_percentage` | `standard_charge\|negotiated_percentage` | `DECIMAL(8,4)`. |
| `negotiated_algorithm` | `standard_charge\|negotiated_algorithm` | Free text. |
| `methodology` | `standard_charge\|methodology` | `VARCHAR(64)`. Common values: `case_rate`, `fee_schedule`, `percent_of_billed_charges`, `per_diem`, `other`. Not constrained. |
| `estimated_allowed_amount` | `estimated_allowed_amount` (v2 only) | `DECIMAL(14,2)`. Replaced by percentile stats in v3. |
| `median_allowed_amount` | `median_amount` (v3, CY2026) | Required when negotiated is a percentage/algorithm. |
| `p10_allowed_amount` | `10th_percentile` (v3) | |
| `p90_allowed_amount` | `90th_percentile` (v3) | |
| `allowed_amounts_count` | `count` (row 3) | **`VARCHAR(16)`, not INT** — `"1 through 10"` is a valid anonymized small-count value. |
| `additional_payer_notes` | `additional_payer_notes` | Free text. |

**Indexes**: `idx_hospital_code_charge_id`, `idx_payer_name_raw`
(prefix B-tree — supports `LIKE 'aetna%'` directly).

### Why prices split this way

A field belongs on `hospital_code_charges` if it has the same value for
every payer at that (hospital, service). It belongs on
`hospital_payer_rates` if it varies per payer.

`gross`, `cash`, `min`, `max` are chargemaster / cross-payer summaries
(same regardless of payer). `negotiated_dollar`, `methodology`,
allowed-amount stats are per-contract.

---

## Chat tables

Powers the agent UI. No FK to pricing.

### chats

`id VARCHAR(32)` PK (client-generated session ID). `title` for sidebar.
`attributes JSON` free-form bag (currently holds `public_ip`,
`user_geo`). `idx_date_updated` for sidebar ordering.

### chat_requests

One row per Gemini `generateContent` round-trip. Sorted by
`date_created` per chat yields the exact agent-loop trail — cost
auditing, replay, debugging.

| column | notes |
|---|---|
| `chat_id` | FK, cascade on delete. |
| `user_message` | **Denormalized**: the user-typed message that initiated this turn block. Every row in a single agent loop carries the same value. The wire assembler groups by `user_message` so there's no separate `messages` table. Placeholder rows (only `user_message` set, response NULL) render the user bubble before the bg task lands an LLM response. |
| `request`, `response` | `JSON`. Full Gemini wire payload (system instruction prepended to the first user turn). |
| `tool_calls` | `JSON`. Extracted at insert time for fast wire assembly. |
| `tool_results` | `MEDIUMTEXT` (JSON-encoded). Tool outputs can blow past TEXT's 64 KB limit. |
| `reply_text` | Denormalized assistant text. On rows with `tool_calls`: holds the iteration's thought summary. On the terminal row: the final reply. |
| `input/output/thought/total_tokens` | Usage metadata. `thought_tokens` only populated for Gemini 2.5+. |
| `model` | The model ID that produced this round-trip. |
| `error` | `JSON` `{status, body, model}` if the call failed. |

`idx_chat_id_date_created` on `(chat_id, date_created)` — every chat
page fetch loads the full turn trail in order.

---

## Common query patterns

### Latest charge for hospital × code

```sql
SELECT hcc.*
FROM hospital_code_charges hcc
JOIN hospital_code_charge_codes hccc ON hccc.hospital_code_charge_id = hcc.id
JOIN mrfs_csv m ON m.id = hcc.mrf_id
WHERE hcc.hospital_id = ? AND hccc.code_id = ? AND hcc.setting = ?
ORDER BY m.last_updated_on DESC
LIMIT 1
```

### Cheapest hospitals for CPT X near ZIP Z

Starts at the junction (`idx_code_id`), joins to charges, geo-bounds via
`hospitals.lat/lng`:

```sql
SELECT h.id, h.location_name, hcc.discounted_cash_price
FROM hospital_code_charge_codes hccc
JOIN codes c                   ON c.id = hccc.code_id
JOIN hospital_code_charges hcc ON hcc.id = hccc.hospital_code_charge_id
JOIN hospitals h               ON h.id = hcc.hospital_id
WHERE c.code = 'CPT:73721'
  AND ST_Distance_Sphere(POINT(h.lng, h.lat), POINT(?, ?)) <= 80467  -- 50 mi in meters
ORDER BY hcc.discounted_cash_price ASC
LIMIT 25
```

### Negotiated rate for a given payer at a hospital

Multi-pattern LIKE to cover spelling variants:

```sql
SELECT hpr.*
FROM hospital_payer_rates hpr
JOIN hospital_code_charges hcc ON hcc.id = hpr.hospital_code_charge_id
WHERE hcc.hospital_id = ? AND hpr.hospital_code_charge_id = ?
  AND (hpr.payer_name_raw LIKE 'aetna%' OR hpr.payer_name_raw LIKE '%aetna ppo%')
```

### Demo bulk-query guardrails

Multi-row price endpoints **must** be gated by either `near_zip`
(≤50 mi) or a specific `hospital_id`. Prevents bulk extraction.

---

## Conventions

- **NULLability is intentional.** NULL costs ~1 bit each in the InnoDB
  bitmap and signals "MRF didn't publish this" — semantically
  different from `0`.
- **No payer canonicalization.** Don't add a `payers` table. The
  agent's multi-pattern LIKE is the canonicalization layer;
  canonicalizing into a table loses the raw audit trail.
- **No SQL ENUMs on source-derived columns.** Anything sourced from
  MRFs (`setting`, `methodology`, `typical_setting`) stays `VARCHAR`.
  Publishers don't conform to fixed vocabularies; ENUMs either reject
  the insert or silently coerce to `''`.
- **Index discipline.** PK only by default. Add `Index(...)` only when
  you can point at the exact query that uses it. Naming:
  `idx_<column>` single-column, `idx_<col1>_<col2>` with columns
  **alphabetized** for composites. Every index needs a comment naming
  the query path.
- **Append-only price history.** Don't `UPDATE` rows in
  `hospital_code_charges` / `hospital_payer_rates` on re-ingest;
  insert a new snapshot tied to a new `mrfs_csv` row.
- **utf8mb4 everywhere**, indexed VARCHARs capped at 768 (InnoDB max
  key under utf8mb4).
- **All timestamps UTC.** The connect-time `SET time_zone = '+00:00'`
  is what makes that true.

---

# HTTP API

FastAPI app in `apps/api/main.py`. Three routers under `/api/`:
`agent`, `sessions`, `meta`. Dev CORS is `allow_origins=["*"]` —
tighten before public deploy.

## `/api/agent/tools/*` — agent-callable tools

Two tiers. The schemas the Gemma model sees come from
`apps/agent-cli/agent_cli/tools.py` (function declarations); each
declaration maps to one route below.

### Tier 1 — Journey tools

One HTTP call answers one user question end-to-end. Server does the
joins; agent gets a denormalized result.

| Route | Method | Purpose |
|---|---|---|
| `/find_prices` | POST | "How much is X (near me / cheapest / with insurance Y) at hospital Z?". Embeds the top 3 payer rates per row so the agent doesn't need a follow-up call. Requires exactly one of `code` or `procedure_keywords`. Optional: `hospital_id` / `hospital_keywords`, `location` (state/city/zip + geo radius), `payer_keywords`, `sort_by`, `limit`. |
| `/price_distribution` | POST | "Is $N fair for X?" — percentiles + n + min/max for a (code, location[, payer]) slice. |
| `/compare_hospitals` | POST | Side-by-side prices for a code across N specific hospitals. |
| `/find_procedure` | POST | Keyword → candidate codes (fuzzy name → CPT/HCPCS/DRG lookup). |
| `/find_hospital` | POST | Resolve a hospital reference (name / city / state) to ids. Input resolver for the other tools. |
| `/find_hospitals_nearby` | POST | "Hospitals near me" with no procedure yet — takes `(lat, lng, radius_miles)`. |
| `/corpus_stats` | GET | Counts: hospitals, MRFs, codes, charges, payer rates. The "how much data do you have" answer. |

### Tier 2 — Primitive escape hatches

Direct row fetches when the journey tools don't fit.

| Route | Method | Purpose |
|---|---|---|
| `/get_code` | GET | `?id=` or `?code=`. |
| `/get_hospital` | GET | `?id=`. |
| `/get_charge` | GET | `?id=`. Returns the full charge row — the canonical way to verify a number the user is asking about. |
| `/get_mrf` | GET | `?id=`. Returns the MRF + linked hospitals — used by the UI's `ⓘ` source chip. |
| `/list_hospital_mrfs` | GET | `?hospital_id=`. |
| `/list_codes_for_charge` | GET | `?charge_id=`. |
| `/list_charges_for_code` | GET | `?code_id=`. |
| `/list_payer_rates_for_charge` | GET | `?charge_id=&payer_name=`. |

## `/api/sessions/*` — chat persistence + server-owned agent runs

Backed by the two chat tables. Wire shape: `{turns: [...]}` assembled
by walking `chat_requests` per chat ordered by `date_created` and
grouping consecutive rows that share the same `user_message`.

| Route | Method | Purpose |
|---|---|---|
| `/api/sessions` | GET | All sessions, newest first. Metadata only (no turns). |
| `/api/sessions/{id}` | GET | One session with `turns[]` assembled. |
| `/api/sessions/{id}` | PATCH | Rename (`title` field). Preserves `date_updated` so renames don't bump sidebar order. |
| `/api/sessions/{id}` | DELETE | Hard-delete chat + cascade `chat_requests`. |
| `/api/sessions/{id}/messages` | POST | Append a user message + kick off a bg agent run. Body: `{message, display_text?, client_timezone?}`. Writes a placeholder `chat_requests` row immediately so the user bubble paints, then streams LLM round-trips into more rows as the bg task progresses. The route returns the authoritative state; the frontend polls `/api/sessions/{id}` every 1.5 s while status is `running`. |
| `/api/sessions/{id}/interrupt` | POST | Cancel the in-flight asyncio task. Awaits the task before returning so a follow-up message can't race a still-cancelling run. |

Session IDs are 12-char lowercase hex (client-generated), validated
against `^[a-z0-9]{6,32}$`. The "running" status is in-memory only —
process restart wipes it; any chat that was running becomes "idle"
with whatever rows the bg task managed to write before the restart.

## `/api/meta/*` — health + caller info

| Route | Method | Purpose |
|---|---|---|
| `/api/meta/health` | GET | Liveness probe. Returns `{status, db, as_of}`; runs `SELECT 1` to confirm DB reachability. |
| `/api/meta/whoami` | GET | Returns the same `{ip, city, region, region_name, zip}` the agent sees about the caller. Powers the privacy banner at the top of the chat — the values come from the same IP→geo chain the chat handler uses, so the banner is honest about what flows into `request_context`. |

## Request context flowing into the agent

When `POST /api/sessions/{id}/messages` runs, it builds a
`request_context` dict and stashes it in a contextvar that the agent's
tools can read. Fields: `client_ip`, `public_ip`, `client_timezone`,
`user_agent`, `session_id`, `user_geo` (cached on `chats.attributes`
after the first message in a chat — keeps us inside the
ip-api.com free-tier rate budget).

The agent's system prompt appends a per-turn `USER CONTEXT` block
derived from `user_geo` — see
`apps/agent-cli/agent_cli/agent.py:_build_user_context_block`. This
keeps the cacheable head of the system prompt byte-identical across
turns so Gemini's implicit context caching kicks in.
