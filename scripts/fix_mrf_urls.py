"""One-shot: replace file:// mrf_url values with the real source URL.

The ingest pipeline stored the local download path (file://...) in
`mrfs_csv.mrf_url` for a subset of MRFs instead of the hospital's
upstream URL. data/mrf_index.csv has the authoritative source URL
keyed by filename — this script copies it back into the DB.

Idempotent: re-running matches only rows that still have file:// URLs
and updates them once. Run with the cloud-sql-proxy active for prod
or against local mysql directly.

  cloud-sql-proxy health-496300:us-west1:health-prod --port 3307 &
  DB_PW=$(gcloud secrets versions access latest --secret=health-db-root-password)
  DATABASE_URL="mysql+pymysql://root:$DB_PW@127.0.0.1:3307/health?charset=utf8mb4" \\
    uv run --project packages/db python scripts/fix_mrf_urls.py
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


load_dotenv()
CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "mrf_index.csv"


def load_filename_to_url(csv_path: Path) -> dict[str, str]:
    """Return {filename: file_url} from the discovery index."""
    by_filename: dict[str, str] = {}
    with csv_path.open() as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            filename = (row.get("filename") or "").strip()
            url = (row.get("file_url") or "").strip()
            if filename and url and not url.startswith("file://"):
                # Multiple rows can share a filename (multi-location MRFs);
                # any non-file:// URL wins, last one assigned.
                by_filename[filename] = url
    return by_filename


def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set. See script docstring.", file=sys.stderr)
        return 2

    by_filename = load_filename_to_url(CSV_PATH)
    print(f"Loaded {len(by_filename)} (filename -> url) pairs from mrf_index.csv")

    engine = create_engine(db_url, future=True)
    with engine.begin() as conn:
        broken = conn.execute(
            text(
                "SELECT id, filename FROM mrfs_csv "
                "WHERE mrf_url LIKE 'file://%'"
            )
        ).all()

        fixed = 0
        unmatched: list[str] = []
        for row in broken:
            real = by_filename.get(row.filename)
            if not real:
                unmatched.append(row.filename)
                continue
            conn.execute(
                text("UPDATE mrfs_csv SET mrf_url = :u WHERE id = :id"),
                {"u": real, "id": row.id},
            )
            fixed += 1

    print(f"Fixed {fixed}/{len(broken)} broken rows.")
    if unmatched:
        print(
            f"{len(unmatched)} row(s) had no match in mrf_index.csv "
            f"(filename not in the discovery index):"
        )
        for f in unmatched[:10]:
            print(f"  {f}")
        if len(unmatched) > 10:
            print(f"  ... +{len(unmatched) - 10} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
