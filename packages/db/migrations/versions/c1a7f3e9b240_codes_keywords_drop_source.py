"""codes: add keywords, drop unused source/source_date

This revision reconciles two pieces of out-of-band schema drift:

  1. Cloud SQL got `keywords TEXT NULL` added by
     scripts/load_code_keywords.py (which runs ALTER TABLE inline so
     the loader script works against a fresh DB). Local mysql never
     got that ALTER, so the column was missing locally.

  2. `source` (VARCHAR(64)) and `source_date` (DATE) on the codes
     table were planned for provenance tracking but never wired up.
     Both columns are NULL across the corpus and don't appear in any
     query.

The upgrade adds `keywords` if missing and drops the two unused
columns if present, so the same revision is safe to run against:
  * a clean dev DB that doesn't have `keywords` yet
  * Cloud SQL which already has `keywords` and still has the dead
    source columns

Revision ID: c1a7f3e9b240
Revises: 2f084d0dd7fa
Create Date: 2026-05-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c1a7f3e9b240"
down_revision: Union[str, Sequence[str], None] = "2f084d0dd7fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(conn, table: str, column: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "  AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).first()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, "codes", "keywords"):
        op.add_column(
            "codes",
            sa.Column(
                "keywords",
                sa.Text(),
                nullable=True,
                comment=(
                    "Comma-separated lowercase consumer-search aliases; "
                    "LIKE-matched by find_procedure"
                ),
            ),
        )
    if _has_column(conn, "codes", "source_date"):
        op.drop_column("codes", "source_date")
    if _has_column(conn, "codes", "source"):
        op.drop_column("codes", "source")


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, "codes", "source"):
        op.add_column(
            "codes",
            sa.Column("source", sa.String(length=64), nullable=True),
        )
    if not _has_column(conn, "codes", "source_date"):
        op.add_column(
            "codes",
            sa.Column("source_date", sa.Date(), nullable=True),
        )
    if _has_column(conn, "codes", "keywords"):
        op.drop_column("codes", "keywords")
