"""FastAPI dependencies — DB session + request-scoped helpers."""

from __future__ import annotations

from typing import Iterator

from sqlalchemy.orm import Session

from db.session import SessionLocal


def get_db() -> Iterator[Session]:
    """Yield a SQLAlchemy session, ensuring it's closed after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
