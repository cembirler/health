# Database State

_Snapshot: 2026-05-17. Verified directly against local MySQL `health`._

## What's in the DB

| Metric                          |       Value |
| ------------------------------- | ----------: |
| Hospitals (all CA)              |         359 |
| MRFs loaded (have charge data)  |         333 |
| MRFs with per-payer rates       |         320 |
| Charges (`hospital_code_charges`) |  15,291,943 |
| Payer rates (`hospital_payer_rates`) | 136,809,195 |
| Codes (`codes`)                 |   2,654,196 |
| CA cities covered               |         207 |
| DB on disk                      |     ~42 GB  |

CMS Provider-of-Service file lists **378** California general/short-term/specialty
hospitals subject to §180.50 price transparency. We cover **359 / 378 = 95%**.
Non-CA hospitals were removed; the DB is now California-only.

## Coverage breakdown (by hospital type)

The 359 covered hospitals span the full CMS PoS mix:

- Acute-care / general short-term — the bulk; private and public systems
  (Sutter, Kaiser NorCal subset, Dignity/Common Spirit, Adventist, Tenet,
  Prime, Scripps, Cedars, Stanford, UC Health, county hospitals, etc.)
- Psychiatric — Aurora Las Encinas, Resnick (UCLA), Gateways, Aurora Vista
  del Mar, BHC Alhambra, etc.
- Critical-access / rural — Tahoe Forest, Mammoth, Mayers, Mountains
  Community, Plumas District, Surprise Valley, etc.
- Children's — Valley Children's, Lucile Packard (Stanford), UCSF Benioff
  Oakland, Loma Linda Children's, Rady (San Diego), CHLA, CHOC.
- Federal-aligned (where a transparency file existed) — note most federal
  facilities (VA, DoD, IHS) are exempt; see below.

## Format types loaded

- **Tall-CSV** — CMS v2/v3 "tall" schema; one row per charge × payer.
  Primary ingest path. Highest fidelity.
- **Wide-CSV** — column-per-payer layout; reshaped to tall in-flight by
  the same loader (header sniff + payer-column detection).
- **JSON (CMS v3)** — separate loader. Used when a publisher only ships
  JSON or the CSV twin is corrupt/missing.

Per `mrfs_csv.filename`:

- 328 CSV-loaded MRFs
- 5 JSON-loaded MRFs (Glendale Memorial, El Camino, UCI Regents, Resnick
  UCLA, Santa Monica UCLA Orthopaedic)

The split between tall and wide CSV is not tagged in the DB; the loader
normalizes both into the tall `hospital_code_charges` + `hospital_payer_rates`
shape so downstream code never has to care.

## The 13 "incomplete" MRFs (charges loaded, payer rates absent)

These are **publisher choices**, not parser bugs. The file conforms to the
CMS schema but the publisher zeroed/omitted the per-payer columns and only
published summary fields (gross charge, cash price, min/max negotiated, or
estimated-allowed ranges).

**Group A — summary-range only (4):** publisher emits gross + cash +
min/max negotiated, no per-payer detail.

1. Aurora Las Encinas, LLC — psychiatric, summary range only
2. Contra Costa County (Regional Medical Center) — county hospital, range only
3. San Mateo Medical Center — county hospital, range only
4. Hi-Desert Medical Center — range only on this filing

**Group B — Tenet / Hyve template, gross + cash only (7):** every Tenet
California facility ships via `mrfs.hyvehealthcare.com/TenetHealth/...`.
Files have well-formed code/description/setting + gross & cash but the
payer-rate columns are blank.

5. Desert Regional Medical Center (Tenet)
6. Doctors Hospital of Manteca (Tenet)
7. Doctors Medical Center of Modesto (Tenet)
8. Emanuel Medical Center (Tenet)
9. JFK Memorial Hospital (Tenet)
10. San Ramon Regional Medical Center (Tenet)
11. Desert Regional / sibling filing (Tenet)

**Group C — small/specialty, summary-only (2):**

12. Gateways Hospital and Mental Health Center — two distinct MRFs (a
    standardcharges CSV and a hashed-name file); neither carries per-payer data
13. Kedren Community Health Center — community mental-health, gross/cash only

Net effect: these 13 MRFs contribute charge rows (gross/cash) but no
payer-rate rows. They are searchable by code/description and surface a
gross/cash price; the agent will not produce a per-payer answer for them.

## The 19 hospitals we don't have (378 - 359 outside coverage)

These are split across three buckets:

1. **Federal facilities exempt from §180.50** — VA hospitals, DoD/military
   treatment facilities, IHS clinics that appear on the CMS PoS roster but
   do not publish a hospital-price-transparency MRF.
2. **Blocked-by-WAF / never-retried** — a handful of publishers (mostly
   small operators behind Cloudflare/Akamai bot-management) returned 403
   on every attempt during fetch; we did not loop back with a residential
   proxy. Tracked in `data/raw/mrfs_downloads.csv` with `status=error`.
3. **File-size cap on the JSON pass (>150 MB)** — the JSON loader skipped
   any single file over 150 MB to keep ingest under memory. Affects the
   handful of large multi-facility JSON bundles listed below.

## Excluded JSON giants — future ijson-streaming pass

These JSON files exist in our discovery set but were either too big to
parse with in-memory `json.load()` or arrived as multi-hospital bundles
that need per-hospital splitting before ingest. They are the largest
items on the "rerun with streaming parser" TODO list (~11 files,
>200 MB each):

- **UCSD** — `UC-San-Diego-Standard-Charges-956006144.json` (~3.2 GB,
  single-file dump for the whole UCSD Health system)
- **Providence cluster** — `pricetransparency.providence.org` CA hospitals
  (St. Joseph Orange, St. Jude, Mission, St. Joseph Burbank, St. Johns
  Health Center Santa Monica, St. Mary Apple Valley, Holy Cross Mission
  Hills, Little Co. of Mary Torrance, Little Co. of Mary San Pedro,
  Cedars-Sinai Tarzana) — each 200 MB to 1 GB+ JSON
- **Los Robles Health System** (HCA, JSON ~500 MB)
- **Good Samaritan / PIH Good Samaritan** — JSON twin, ~600 MB
- **Riverside University Health System** — JSON twin, ~250 MB
  (Note: CSV twin was loaded; JSON is the larger source)

Plan: introduce an `ijson`-based streaming pass that yields charges and
payer-rate rows in chunks, so peak RSS stays bounded. Same DB shape, same
loaders — only the JSON parser changes.

## Source-of-truth queries

All numbers above were verified with:

```sql
SELECT COUNT(*) FROM hospitals;                              -- 359
SELECT COUNT(*) FROM hospitals WHERE state='CA';             -- 359
SELECT COUNT(*) FROM mrfs_csv;                               -- 333
SELECT COUNT(DISTINCT mrf_id) FROM hospital_payer_rates;     -- 320
SELECT COUNT(*) FROM hospital_code_charges;                  -- 15,291,943
SELECT COUNT(*) FROM hospital_payer_rates;                   -- 136,809,195
SELECT COUNT(*) FROM codes;                                  -- 2,654,196
SELECT COUNT(DISTINCT city) FROM hospitals WHERE state='CA'; -- 207
SELECT ROUND(SUM(data_length+index_length)/1024/1024/1024,1)
  FROM information_schema.tables WHERE table_schema='health';-- ~42 GB
```

To regenerate the list of 13 incomplete MRFs:

```sql
SELECT DISTINCT m.id, m.filename, h.hospital_name
FROM mrfs_csv m
JOIN hospital_mrfs hm ON hm.mrf_id = m.id
JOIN hospitals h ON h.id = hm.hospital_id
WHERE m.id NOT IN (SELECT DISTINCT mrf_id FROM hospital_payer_rates)
ORDER BY h.hospital_name;
```
