"""`/api/agent/tools/*` — flat namespace of agent-callable tools.

Two tiers — journey tools (Tier 1) answer a whole user question in one
call by doing the joins server-side; primitive tools (Tier 2) are
direct row fetches the agent uses when the journey tools don't fit.
The full route catalog (with request shapes) lives in
[docs/database_and_api.md](../../../../docs/database_and_api.md#apiagenttools--agent-callable-tools).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, distinct, func, or_, select
from sqlalchemy.orm import Session

from db.models import (
    Code,
    Hospital,
    HospitalCodeCharge,
    HospitalCodeChargeCode,
    HospitalMrf,
    HospitalPayerRate,
    MrfCsv,
)
from deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/tools", tags=["agent-tools"])


# ============================================================================
# Helpers
# ============================================================================

def _pat(q: str) -> str:
    return f"%{q.strip()}%"


def _clean_keywords(kws: Optional[list[str]]) -> list[str]:
    return [k for k in (kw.strip() for kw in (kws or [])) if k]


_METERS_PER_MILE = 1609.344


def _apply_location(stmt, loc: Optional["LocationFilter"]):
    """Apply LocationFilter constraints to a SELECT that includes `Hospital`.

    Centralized so `find_prices`, `price_distribution`, and `find_hospital`
    stay in sync — adding a new filter (e.g. county) only edits this one
    function. Geo radius uses `ST_Distance_Sphere(POINT(lng, lat), …) <=
    meters`; rows where lat or lng is NULL are excluded by the comparison
    semantics, which is the desired behavior for "near me" queries."""
    if loc is None:
        return stmt
    if loc.state:
        stmt = stmt.where(Hospital.state == loc.state.upper())
    if loc.city:
        stmt = stmt.where(Hospital.city.like(_pat(loc.city)))
    if loc.zip:
        stmt = stmt.where(Hospital.zip == loc.zip)
    if (
        loc.near_lat is not None
        and loc.near_lng is not None
        and loc.radius_miles is not None
    ):
        meters = float(loc.radius_miles) * _METERS_PER_MILE
        # ST_Distance_Sphere(POINT(x, y), POINT(x, y)) — MySQL convention is
        # POINT(longitude, latitude). Wrap the literal POINT in a bind so
        # SQLAlchemy parameterizes the floats.
        stmt = stmt.where(
            func.ST_Distance_Sphere(
                func.POINT(Hospital.lng, Hospital.lat),
                func.POINT(loc.near_lng, loc.near_lat),
            ) <= meters
        )
    return stmt


def _and_keyword_like(columns: list, keywords: list[str]):
    """Build a `WHERE` clause: for each keyword, the row qualifies if ANY of
    `columns` LIKE %keyword%; across keywords, ALL must qualify."""
    return and_(*[
        or_(*[c.like(_pat(k)) for c in columns])
        for k in keywords
    ])


def _resolve_codes(
    db: Session,
    procedure_keywords: Optional[list[str]],
    code: Optional[str],
    limit: int = 5,
) -> list[Code]:
    """Resolve a procedure spec to candidate Code rows.

    Caller passes EITHER a `code` (specific `<TYPE>:<value>` key — used
    as-is) OR a list of `procedure_keywords` (LIKE-matched across the
    description columns). Returns 0..N rows; caller decides what to do
    with multiple matches.
    """
    if code:
        rows = db.execute(
            select(Code).where(Code.code == code).limit(1)
        ).scalars().all()
        return rows
    kws = _clean_keywords(procedure_keywords)
    if not kws:
        return []
    where = _and_keyword_like(
        [
            Code.code,
            Code.official_description,
            Code.most_common_description,
            Code.gemma_description,
            # Curated comma-separated consumer aliases — loaded from
            # data/code_keywords.md via scripts/load_code_keywords.py.
            # Catches lay terms ("knee mri") that official CPT
            # descriptions strip out ("lower-extremity joint imaging").
            Code.keywords,
        ],
        kws,
    )
    return db.execute(select(Code).where(where).limit(limit)).scalars().all()


def _resolve_payer_names(
    db: Session, payer_keywords: list[str], limit: int = 50,
) -> list[str]:
    """LIKE-match `hospital_payer_rates.payer_name_raw` against ALL
    keywords (AND across), return the distinct strings."""
    stmt = select(distinct(HospitalPayerRate.payer_name_raw))
    for k in payer_keywords:
        stmt = stmt.where(HospitalPayerRate.payer_name_raw.like(_pat(k)))
    return list(db.execute(stmt.limit(limit)).scalars())


def _embed_top_payer_rates(
    db: Session,
    charge_id: int,
    payer_names: Optional[list[str]] = None,
    limit: int = 3,
) -> list[dict]:
    """Top payer rates for one charge (cheapest first when `negotiated_dollar`
    is set). When `payer_names` is given, restrict to that exact-match set."""
    stmt = (
        select(HospitalPayerRate)
        .where(HospitalPayerRate.hospital_code_charge_id == charge_id)
    )
    if payer_names:
        stmt = stmt.where(HospitalPayerRate.payer_name_raw.in_(payer_names))
    stmt = (
        stmt.order_by(
            HospitalPayerRate.negotiated_dollar.is_(None),
            HospitalPayerRate.negotiated_dollar.asc(),
        )
        .limit(limit)
    )
    rows = db.execute(stmt).scalars().all()
    return [_payer_rate_short(r) for r in rows]


# Per-row citation = bare `mrf_id` field on the row. The agent (or UI)
# can resolve it to the full MRF (URL, date, linked hospitals) with
# `get_mrf?id=<n>` when it actually needs to show a "Source" link.
# Keeps the response payload small + avoids an extra join on the hot path.


# ============================================================================
# IO models
# ============================================================================

class FindProcedureIn(BaseModel):
    keywords: list[str] = Field(..., min_length=1, max_length=10)
    limit: int = Field(20, ge=1, le=100)


class FindHospitalIn(BaseModel):
    keywords: list[str] = Field(..., min_length=1, max_length=10)
    location: Optional["LocationFilter"] = None
    limit: int = Field(20, ge=1, le=100)


class NearbyHospitalsIn(BaseModel):
    """Body for `find_hospitals_nearby` — pure geo query, no procedure.

    Useful as a first turn ("hospitals near me") before drilling into a
    specific procedure. Caller supplies the point + radius; the server
    returns hospitals sorted by ascending distance with `distance_miles`
    on each row."""
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    radius_miles: float = Field(25.0, ge=0.1, le=500)
    limit: int = Field(20, ge=1, le=100)


class LocationFilter(BaseModel):
    """Optional location scope. All filters AND'd.

    Geo radius: pass `near_lat`, `near_lng`, and `radius_miles` together to
    restrict to hospitals within great-circle distance of a point. Uses
    MySQL `ST_Distance_Sphere`. `hospitals.lat`/`lng` are populated for the
    full CA corpus; rows with NULL lat/lng are silently excluded from
    geo-filtered queries."""
    state: Optional[str] = None
    city: Optional[str] = None
    zip: Optional[str] = None
    near_lat: Optional[float] = Field(None, ge=-90, le=90)
    near_lng: Optional[float] = Field(None, ge=-180, le=180)
    radius_miles: Optional[float] = Field(None, ge=0.1, le=500)


class FindPricesIn(BaseModel):
    """Body for `find_prices`. Exactly one of `code` or `procedure_keywords`
    must be set."""
    code: Optional[str] = None
    procedure_keywords: Optional[list[str]] = None
    hospital_id: Optional[int] = None
    hospital_keywords: Optional[list[str]] = None
    location: Optional[LocationFilter] = None
    payer_keywords: Optional[list[str]] = None
    sort_by: str = Field(
        "discounted_cash_price",
        description=(
            "One of: discounted_cash_price, gross_charge, "
            "min_negotiated_charge, max_negotiated_charge"
        ),
    )
    limit: int = Field(10, ge=1, le=50)


class PriceDistributionIn(BaseModel):
    """Body for `price_distribution`. Exactly one of `code` or
    `procedure_keywords` must be set. Scope filters are optional."""
    code: Optional[str] = None
    procedure_keywords: Optional[list[str]] = None
    location: Optional[LocationFilter] = None
    payer_keywords: Optional[list[str]] = None


class CompareHospitalsIn(BaseModel):
    code: str
    hospital_ids: list[int] = Field(..., min_length=1, max_length=10)


# ============================================================================
# Row → wire helpers
# ============================================================================

def _code_row(r: Code) -> dict:
    return {
        "id": r.id,
        "code": r.code,
        "official_description": r.official_description,
        "most_common_description": r.most_common_description,
        "gemma_description": r.gemma_description,
        "category": r.category,
        "typical_setting": r.typical_setting,
    }


def _code_short(r: Code) -> dict:
    """Inline code reference inside a charge row — just the key and best
    description."""
    return {
        "code": r.code,
        "description": (
            r.most_common_description
            or r.official_description
            or r.gemma_description
        ),
    }


def _hospital_row(r: Hospital) -> dict:
    return {
        "id": r.id,
        "ein": r.ein,
        "hospital_name": r.hospital_name,
        "location_name": r.location_name,
        "hospital_address": r.hospital_address,
        "city": r.city,
        "state": r.state,
        "zip": r.zip,
        "lat": r.lat,
        "lng": r.lng,
        "license_number": r.license_number,
        "license_state": r.license_state,
    }


def _hospital_short(r: Hospital) -> dict:
    """Inline hospital reference inside a price row — just the bits the UI
    renders on a card."""
    return {
        "id": r.id,
        "name": r.location_name or r.hospital_name,
        "city": r.city,
        "state": r.state,
        "zip": r.zip,
    }


def _mrf_row(r: MrfCsv) -> dict:
    return {
        "id": r.id,
        "mrf_url": r.mrf_url,
        "last_updated_on": r.last_updated_on,
        "version": r.version,
        "attestation": r.attestation,
        "attester_name": r.attester_name,
        "contact_name": r.contact_name,
        "contact_email": r.contact_email,
        "content_sha256": r.content_sha256,
    }


def _charge_row(r: HospitalCodeCharge) -> dict:
    return {
        "id": r.id,
        "hospital_id": r.hospital_id,
        "mrf_id": r.mrf_id,
        "setting": r.setting,
        "description": r.description,
        "modifiers": r.modifiers,
        "drug_unit_of_measurement": r.drug_unit_of_measurement,
        "drug_type_of_measurement": r.drug_type_of_measurement,
        "additional_generic_notes": r.additional_generic_notes,
        "gross_charge": _dec(r.gross_charge),
        "discounted_cash_price": _dec(r.discounted_cash_price),
        "min_negotiated_charge": _dec(r.min_negotiated_charge),
        "max_negotiated_charge": _dec(r.max_negotiated_charge),
    }


def _payer_rate_row(r: HospitalPayerRate) -> dict:
    return {
        "id": r.id,
        "hospital_code_charge_id": r.hospital_code_charge_id,
        "payer_name_raw": r.payer_name_raw,
        "plan_name": r.plan_name,
        "negotiated_dollar": _dec(r.negotiated_dollar),
        "negotiated_percentage": _dec(r.negotiated_percentage),
        "negotiated_algorithm": r.negotiated_algorithm,
        "methodology": r.methodology,
        "estimated_allowed_amount": _dec(r.estimated_allowed_amount),
        "median_allowed_amount": _dec(r.median_allowed_amount),
        "p10_allowed_amount": _dec(r.p10_allowed_amount),
        "p90_allowed_amount": _dec(r.p90_allowed_amount),
        "allowed_amounts_count": r.allowed_amounts_count,
        "additional_payer_notes": r.additional_payer_notes,
    }


def _payer_rate_short(r: HospitalPayerRate) -> dict:
    """Inline payer rate inside a price row — just the per-payer dollar
    figure the UI needs on a card."""
    return {
        "payer_name_raw": r.payer_name_raw,
        "plan_name": r.plan_name,
        "negotiated_dollar": _dec(r.negotiated_dollar),
        "negotiated_percentage": _dec(r.negotiated_percentage),
        "methodology": r.methodology,
    }


def _dec(v) -> Optional[float]:
    return float(v) if v is not None else None


# ============================================================================
# Tier 1 — Journey tools
# ============================================================================

_SORT_BY_COLS = {
    "discounted_cash_price": HospitalCodeCharge.discounted_cash_price,
    "gross_charge": HospitalCodeCharge.gross_charge,
    "min_negotiated_charge": HospitalCodeCharge.min_negotiated_charge,
    "max_negotiated_charge": HospitalCodeCharge.max_negotiated_charge,
}


@router.post("/find_prices")
def find_prices(body: FindPricesIn, db: Session = Depends(get_db)) -> dict:
    """**Journey Q1/Q2/Q3/Q5** — "How much is X (near me / cheapest /
    with insurance Y) at hospital Z?". Resolves the procedure, optionally
    filters by hospital and/or location and/or payer, returns ranked
    price rows.

    Embeds the top 3 payer rates per row so the agent doesn't need a
    second call to know what insurers see what price.

    Required: exactly one of `code` or `procedure_keywords`.
    """
    # 1. Resolve procedure → codes
    codes = _resolve_codes(db, body.procedure_keywords, body.code, limit=5)
    if not codes:
        return {
            "matched_codes": [],
            "data": [],
            "note": "No codes matched the procedure spec.",
        }
    code_ids = [c.id for c in codes]

    # 2. Build charge query: join junction → codes filter
    stmt = (
        select(HospitalCodeCharge, Hospital)
        .join(
            HospitalCodeChargeCode,
            HospitalCodeChargeCode.hospital_code_charge_id == HospitalCodeCharge.id,
        )
        .join(Hospital, Hospital.id == HospitalCodeCharge.hospital_id)
        .where(HospitalCodeChargeCode.code_id.in_(code_ids))
    )

    # 3. Hospital filter
    if body.hospital_id is not None:
        stmt = stmt.where(HospitalCodeCharge.hospital_id == body.hospital_id)
    elif body.hospital_keywords:
        kws = _clean_keywords(body.hospital_keywords)
        if kws:
            stmt = stmt.where(
                _and_keyword_like([Hospital.hospital_name, Hospital.location_name], kws)
            )

    # 4. Location filter (state/city/zip + optional geo radius)
    stmt = _apply_location(stmt, body.location)

    # 5. Payer filter via EXISTS on rates
    payer_names: list[str] = []
    if body.payer_keywords:
        pk = _clean_keywords(body.payer_keywords)
        if pk:
            payer_names = _resolve_payer_names(db, pk, limit=50)
            if not payer_names:
                return {
                    "matched_codes": [_code_short(c) for c in codes],
                    "data": [],
                    "note": (
                        f"No payers matched keywords {pk}; relax payer filter "
                        "or call find_procedure to confirm the procedure first."
                    ),
                }
            stmt = stmt.where(
                select(HospitalPayerRate.id)
                .where(
                    HospitalPayerRate.hospital_code_charge_id == HospitalCodeCharge.id,
                    HospitalPayerRate.payer_name_raw.in_(payer_names),
                )
                .exists()
            )

    # 6. Sort
    sort_col = _SORT_BY_COLS.get(body.sort_by, HospitalCodeCharge.discounted_cash_price)
    stmt = stmt.order_by(sort_col.is_(None), sort_col.asc()).limit(body.limit)

    rows = db.execute(stmt).all()

    # 7. Build response with embedded payer rates. Per-row citation is
    # `mrf_id` — the agent (or UI) calls `get_mrf?id=<n>` to resolve.
    out = []
    for charge, hospital in rows:
        out.append({
            "charge_id": charge.id,
            "mrf_id": charge.mrf_id,
            "hospital": _hospital_short(hospital),
            "prices": {
                "gross_charge": _dec(charge.gross_charge),
                "discounted_cash_price": _dec(charge.discounted_cash_price),
                "min_negotiated_charge": _dec(charge.min_negotiated_charge),
                "max_negotiated_charge": _dec(charge.max_negotiated_charge),
            },
            "setting": charge.setting,
            "description": charge.description,
            "top_payer_rates": _embed_top_payer_rates(
                db, charge.id, payer_names=payer_names or None, limit=3,
            ),
        })

    return {
        "matched_codes": [_code_short(c) for c in codes],
        "matched_payers": payer_names if body.payer_keywords else None,
        "sort_by": body.sort_by,
        "data": out,
    }


@router.post("/price_distribution")
def price_distribution(
    body: PriceDistributionIn, db: Session = Depends(get_db),
) -> dict:
    """**Journey Q4** — "Is $N fair for X in my area?". Returns min / p10 /
    p25 / median / p75 / p90 / max + count for cash and negotiated-dollar
    prices over the scoped charge set."""
    codes = _resolve_codes(db, body.procedure_keywords, body.code, limit=5)
    if not codes:
        return {"matched_codes": [], "stats": {}, "freshness": {}}
    code_ids = [c.id for c in codes]

    # Pull the price columns we'll compute stats on. One query, Python
    # quantile math — MySQL's percentile syntax is awkward and the scoped
    # row set is bounded.
    join_cols = [HospitalCodeCharge.discounted_cash_price, HospitalCodeCharge.gross_charge]
    stmt = (
        select(*join_cols)
        .join(
            HospitalCodeChargeCode,
            HospitalCodeChargeCode.hospital_code_charge_id == HospitalCodeCharge.id,
        )
        .join(Hospital, Hospital.id == HospitalCodeCharge.hospital_id)
        .where(HospitalCodeChargeCode.code_id.in_(code_ids))
    )
    stmt = _apply_location(stmt, body.location)

    rows = db.execute(stmt.limit(50_000)).all()
    cash = sorted(float(r[0]) for r in rows if r[0] is not None)
    gross = sorted(float(r[1]) for r in rows if r[1] is not None)

    # Negotiated dollar stats need the rates table, optionally payer-filtered.
    neg_stmt = (
        select(HospitalPayerRate.negotiated_dollar)
        .join(
            HospitalCodeCharge,
            HospitalCodeCharge.id == HospitalPayerRate.hospital_code_charge_id,
        )
        .join(
            HospitalCodeChargeCode,
            HospitalCodeChargeCode.hospital_code_charge_id == HospitalCodeCharge.id,
        )
        .join(Hospital, Hospital.id == HospitalCodeCharge.hospital_id)
        .where(
            HospitalCodeChargeCode.code_id.in_(code_ids),
            HospitalPayerRate.negotiated_dollar.is_not(None),
        )
    )
    neg_stmt = _apply_location(neg_stmt, body.location)
    payer_names: list[str] = []
    if body.payer_keywords:
        pk = _clean_keywords(body.payer_keywords)
        if pk:
            payer_names = _resolve_payer_names(db, pk, limit=50)
            if payer_names:
                neg_stmt = neg_stmt.where(
                    HospitalPayerRate.payer_name_raw.in_(payer_names)
                )
    neg = sorted(float(v) for v in db.execute(neg_stmt.limit(200_000)).scalars())

    # Distinct MRF ids that backed the scoped charge set. Caller resolves
    # each via `get_mrf?id=N` for date / URL / linked hospitals when it
    # wants to cite or compute earliest/latest itself.
    mrf_ids_stmt = (
        select(distinct(MrfCsv.id))
        .join(HospitalCodeCharge, HospitalCodeCharge.mrf_id == MrfCsv.id)
        .join(
            HospitalCodeChargeCode,
            HospitalCodeChargeCode.hospital_code_charge_id == HospitalCodeCharge.id,
        )
        .where(HospitalCodeChargeCode.code_id.in_(code_ids))
    )
    source_mrf_ids = sorted(int(i) for i in db.execute(mrf_ids_stmt).scalars())

    return {
        "matched_codes": [_code_short(c) for c in codes],
        "matched_payers": payer_names if body.payer_keywords else None,
        "stats": {
            "discounted_cash_price": _percentiles(cash),
            "gross_charge": _percentiles(gross),
            "negotiated_dollar": _percentiles(neg),
        },
        "source_mrf_ids": source_mrf_ids,
    }


def _percentiles(sorted_vals: list[float]) -> dict:
    n = len(sorted_vals)
    if n == 0:
        return {"count": 0}

    def q(p: float) -> float:
        # Linear interpolation across the sorted array. p ∈ [0, 1].
        if n == 1:
            return sorted_vals[0]
        idx = p * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

    return {
        "count": n,
        "min": sorted_vals[0],
        "p10": q(0.10),
        "p25": q(0.25),
        "median": q(0.50),
        "p75": q(0.75),
        "p90": q(0.90),
        "max": sorted_vals[-1],
        "avg": sum(sorted_vals) / n,
    }


@router.post("/compare_hospitals")
def compare_hospitals(
    body: CompareHospitalsIn, db: Session = Depends(get_db),
) -> dict:
    """**Journey Q8** — "Compare X at hospitals A, B, C side-by-side".
    For one code key + a list of hospital IDs, returns one row per
    hospital with the latest matching charge + top 3 payer rates."""
    code = db.execute(
        select(Code).where(Code.code == body.code).limit(1)
    ).scalar_one_or_none()
    if code is None:
        raise HTTPException(404, detail={
            "error": f"code {body.code!r} not found", "code": "not_found",
        })

    out = []
    for hid in body.hospital_ids:
        hospital = db.get(Hospital, hid)
        if hospital is None:
            out.append({"hospital_id": hid, "missing": True})
            continue
        # Latest charge for this hospital × code (freshest MRF wins).
        charge = db.execute(
            select(HospitalCodeCharge)
            .join(
                HospitalCodeChargeCode,
                HospitalCodeChargeCode.hospital_code_charge_id == HospitalCodeCharge.id,
            )
            .join(MrfCsv, MrfCsv.id == HospitalCodeCharge.mrf_id)
            .where(
                HospitalCodeCharge.hospital_id == hid,
                HospitalCodeChargeCode.code_id == code.id,
            )
            .order_by(MrfCsv.last_updated_on.is_(None), MrfCsv.last_updated_on.desc())
            .limit(1)
        ).scalar_one_or_none()
        if charge is None:
            out.append({"hospital": _hospital_short(hospital), "no_data": True})
            continue
        out.append({
            "hospital": _hospital_short(hospital),
            "charge_id": charge.id,
            "mrf_id": charge.mrf_id,
            "prices": {
                "gross_charge": _dec(charge.gross_charge),
                "discounted_cash_price": _dec(charge.discounted_cash_price),
                "min_negotiated_charge": _dec(charge.min_negotiated_charge),
                "max_negotiated_charge": _dec(charge.max_negotiated_charge),
            },
            "top_payer_rates": _embed_top_payer_rates(db, charge.id, limit=3),
        })

    return {
        "code": _code_short(code),
        "data": out,
    }


@router.post("/find_procedure")
def find_procedure(body: FindProcedureIn, db: Session = Depends(get_db)) -> dict:
    """Keyword search for codes. Returns candidate codes with descriptions.

    Used when the agent has a procedure name but not a code yet. For exact
    lookup of a known code key, prefer `get_code?code=CPT:99213`.
    """
    kws = _clean_keywords(body.keywords)
    if not kws:
        raise HTTPException(400, detail={
            "error": "keywords must contain at least one non-empty string",
            "code": "invalid_param",
        })
    where = _and_keyword_like(
        [
            Code.code,
            Code.official_description,
            Code.most_common_description,
            Code.gemma_description,
            # Curated comma-separated consumer aliases — loaded from
            # data/code_keywords.md via scripts/load_code_keywords.py.
            # Catches lay terms ("knee mri") that official CPT
            # descriptions strip out ("lower-extremity joint imaging").
            Code.keywords,
        ],
        kws,
    )
    rows = db.execute(
        select(Code).where(where).limit(body.limit)
    ).scalars().all()
    return {"data": [_code_row(r) for r in rows], "limit": body.limit}


@router.post("/find_hospital")
def find_hospital(body: FindHospitalIn, db: Session = Depends(get_db)) -> dict:
    """Keyword search for hospitals (name or location). Accepts an
    optional `location` filter — state/city/zip narrow the search, and
    `near_lat`/`near_lng`/`radius_miles` restrict to a geographic radius."""
    kws = _clean_keywords(body.keywords)
    if not kws:
        raise HTTPException(400, detail={
            "error": "keywords must contain at least one non-empty string",
            "code": "invalid_param",
        })
    where = _and_keyword_like([Hospital.hospital_name, Hospital.location_name], kws)
    stmt = select(Hospital).where(where)
    stmt = _apply_location(stmt, body.location)
    rows = db.execute(stmt.limit(body.limit)).scalars().all()
    return {"data": [_hospital_row(r) for r in rows], "limit": body.limit}


@router.post("/find_hospitals_nearby")
def find_hospitals_nearby(
    body: NearbyHospitalsIn, db: Session = Depends(get_db),
) -> dict:
    """Hospitals within `radius_miles` of (lat, lng), sorted nearest first.

    Use this as a first turn when the user asks "what hospitals are near
    me" without naming a procedure. The agent typically gets `(lat, lng)`
    from the chat's IP-derived location context; users can override with
    a zip/city resolved through `find_hospital` first."""
    meters = float(body.radius_miles) * _METERS_PER_MILE
    distance_expr = func.ST_Distance_Sphere(
        func.POINT(Hospital.lng, Hospital.lat),
        func.POINT(body.lng, body.lat),
    )
    stmt = (
        select(Hospital, distance_expr.label("distance_meters"))
        .where(
            Hospital.lat.is_not(None),
            Hospital.lng.is_not(None),
            distance_expr <= meters,
        )
        .order_by(distance_expr.asc())
        .limit(body.limit)
    )
    rows = db.execute(stmt).all()
    # Collapse rows that describe the same physical facility — multiple
    # hospitals can share an address (different ingest paths from MRFs
    # with slightly different `location_name` produce two rows for the
    # same building). Dedupe on rounded (lat, lng) so spelling variants
    # in name/address don't matter; 4 decimals ≈ 11 m of precision, which
    # collapses building-shared rows without merging across-the-street
    # facilities. Since rows are already sorted by ascending distance,
    # first-seen wins so the user gets the closest distance reading.
    seen: set[tuple] = set()
    out = []
    for hospital, distance_meters in rows:
        if hospital.lat is None or hospital.lng is None:
            continue
        key = (round(float(hospital.lat), 4), round(float(hospital.lng), 4))
        if key in seen:
            continue
        seen.add(key)
        d = _hospital_row(hospital)
        d["distance_miles"] = round(float(distance_meters) / _METERS_PER_MILE, 2)
        out.append(d)
    return {
        "data": out,
        "center": {"lat": body.lat, "lng": body.lng},
        "radius_miles": body.radius_miles,
    }


@router.get("/corpus_stats")
def corpus_stats(db: Session = Depends(get_db)) -> dict:
    """**Journey Q10** — "How much data do you have / how old is it?"."""
    # Exact counts on the small tables; estimates on the big ones via
    # information_schema (microseconds vs minutes for a real COUNT(*)).
    hospitals = db.execute(select(func.count()).select_from(Hospital)).scalar_one()
    codes = db.execute(select(func.count()).select_from(Code)).scalar_one()
    mrfs = db.execute(select(func.count()).select_from(MrfCsv)).scalar_one()

    # Estimates for the fact tables.
    from sqlalchemy import text
    charge_est = db.execute(text(
        "SELECT TABLE_ROWS FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'hospital_code_charges'"
    )).scalar() or 0
    rate_est = db.execute(text(
        "SELECT TABLE_ROWS FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'hospital_payer_rates'"
    )).scalar() or 0

    # Caller resolves dates via get_mrf if needed; we keep this lean.
    mrf_ids = sorted(int(i) for i in db.execute(select(MrfCsv.id)).scalars())

    return {
        "data": {
            "total_hospitals": int(hospitals),
            "total_codes": int(codes),
            "total_mrfs": int(mrfs),
            "total_charges_est": int(charge_est),
            "total_payer_rates_est": int(rate_est),
            "source_mrf_ids": mrf_ids,
        }
    }


# ============================================================================
# Tier 2 — Primitive escape hatches
# ============================================================================

@router.get("/get_code")
def get_code(
    id: Optional[int] = Query(None),
    code: Optional[str] = Query(None, description="`<TYPE>:<value>` exact key"),
    db: Session = Depends(get_db),
) -> dict:
    """One code by integer id OR `<TYPE>:<value>` string. 404 if missing."""
    if id is None and code is None:
        raise HTTPException(400, detail={
            "error": "either `id` or `code` is required", "code": "invalid_param",
        })
    if id is not None:
        row = db.get(Code, id)
    else:
        row = db.execute(
            select(Code).where(Code.code == code).limit(1)
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, detail={
            "error": "code not found", "code": "not_found",
        })
    return {"data": _code_row(row)}


@router.get("/get_hospital")
def get_hospital(
    id: int = Query(..., description="Integer PK"),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(Hospital, id)
    if row is None:
        raise HTTPException(404, detail={
            "error": f"hospital {id} not found", "code": "not_found",
        })
    return {"data": _hospital_row(row)}


@router.get("/get_charge")
def get_charge(
    id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(HospitalCodeCharge, id)
    if row is None:
        raise HTTPException(404, detail={
            "error": f"charge {id} not found", "code": "not_found",
        })
    return {"data": _charge_row(row)}


@router.get("/get_mrf")
def get_mrf(
    id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(MrfCsv, id)
    if row is None:
        raise HTTPException(404, detail={
            "error": f"mrf {id} not found", "code": "not_found",
        })
    # Source chip's tooltip wants the hospital(s) this file covers — one
    # MRF can map to many hospitals via the hospital_mrfs junction (CMS
    # multi-location files use this; Cottage/Kaiser share one MRF across
    # many sites). Surface the names so the UI can lead with "Source:
    # <hospital>" instead of the publisher filename.
    hospitals = db.execute(
        select(Hospital.id, Hospital.location_name, Hospital.hospital_name)
        .join(HospitalMrf, HospitalMrf.hospital_id == Hospital.id)
        .where(HospitalMrf.mrf_id == id)
        .order_by(Hospital.id)
    ).all()
    payload = _mrf_row(row)
    payload["hospitals"] = [
        {"id": h.id, "name": h.location_name or h.hospital_name}
        for h in hospitals
    ]
    return {"data": payload}


@router.get("/list_hospital_mrfs")
def list_hospital_mrfs(
    hospital_id: int = Query(...),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        select(MrfCsv)
        .join(HospitalMrf, HospitalMrf.mrf_id == MrfCsv.id)
        .where(HospitalMrf.hospital_id == hospital_id)
        .order_by(MrfCsv.last_updated_on.is_(None), MrfCsv.last_updated_on.desc())
        .limit(limit)
    ).scalars().all()
    return {"data": [_mrf_row(r) for r in rows], "limit": limit}


@router.get("/list_codes_for_charge")
def list_codes_for_charge(
    charge_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        select(Code)
        .join(HospitalCodeChargeCode, HospitalCodeChargeCode.code_id == Code.id)
        .where(HospitalCodeChargeCode.hospital_code_charge_id == charge_id)
    ).scalars().all()
    return {"data": [_code_row(r) for r in rows]}


@router.get("/list_charges_for_code")
def list_charges_for_code(
    code_id: int = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        select(HospitalCodeCharge)
        .join(
            HospitalCodeChargeCode,
            HospitalCodeChargeCode.hospital_code_charge_id == HospitalCodeCharge.id,
        )
        .where(HospitalCodeChargeCode.code_id == code_id)
        .order_by(HospitalCodeCharge.id)
        .limit(limit).offset(offset)
    ).scalars().all()
    return {"data": [_charge_row(r) for r in rows], "limit": limit, "offset": offset}


@router.get("/list_payer_rates_for_charge")
def list_payer_rates_for_charge(
    charge_id: int = Query(...),
    payer_name: Optional[str] = Query(
        None, description="Exact `payer_name_raw` filter.",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    stmt = (
        select(HospitalPayerRate)
        .where(HospitalPayerRate.hospital_code_charge_id == charge_id)
    )
    if payer_name:
        stmt = stmt.where(HospitalPayerRate.payer_name_raw == payer_name)
    rows = db.execute(
        stmt.order_by(HospitalPayerRate.id).limit(limit).offset(offset)
    ).scalars().all()
    return {
        "data": [_payer_rate_row(r) for r in rows],
        "limit": limit,
        "offset": offset,
    }


