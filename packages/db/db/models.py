"""SQLAlchemy models for the health DB.

Schema design lives in `.claude/skills/ingest-mrf/SKILL.md`. The short story:

  Pricing data flows from MRF CSVs (download log: `mrfs_csv`) into 3 derived
  tables (`codes`, `hospital_code_charges`, `hospital_payer_rates`) hanging
  off 2 entity/provenance dims (`hospitals`, `mrfs_csv`) with a junction
  (`hospital_mrfs`) for the many-to-many between them.

  Per-charge facts (gross, cash, min, max) live on `hospital_code_charges`.
  Per-payer facts (negotiated, methodology, allowed-amount stats) live on
  `hospital_payer_rates`. Payer matching is done by LIKE-search on
  `payer_name_raw` — there is no canonical payer table; the agent can issue
  multiple keyword patterns ("aetna", "aetna ppo", etc.) to cover variants.
  The split is semantic — see SKILL.md §"Why prices split this way".

Schema changes: edit this file, then run
    uv run alembic revision --autogenerate -m "<message>"
    uv run alembic upgrade head
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    DECIMAL,
    JSON,
    Boolean,
    CHAR,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


# --- Reference: codes ----------------------------------------------------------

class Code(Base):
    """One row per (code, code_type). Reference dim joined by every item.

    `official_description` is populated for HCPCS, MS-DRG, ICD, NDC (free CMS
    sources). CPT short descriptors require an AMA license — leave NULL there
    and fall back to `most_common_description` (the modal description across
    hospitals in the corpus — derived from MRFs) and `gemma_description`
    (Gemma-generated consumer-friendly text). The `source` column tells the
    agent which provenance backed each description so it can cite honestly.
    """

    __tablename__ = "codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Combined `<TYPE>:<value>` (e.g. `"CPT:99213"`, `"HCPCS:G0008"`,
    # `"NDC:12345-1234-12"`, `"CDM:SUP-15000"`). Type uppercase, no whitespace.
    # When the publisher leaves the type cell empty, just the bare value is
    # stored. Length 32 fits all observed cases (corpus max is 28).
    code: Mapped[str] = mapped_column(String(32), nullable=False)

    official_description: Mapped[Optional[str]] = mapped_column(Text)
    most_common_description: Mapped[Optional[str]] = mapped_column(Text)
    gemma_description: Mapped[Optional[str]] = mapped_column(Text)
    # Curated comma-separated lowercase consumer-search aliases (loaded
    # from data/code_keywords.md via scripts/load_code_keywords.py).
    # Sits alongside the description columns in find_procedure's LIKE search.
    keywords: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(128))
    typical_setting: Mapped[Optional[str]] = mapped_column(String(32))

    date_created: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    date_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint("code", name="idx_code"),
    )


# --- Entity: hospitals ---------------------------------------------------------

class Hospital(Base):
    """One row per physical hospital location. MRF files are the sole source
    of truth — no CMS seed, no external augmentation.

    Column sources:

      Directly from MRF row 1-2 header
          hospital_name        — verbatim. Often the system (Hawaii Pacific
                                  Health, MaineHealth, NYU Langone); for
                                  single-location publishers equals
                                  `location_name`.
          location_name        — verbatim. The actual hospital location.
                                  Always populated. (CY2026 renamed
                                  `hospital_location` → `location_name`;
                                  parser maps both.)
          hospital_address     — verbatim free-text. City/state/zip parsed
                                  out into separate columns at ingest.
          license_number       — value before the `|` in column header
                                  `license_number|<state>`.
          license_state        — the `<state>` portion of that column header.

      Derived at ingest time
          ein                  — first 9 digits of the MRF *filename* per
                                  §180.50; not in the file body.
          city, state, zip     — parsed from hospital_address.
          lat, lng             — geocoded post-ingest (US Census Geocoder
                                  batch + ZIP centroid fallback).

    Identity: there's no natural unique key without CCN. Soft identity at
    ingest time is (ein, license_number, license_state, location_name) —
    the loader looks up an existing row by that tuple and upserts. CCN,
    website, hospital_type, ownership are not tracked because they don't
    appear in MRFs.

    NPIs live in the `hospital_npis` child table — a single hospital can
    declare 2-3 Type 2 NPIs in one MRF `type_2_npi` cell (pipe-separated).
    """

    __tablename__ = "hospitals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # EIN from filename per §180.50
    ein: Mapped[Optional[str]] = mapped_column(String(9))

    # Names — MRF column names verbatim
    hospital_name: Mapped[Optional[str]] = mapped_column(String(255))
    location_name: Mapped[str] = mapped_column(String(512), nullable=False)

    # Address from MRF + parsed components + geocode
    hospital_address: Mapped[Optional[str]] = mapped_column(String(512))
    city: Mapped[Optional[str]] = mapped_column(String(128))
    state: Mapped[Optional[str]] = mapped_column(String(2))
    zip: Mapped[Optional[str]] = mapped_column(String(10))
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lng: Mapped[Optional[float]] = mapped_column(Float)

    # State licensure (from MRF row 1 `license_number|<state>`)
    license_number: Mapped[Optional[str]] = mapped_column(String(64))
    license_state: Mapped[Optional[str]] = mapped_column(String(2))

    date_created: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    date_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    __table_args__ = (
        # "look up hospital by EIN" — used by the ingest upsert path to
        # match an MRF's filename-derived EIN against existing rows.
        Index("idx_ein", "ein"),
        # "hospitals in city X" — direct city filter for the search UI.
        Index("idx_city", "city"),
        # "hospitals in state X" — direct state filter for the search UI.
        Index("idx_state", "state"),
        # "hospitals in ZIP Z" — ZIP-bounded queries (radius search starts
        # by widening from a center ZIP).
        Index("idx_zip", "zip"),
        # "find by name" — autocomplete / typeahead.
        Index("idx_hospital_name", "hospital_name"),
    )


class HospitalNpi(Base):
    """One row per (hospital, Type 2 NPI). Normalizes the multi-NPI cell
    that MRFs publish as a pipe-separated string in row 1-2 `type_2_npi`.

    Examples from the corpus: Penrose Hospital declares 2 NPIs
    (`1801436415|1932112125`); Saint Anthony Hospital declares 3.

    CY2026 §180.50(b)(2)(i)(A) requires hospitals to include ALL Type 2 NPIs
    with primary taxonomy starting `28` (hospital) or `27` (hospital unit).
    """

    __tablename__ = "hospital_npis"

    hospital_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hospitals.id", ondelete="CASCADE"), primary_key=True
    )
    npi: Mapped[str] = mapped_column(String(10), primary_key=True)

    date_created: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    date_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    __table_args__ = (
        # "which hospital owns this NPI?" — ingest matches MRF row 1 NPIs
        # against existing hospital records.
        Index("idx_npi", "npi"),
    )


# --- Provenance: mrfs_csv (append-only download log) ---------------------------

class MrfCsv(Base):
    """Download log — one row per download event. No UNIQUE constraint.

    Republishes are kept as separate snapshots over time, distinguished by
    `last_updated_on`. Queries that need "the latest MRF for this hospital"
    join through `hospital_mrfs` and `ORDER BY last_updated_on DESC LIMIT 1`.

    See ingest-mrf SKILL.md §"mrfs_csv is an append-only download log".
    """

    __tablename__ = "mrfs_csv"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Source URL we fetched from. URL/filename are kept for provenance display only, not lookup.
    mrf_url: Mapped[str] = mapped_column(String(768), nullable=False)
    # Local filename only, no path. The §180.50 filename embeds EIN + NPI + name.
    filename: Mapped[str] = mapped_column(String(512), nullable=False)

    # From MRF row 1-2 header
    last_updated_on: Mapped[Optional[str]] = mapped_column(String(10))  # YYYY-MM-DD
    version: Mapped[Optional[str]] = mapped_column(String(16))
    # CY2026 v3.0 only; NULL on v2.x snapshots.
    attestation: Mapped[Optional[bool]] = mapped_column(Boolean)
    attester_name: Mapped[Optional[str]] = mapped_column(String(255))

    # From cms-hpt.txt discovery
    contact_name: Mapped[Optional[str]] = mapped_column(String(255))
    contact_email: Mapped[Optional[str]] = mapped_column(String(255))

    # SHA-256 of the downloaded MRF bytes. Used for deduplication at ingest time.
    # single mrfs_csv row even when several hospitals publish the identical file (Cottage Health, Kaiser). 
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64))

    date_created: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    date_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    __table_args__ = (
        # "is this byte-identical to an MRF we already ingested?" — dedupe key
        # for files that multiple hospitals publish (Cottage Health, Kaiser).
        UniqueConstraint("content_sha256", name="idx_content_sha256"),
        # "latest MRF for a hospital" — ORDER BY last_updated_on DESC LIMIT 1
        # after joining through hospital_mrfs.
        Index("idx_last_updated_on", "last_updated_on"),
    )


# --- Junction: hospital_mrfs ---------------------------------------------------

class HospitalMrf(Base):
    """Many-to-many junction. One MRF can cover many hospitals (Southwestern
    Vermont MC: 5 locations). One hospital appears in many MRFs over time
    (NYU Langone publishes 4 separate per-campus MRFs; quarterly republishes
    multiply further).

    Populated when an MRF header is parsed — one row per (hospital, this mrf)
    location declared.
    """

    __tablename__ = "hospital_mrfs"

    hospital_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hospitals.id", ondelete="CASCADE"), primary_key=True
    )
    mrf_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mrfs_csv.id", ondelete="CASCADE"), primary_key=True
    )

    date_created: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    date_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


# --- Derived: hospital_code_charges (charge-level facts; 1 row per MRF charge row)

class HospitalCodeCharge(Base):
    """One row per *service* a hospital prices in one MRF snapshot. Charge-level
    facts that don't vary per payer: gross / cash / de-identified min / max.

    Billing codes attach via the `hospital_code_charge_codes` junction — CMS
    allows up to 4 codes per MRF row (CPT + HCPCS + revenue + ...) for the same
    underlying service, all sharing the same price. Storing one row per service
    and fanning codes out through the junction avoids 2.4× row blowup at corpus
    scale (~150M → ~360M without the junction).

    Snapshots are append-only — each MRF re-ingest adds new rows alongside the
    older ones. "Latest charge for a hospital+code" joins through the junction
    + `mrfs_csv` ordered by `last_updated_on DESC`. No UNIQUE constraint here:
    `mrfs_csv.content_sha256` blocks re-ingest of identical files, and the
    parser drops exact-duplicate MRF rows before insert, so the only protection
    needed is the synthetic PK.
    """

    __tablename__ = "hospital_code_charges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    hospital_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False
    )
    mrf_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mrfs_csv.id", ondelete="CASCADE"), nullable=False
    )

    setting: Mapped[Optional[str]] = mapped_column(String(32))
    # Raw description from the MRF row — kept for debugging the
    # hospital-vs-CPT descriptor mismatch (Scripps' "HC G-Tube Removal Only"
    # for CPT 99213 etc.). Not user-facing.
    description: Mapped[Optional[str]] = mapped_column(Text)
    # CPT/HCPCS modifiers, pipe-separated when multiple (e.g. "25", "25|59",
    # "LT|RT"). Modifiers technically change the procedure's meaning, so a
    # hospital can list 99213 and 99213-25 separately. NOT part of the UNIQUE
    # key for now — if real collisions show up at ingest, add it.
    modifiers: Mapped[Optional[str]] = mapped_column(String(64))
    # Drug-specific (NDC rows). Unit = "mL" / "mg" / "UNITS"; type = "ML" /
    # "GR" / "UN" short codes. NULL on non-drug rows (CPT/HCPCS/DRG/etc.).
    drug_unit_of_measurement: Mapped[Optional[str]] = mapped_column(String(32))
    drug_type_of_measurement: Mapped[Optional[str]] = mapped_column(String(8))
    # Free-text per-charge notes — usually lookback-period boilerplate or
    # vendor caveats. Often empty; TEXT to allow long paragraphs.
    additional_generic_notes: Mapped[Optional[str]] = mapped_column(Text)

    gross_charge: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(14, 2))
    discounted_cash_price: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(14, 2))
    min_negotiated_charge: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(14, 2))
    max_negotiated_charge: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(14, 2))

    date_created: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    date_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    __table_args__ = (
        # "all charges at this hospital" — hospital detail page.
        Index("idx_hospital_id", "hospital_id"),
        # "what did this MRF contribute?" — joins for freshness queries and
        # cleanup when a snapshot is superseded.
        Index("idx_mrf_id", "mrf_id"),
    )


# --- Junction: hospital_code_charge_codes (codes per charge; 1-4 rows per charge)

class HospitalCodeChargeCode(Base):
    """Junction linking a charge to its 1-4 billing codes.

    CMS allows up to 4 codes per MRF row — the same service may be billable as
    a CPT *and* an HCPCS *and* a revenue code; price is identical across them.
    The junction keeps prices in `hospital_code_charges` once and lets all the
    codes resolve to the same charge, avoiding ~2.4× row blowup vs. an
    emit-per-code design.

    No code-type whitelist. Every non-empty `code|N` cell creates a junction
    row, including hospital-internal types like `LOCAL` / `CDM` / `RC`. The
    raw signal stays; the agent or UI can filter by code-type prefix at query
    time (`code LIKE 'CPT:%'`).
    """

    __tablename__ = "hospital_code_charge_codes"

    hospital_code_charge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hospital_code_charges.id", ondelete="CASCADE"), primary_key=True
    )
    code_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("codes.id", ondelete="RESTRICT"), primary_key=True
    )

    date_created: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    date_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    __table_args__ = (
        # "all charges for code X" — primary read path for code lookups.
        # PK (hospital_code_charge_id, code_id) covers the reverse direction
        # ("which codes apply to this charge?").
        Index("idx_code_id", "code_id"),
    )


# --- Derived: hospital_payer_rates (per-payer facts; N rows per item) ----------

class HospitalPayerRate(Base):
    """One row per (charge × payer × plan). Per-payer facts: negotiated charges,
    methodology, allowed-amount stats (CY2026).

    `payer_name_raw` is preserved verbatim from the MRF — no canonicalization
    layer. Filter on it with LIKE patterns ("aetna", "anthem", etc.); the
    agent issues multiple patterns to cover variant spellings.

    The four allowed-amount columns are required by CY2026 §180.50(b)(2)(ii)(C)
    when the negotiated charge is a percentage or algorithm (i.e. dollar can't
    be expressed). `allowed_amounts_count` is VARCHAR because "1 through 10"
    is a valid anonymized small-count value.
    """

    __tablename__ = "hospital_payer_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    hospital_code_charge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hospital_code_charges.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized from `hospital_code_charges.mrf_id` so freshness queries
    # ("rate as of <date>") don't need a 2-table join through the charge.
    # Always equal to the parent charge's mrf_id; populated at ingest time.
    mrf_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mrfs_csv.id", ondelete="CASCADE"), nullable=False
    )
    payer_name_raw: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_name: Mapped[Optional[str]] = mapped_column(String(255))

    # Negotiated charge — at least one of these three must be populated
    # whenever payer_name+plan_name are set (CY2026 validation, filter rule 3.7)
    negotiated_dollar: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(14, 2))
    negotiated_percentage: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 4))
    negotiated_algorithm: Mapped[Optional[str]] = mapped_column(Text)
    methodology: Mapped[Optional[str]] = mapped_column(String(64))

    # Payer's own estimate of what they'd allow on this code (CY2026
    # §180.50(b)(2)(ii)(C)). Different from the historical percentile stats
    # below — this is forward-looking.
    estimated_allowed_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(14, 2))

    # Allowed-amount stats (CY2026; required when percentage or algorithm set)
    median_allowed_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(14, 2))
    p10_allowed_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(14, 2))
    p90_allowed_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(14, 2))
    # VARCHAR because "1 through 10" is a valid spec value alongside numbers.
    allowed_amounts_count: Mapped[Optional[str]] = mapped_column(String(16))

    additional_payer_notes: Mapped[Optional[str]] = mapped_column(Text)

    date_created: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    date_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    __table_args__ = (
        # Every payer-rate read joins on the parent charge — required FK path.
        Index("idx_hospital_code_charge_id", "hospital_code_charge_id"),
        # "rates for payer matching <pattern>" — prefix B-tree, supports
        # `LIKE 'aetna%'`. Leading-wildcard (`LIKE '%aetna%'`) still scans;
        # switch to FULLTEXT if substring search is ever needed at scale.
        Index("idx_payer_name_raw", "payer_name_raw"),
        # Freshness lookups ("show me the latest rate for this hospital+code")
        # filter on mrf_id (joined to mrfs_csv.last_updated_on). Without this
        # index the join is a full scan of 63M rows.
        Index("idx_payer_rates_mrf_id", "mrf_id"),
    )


# --- Chat (orthogonal to pricing; powers the agent UI) ------------------------

class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Free-form key/value bag. Avoids ALTERs every time we add a UI preference.
    attributes: Mapped[Optional[dict]] = mapped_column(JSON)

    date_created: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    date_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    __table_args__ = (
        # Chat sidebar list — ORDER BY date_updated DESC.
        Index("idx_date_updated", "date_updated"),
    )


class ChatRequest(Base):
    """One row per Gemini generateContent round-trip. Sorted by date_created
    per chat gives the exact agent loop trail — useful for cost auditing,
    replay, and debugging.
    """

    __tablename__ = "chat_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalized: the user-typed message that initiated this turn block.
    # Every row in a single agent loop carries the same value, so the wire
    # assembler can group rows by user_message without a separate messages
    # table. The placeholder row inserted by post_message has this set and
    # the response fields null, so the user bubble renders the instant they
    # hit send.
    user_message: Mapped[Optional[str]] = mapped_column(Text)

    # What we POSTed to Gemini — the full `contents` array including the
    # system instruction prepended to the first user turn.
    request: Mapped[Optional[dict]] = mapped_column(JSON)
    response: Mapped[Optional[dict]] = mapped_column(JSON)

    # Denormalized extracts pulled out at insert time so common queries don't
    # need to re-parse the JSON.
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSON)
    tool_results: Mapped[Optional[dict]] = mapped_column(MEDIUMTEXT)
    reply_text: Mapped[Optional[str]] = mapped_column(Text)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Only populated for thinking-family models (Gemini 2.5+).
    thought_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Which model produced this round-trip (e.g. "gemma-4-26b-a4b-it").
    model: Mapped[str] = mapped_column(String(64), nullable=False)

    # {status, body, model} if the call failed before yielding usage metadata.
    error: Mapped[Optional[dict]] = mapped_column(JSON)

    # Rendering-specific bag — UI hints (citation styles, collapse state,
    # etc.) that don't belong in the Gemini request/response blob. Mirrors
    # `chats.attributes` for the same reason: avoids ALTERs every time the
    # frontend adds a new render flag.
    attributes: Mapped[Optional[dict]] = mapped_column(JSON)

    date_created: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    date_updated: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    __table_args__ = (
        # Load a chat's full turn trail in order — every chat page fetch.
        Index("idx_chat_id_date_created", "chat_id", "date_created"),
    )
