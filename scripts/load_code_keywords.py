"""Parse data/code_keywords.md and load the curated keywords into codes.keywords.

Idempotent — runs the same UPDATEs every time. Run via the cloud-sql-proxy
(`cloud-sql-proxy ... --port 3307`) with DATABASE_URL pointed at 127.0.0.1.

Why parse the markdown instead of keeping a CSV: the markdown is the
source-of-truth document the human reviews; duplicating into a CSV invites
drift. Parsing the same file the reviewer reads guarantees alignment.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


load_dotenv()
MD = Path(__file__).resolve().parent.parent / "data" / "code_keywords.md"
ROW_RE = re.compile(r"^\|\s*((?:CPT|HCPCS):[A-Za-z0-9]+)\s*\|")


def parse_rows(md_path: Path) -> list[tuple[str, str]]:
    """Return [(code, keywords), ...] from every markdown table row whose first
    cell matches a CPT/HCPCS code. Keywords is always the 3rd cell; tables
    that have a 4th "Notes" column are tolerated."""
    rows: list[tuple[str, str]] = []
    for raw in md_path.read_text().splitlines():
        if not ROW_RE.match(raw):
            continue
        cells = [c.strip() for c in raw.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        code, _meaning, keywords = cells[0], cells[1], cells[2]
        if "," not in keywords:
            # No keyword list (or single-keyword row); skip rather than
            # write a single-entry value that might be a header artefact.
            continue
        rows.append((code, keywords))
    return rows


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print(
            "DATABASE_URL not set. Start the proxy and export:\n"
            "  cloud-sql-proxy health-496300:us-west1:health-prod --port 3307 &\n"
            "  DB_PW=$(gcloud secrets versions access latest --secret=health-db-root-password)\n"
            "  export DATABASE_URL=\"mysql+pymysql://root:$DB_PW@127.0.0.1:3307/health?charset=utf8mb4\"",
            file=sys.stderr,
        )
        return 2

    rows = parse_rows(MD)
    print(f"Parsed {len(rows)} (code, keywords) rows from {MD.name}")

    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        # Add the column if it doesn't exist. MySQL 8 doesn't support
        # IF NOT EXISTS on ADD COLUMN, so probe information_schema first.
        exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = DATABASE() "
                "  AND table_name = 'codes' "
                "  AND column_name = 'keywords'"
            )
        ).scalar()
        if not exists:
            print("Adding codes.keywords column...")
            conn.execute(
                text(
                    "ALTER TABLE codes ADD COLUMN keywords TEXT NULL "
                    "COMMENT 'Comma-separated lowercase consumer-search "
                    "aliases; LIKE-matched by find_procedure'"
                )
            )

        # Bulk-update. Each row is its own statement — ~100 statements, runs
        # in well under a second over the proxy.
        matched = 0
        missing: list[str] = []
        for code, keywords in rows:
            result = conn.execute(
                text("UPDATE codes SET keywords = :kw WHERE code = :code"),
                {"kw": keywords, "code": code},
            )
            if result.rowcount > 0:
                matched += 1
            else:
                missing.append(code)

    print(f"Updated {matched}/{len(rows)} codes.")
    if missing:
        print(
            f"{len(missing)} code(s) not found in the codes table (no MRF hospital "
            f"uses them, or wrong type prefix): {', '.join(missing[:20])}"
            + (" ..." if len(missing) > 20 else "")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
