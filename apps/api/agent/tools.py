"""Tool registry — journey-driven tools the Gemini loop can call.

Two tiers, both backed by `/api/agent/tools/*` on the FastAPI side:

  - **Tier 1 — Journey tools** answer one user question end-to-end in a
    single round-trip (`find_prices`, `price_distribution`,
    `compare_hospitals`, `find_procedure`, `find_hospital`,
    `corpus_stats`).
  - **Tier 2 — Escape-hatch primitives** are single-row / single-table
    fetches for the cases that don't fit a journey tool (`get_*`,
    `list_*`).

The implementations live in `resolvers.py`; this module wraps each in a
`Tool(...)` declaration with the JSON-Schema the model needs.

Adding a new tool:
  1. Add the async wrapper in `resolvers.py`.
  2. Append a `Tool(...)` entry to `TOOLS` below with a JSON-Schema
     `parameters` block describing what the model should pass.

The agent loop wraps each tool result as `{result: <payload>}`. Citations
come from inside the payload — every priced row carries `mrf_id`,
aggregates carry `source_mrf_ids`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx


# Base URL of the apps/api FastAPI server. Override for remote deployments.
API_BASE_URL = os.getenv("HEALTH_API_URL", "http://127.0.0.1:8000").rstrip("/")

# Shared httpx client — connection pooling for back-to-back tool fires.
_http: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0)
    return _http


@dataclass
class Tool:
    """One callable surface for the model.

    `parameters` is a JSON-Schema object handed to Gemini verbatim — keep
    it minimal (description on every property, mark `required`). `fn`
    should be async.
    """
    name: str
    description: str
    parameters: dict
    fn: Callable[..., Any]


# --- HTTP helpers -------------------------------------------------------------

async def _get(path: str, params: Optional[dict] = None) -> Any:
    """GET against the API. Returns parsed JSON wrapped with upstream source
    on success, or `{error, code, http_status}` on non-2xx."""
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    r = await _client().get(path, params=clean)
    return _decode(r, path)


async def _post(path: str, json_body: Optional[dict] = None) -> Any:
    r = await _client().post(path, json=json_body or {})
    return _decode(r, path)


def _decode(r: httpx.Response, path: str) -> Any:
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:500]}
    if 200 <= r.status_code < 300:
        return body
    err = body if isinstance(body, dict) else {"raw": str(body)}
    err.setdefault("error", f"HTTP {r.status_code} from {path}")
    err["code"] = err.get("code") or "upstream_http"
    err["http_status"] = r.status_code
    return err


# --- Registry -----------------------------------------------------------------
#
# Import the journey + escape-hatch resolvers and register each one.
# The resolvers are thin HTTP wrappers around `/api/agent/tools/*`.

from . import resolvers  # noqa: E402  (kept near registry for locality)


TOOLS: dict[str, Tool] = {t.name: t for t in [
    # --------------------------------------------------------------
    # Tier 1 — Journey tools
    # --------------------------------------------------------------
    Tool(
        name="find_prices",
        description=(
            "Workhorse pricing lookup. Answers 'how much does X cost' "
            "(optionally near a location, at a specific hospital, or for "
            "a specific payer). Returns ranked charges with embedded "
            "top-3 payer rates and per-row mrf_id citations. Pass "
            "exactly one of `code` (exact `<TYPE>:<value>` key) OR "
            "`procedure_keywords` (the model picks the keywords)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Exact code key like 'CPT:99213' or 'MS-DRG:470'.",
                },
                "procedure_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords ANDed across code description columns (e.g. ['MRI','knee']).",
                },
                "hospital_id": {
                    "type": "integer",
                    "description": "Pin to one hospital by id.",
                },
                "hospital_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords ANDed across hospital_name + location_name.",
                },
                "location": {
                    "type": "object",
                    "description": (
                        "Filter on hospital location. "
                        "Pass state/city/zip for exact matches, OR "
                        "near_lat+near_lng+radius_miles together for a "
                        "geographic radius (preferred for 'near me')."
                    ),
                    "properties": {
                        "state": {"type": "string", "description": "Two-letter state code, e.g. 'CA'."},
                        "city": {"type": "string"},
                        "zip": {"type": "string"},
                        "near_lat": {"type": "number", "description": "Center latitude for radius search."},
                        "near_lng": {"type": "number", "description": "Center longitude for radius search."},
                        "radius_miles": {"type": "number", "description": "Radius in miles around (near_lat, near_lng). 0.1–500."},
                    },
                },
                "payer_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Restrict charges to those that have negotiated rates with payers matching ALL keywords (e.g. ['anthem']).",
                },
                "sort_by": {
                    "type": "string",
                    "description": "discounted_cash_price | gross_charge | min_negotiated_dollar | max_negotiated_dollar. Default discounted_cash_price.",
                },
                "limit": {"type": "integer", "description": "Max rows. Default 10."},
            },
        },
        fn=resolvers.find_prices,
    ),
    Tool(
        name="price_distribution",
        description=(
            "Returns price percentiles (min/p10/p25/median/p75/p90/max + "
            "count + avg) for cash, gross, and negotiated-dollar prices "
            "across the scoped charges. Use when the user asks 'is $N "
            "fair for X?' — the model percentile-ranks the user's number "
            "client-side. Pass exactly one of `code` or "
            "`procedure_keywords`."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "procedure_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "location": {
                    "type": "object",
                    "description": (
                        "Same shape as find_prices.location — accepts "
                        "state/city/zip OR near_lat+near_lng+radius_miles."
                    ),
                    "properties": {
                        "state": {"type": "string"},
                        "city": {"type": "string"},
                        "zip": {"type": "string"},
                        "near_lat": {"type": "number"},
                        "near_lng": {"type": "number"},
                        "radius_miles": {"type": "number"},
                    },
                },
                "payer_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        fn=resolvers.price_distribution,
    ),
    Tool(
        name="compare_hospitals",
        description=(
            "Side-by-side price comparison for ONE billing code across "
            "N hospitals (by id). Each row carries the freshest charge "
            "for that hospital + code, embedded top-3 payer rates, and "
            "mrf_id. Missing hospital → {hospital_id, missing: true}; "
            "no charge for the code → {hospital, no_data: true}."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Exact code key like 'CPT:99213'.",
                },
                "hospital_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Hospital ids to compare. Resolve names via find_hospital first.",
                },
            },
            "required": ["code", "hospital_ids"],
        },
        fn=resolvers.compare_hospitals,
    ),
    Tool(
        name="find_procedure",
        description=(
            "Keyword search across code descriptions. Returns candidate "
            "codes (id, code, code_type, descriptions). Use when the "
            "user names a procedure but you don't have a code yet, and "
            "you want to disambiguate before calling find_prices."
        ),
        parameters={
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "ANDed substring filters across code descriptions.",
                },
                "limit": {"type": "integer", "description": "Default 20."},
            },
            "required": ["keywords"],
        },
        fn=resolvers.find_procedure,
    ),
    Tool(
        name="find_hospital",
        description=(
            "Keyword search across hospital_name + location_name. "
            "Returns candidate hospitals (id, hospital_name, "
            "location_name, city, state). Resolve names → ids before "
            "calling compare_hospitals. Optional `location` filter "
            "narrows by state/city/zip or a geo radius."
        ),
        parameters={
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "location": {
                    "type": "object",
                    "properties": {
                        "state": {"type": "string"},
                        "city": {"type": "string"},
                        "zip": {"type": "string"},
                        "near_lat": {"type": "number"},
                        "near_lng": {"type": "number"},
                        "radius_miles": {"type": "number"},
                    },
                },
                "limit": {"type": "integer", "description": "Default 20."},
            },
            "required": ["keywords"],
        },
        fn=resolvers.find_hospital,
    ),
    Tool(
        name="find_hospitals_nearby",
        description=(
            "Hospitals within a great-circle radius of (lat, lng), "
            "sorted nearest first. Each row carries `distance_miles`. "
            "No procedure needed — use this for 'hospitals near me' "
            "first turns, before drilling into find_prices for a "
            "specific service. Coordinates typically come from the "
            "IP-derived USER CONTEXT block (lat/lng); only ask the "
            "user for a ZIP if no coords are available."
        ),
        parameters={
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Center latitude."},
                "lng": {"type": "number", "description": "Center longitude."},
                "radius_miles": {
                    "type": "number",
                    "description": "Radius in miles. Default 25. Range 0.1–500.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max hospitals returned. Default 20.",
                },
            },
            "required": ["lat", "lng"],
        },
        fn=resolvers.find_hospitals_nearby,
    ),
    Tool(
        name="corpus_stats",
        description=(
            "Trust / freshness check. Returns total counts (hospitals, "
            "codes, charges, MRFs) and the source_mrf_ids list. Call "
            "when the user asks 'how much data do you have' / 'how "
            "recent is your data'."
        ),
        parameters={"type": "object", "properties": {}},
        fn=resolvers.corpus_stats,
    ),

    # --------------------------------------------------------------
    # Tier 2 — Escape-hatch primitives
    # --------------------------------------------------------------
    Tool(
        name="get_code",
        description=(
            "Fetch one code by integer id OR by exact `<TYPE>:<value>` "
            "key. Returns the full code row with all four description "
            "columns. Use to resolve mrf_id-style citations or to look "
            "up the canonical form of a code the user typed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "code": {
                    "type": "string",
                    "description": "Exact key like 'CPT:99213'.",
                },
            },
        },
        fn=resolvers.get_code,
    ),
    Tool(
        name="get_hospital",
        description="Fetch one hospital by id. Returns the full hospital row.",
        parameters={
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
        fn=resolvers.get_hospital,
    ),
    Tool(
        name="get_charge",
        description=(
            "Fetch one hospital_code_charges row by id. Returns the "
            "charge with its prices and source mrf_id."
        ),
        parameters={
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
        fn=resolvers.get_charge,
    ),
    Tool(
        name="get_mrf",
        description=(
            "Resolve an mrf_id citation. Returns the source MRF row "
            "(url, filename, last_updated_on, attestation, hospital "
            "linkage). Call this when you need to show the user where "
            "a price came from."
        ),
        parameters={
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
        fn=resolvers.get_mrf,
    ),
    Tool(
        name="list_hospital_mrfs",
        description=(
            "List the source MRFs that fed one hospital, freshest "
            "first. Use to answer 'how recent is the data for hospital "
            "Y?'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hospital_id": {"type": "integer"},
                "limit": {"type": "integer", "description": "Default 50."},
            },
            "required": ["hospital_id"],
        },
        fn=resolvers.list_hospital_mrfs,
    ),
    Tool(
        name="list_codes_for_charge",
        description=(
            "List the 1-4 codes attached to one charge via the M:N "
            "junction. Use after a find_prices row when you want to "
            "see every code that charge maps to."
        ),
        parameters={
            "type": "object",
            "properties": {"charge_id": {"type": "integer"}},
            "required": ["charge_id"],
        },
        fn=resolvers.list_codes_for_charge,
    ),
    Tool(
        name="list_charges_for_code",
        description=(
            "List every charge linked to one code (across all "
            "hospitals). Heavier than find_prices — prefer find_prices "
            "for user-facing pricing answers; reach for this only when "
            "the user explicitly wants a raw enumeration."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code_id": {"type": "integer"},
                "limit": {"type": "integer", "description": "Default 50."},
                "offset": {"type": "integer"},
            },
            "required": ["code_id"],
        },
        fn=resolvers.list_charges_for_code,
    ),
    Tool(
        name="list_payer_rates_for_charge",
        description=(
            "List per-payer negotiated rates under one charge. "
            "find_prices already embeds the top 3 — use this only when "
            "the user wants more than top 3 or filters to a specific "
            "payer_name_raw."
        ),
        parameters={
            "type": "object",
            "properties": {
                "charge_id": {"type": "integer"},
                "payer_name": {
                    "type": "string",
                    "description": "Exact payer_name_raw match (use find_prices.matched_payers values).",
                },
                "limit": {"type": "integer", "description": "Default 50."},
                "offset": {"type": "integer"},
            },
            "required": ["charge_id"],
        },
        fn=resolvers.list_payer_rates_for_charge,
    ),

]}
