"""Thin HTTP wrappers around `/api/agent/tools/*`.

Two tiers, mirroring the server-side layout:

  - **Journey tools** (`find_prices`, `price_distribution`,
    `compare_hospitals`, `find_procedure`, `find_hospital`,
    `corpus_stats`) — composite endpoints that each answer one user
    question end-to-end.

  - **Primitive escape hatches** (`get_*` / `list_*`) — single-table
    fetches when no journey tool fits.

All endpoints live behind `HEALTH_API_URL` (default
`http://127.0.0.1:8000`). Each wrapper is ~3 lines.
"""

from __future__ import annotations

from typing import Any, Optional

from .tools import _get, _post


# ---------------------------------------------------------------------------
# Tier 1 — Journey tools
# ---------------------------------------------------------------------------

async def find_prices(
    *,
    code: Optional[str] = None,
    procedure_keywords: Optional[list[str]] = None,
    hospital_id: Optional[int] = None,
    hospital_keywords: Optional[list[str]] = None,
    location: Optional[dict] = None,
    payer_keywords: Optional[list[str]] = None,
    sort_by: str = "discounted_cash_price",
    limit: int = 10,
) -> dict[str, Any]:
    """Q1/Q2/Q3/Q5 — "How much is X (near me / cheapest / with my
    insurance / at hospital Y)?". Exactly one of `code` or
    `procedure_keywords` is required. `location` is
    `{state?, city?, zip?, near_lat?, near_lng?, radius_miles?}` — pass
    the geo trio together to restrict to a great-circle radius around a
    point (typically the IP-derived user location).

    Returns `{matched_codes, matched_payers?, sort_by, data: [...]}` —
    each row carries the hospital, charge prices, embedded top-3 payer
    rates, and the source MRF date.
    """
    body: dict[str, Any] = {"sort_by": sort_by, "limit": limit}
    if code is not None:
        body["code"] = code
    if procedure_keywords:
        body["procedure_keywords"] = procedure_keywords
    if hospital_id is not None:
        body["hospital_id"] = hospital_id
    if hospital_keywords:
        body["hospital_keywords"] = hospital_keywords
    if location:
        body["location"] = location
    if payer_keywords:
        body["payer_keywords"] = payer_keywords
    return await _post("/api/agent/tools/find_prices", json_body=body)


async def price_distribution(
    *,
    code: Optional[str] = None,
    procedure_keywords: Optional[list[str]] = None,
    location: Optional[dict] = None,
    payer_keywords: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Q4 — "Is $N fair for X in my area?". Returns percentiles
    (min/p10/p25/median/p75/p90/max + count + avg) for cash, gross, and
    negotiated-dollar prices over the scoped charge set, plus the MRF
    freshness range.
    """
    body: dict[str, Any] = {}
    if code is not None:
        body["code"] = code
    if procedure_keywords:
        body["procedure_keywords"] = procedure_keywords
    if location:
        body["location"] = location
    if payer_keywords:
        body["payer_keywords"] = payer_keywords
    return await _post("/api/agent/tools/price_distribution", json_body=body)


async def compare_hospitals(
    *, code: str, hospital_ids: list[int],
) -> dict[str, Any]:
    """Q8 — Side-by-side prices for one code across N hospitals."""
    return await _post(
        "/api/agent/tools/compare_hospitals",
        json_body={"code": code, "hospital_ids": hospital_ids},
    )


async def find_procedure(
    keywords: list[str], limit: int = 20,
) -> list[dict[str, Any]]:
    """Q9 (keyword path) — Keyword search across code descriptions.
    Returns candidate codes; use `get_code` for exact lookups."""
    resp = await _post(
        "/api/agent/tools/find_procedure",
        json_body={"keywords": keywords, "limit": limit},
    )
    return (resp or {}).get("data") or []


async def find_hospital(
    keywords: list[str],
    location: Optional[dict] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Keyword search across hospital_name + location_name. Accepts an
    optional `location` filter (same shape as `find_prices.location`)."""
    body: dict[str, Any] = {"keywords": keywords, "limit": limit}
    if location:
        body["location"] = location
    resp = await _post("/api/agent/tools/find_hospital", json_body=body)
    return (resp or {}).get("data") or []


async def find_hospitals_nearby(
    *,
    lat: float,
    lng: float,
    radius_miles: float = 25.0,
    limit: int = 20,
) -> dict[str, Any]:
    """Hospitals within `radius_miles` of (lat, lng), sorted nearest
    first. Each row carries `distance_miles`. No procedure needed — use
    this for "hospitals near me" first turns, then drill into
    `find_prices` for a specific service."""
    return await _post(
        "/api/agent/tools/find_hospitals_nearby",
        json_body={
            "lat": lat, "lng": lng,
            "radius_miles": radius_miles, "limit": limit,
        },
    )


async def corpus_stats() -> dict[str, Any]:
    """Q10 — "How much data / how recent?". Returns counts + MRF date range."""
    resp = await _get("/api/agent/tools/corpus_stats")
    return (resp or {}).get("data") or {}


# ---------------------------------------------------------------------------
# Tier 2 — Primitive escape hatches
# ---------------------------------------------------------------------------

async def get_code(
    id: Optional[int] = None, code: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """One code by integer id OR `<TYPE>:<value>` key. None if missing."""
    params: dict[str, Any] = {}
    if id is not None:
        params["id"] = id
    if code is not None:
        params["code"] = code
    resp = await _get("/api/agent/tools/get_code", params=params)
    return (resp or {}).get("data")


async def get_hospital(id: int) -> Optional[dict[str, Any]]:
    resp = await _get("/api/agent/tools/get_hospital", params={"id": id})
    return (resp or {}).get("data")


async def get_charge(id: int) -> Optional[dict[str, Any]]:
    resp = await _get("/api/agent/tools/get_charge", params={"id": id})
    return (resp or {}).get("data")


async def get_mrf(id: int) -> Optional[dict[str, Any]]:
    resp = await _get("/api/agent/tools/get_mrf", params={"id": id})
    return (resp or {}).get("data")


async def list_hospital_mrfs(
    hospital_id: int, limit: int = 50,
) -> list[dict[str, Any]]:
    resp = await _get(
        "/api/agent/tools/list_hospital_mrfs",
        params={"hospital_id": hospital_id, "limit": limit},
    )
    return (resp or {}).get("data") or []


async def list_codes_for_charge(charge_id: int) -> list[dict[str, Any]]:
    resp = await _get(
        "/api/agent/tools/list_codes_for_charge",
        params={"charge_id": charge_id},
    )
    return (resp or {}).get("data") or []


async def list_charges_for_code(
    code_id: int, limit: int = 50, offset: int = 0,
) -> list[dict[str, Any]]:
    resp = await _get(
        "/api/agent/tools/list_charges_for_code",
        params={"code_id": code_id, "limit": limit, "offset": offset},
    )
    return (resp or {}).get("data") or []


async def list_payer_rates_for_charge(
    charge_id: int,
    payer_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    resp = await _get(
        "/api/agent/tools/list_payer_rates_for_charge",
        params={
            "charge_id": charge_id, "payer_name": payer_name,
            "limit": limit, "offset": offset,
        },
    )
    return (resp or {}).get("data") or []


