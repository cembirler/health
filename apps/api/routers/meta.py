"""`/api/meta/*` — liveness + whoami.

`whoami` powers the privacy banner at the top of the chat: it tells the user
exactly which two facts the agent gets about them (IP + derived city/state)
and that those are used only to resolve "near me" queries. Reusing the same
ip→geo path the chat handler uses keeps the banner honest — what the user
sees here is literally what the agent gets fed in `request_context`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from deps import get_db
from schemas import HealthStatus, SingleResponse

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/health", response_model=SingleResponse[HealthStatus])
def get_health(db: Session = Depends(get_db)) -> SingleResponse[HealthStatus]:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        raise HTTPException(503, detail={
            "error": f"database unreachable: {e}", "code": "server_error",
        })
    return SingleResponse(data=HealthStatus(
        status="ok",
        db=db_status,
        as_of=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    ))


@router.get("/whoami")
async def whoami(request: Request) -> dict:
    """Return the same {ip, city, region} the agent sees for this request.

    Mirrors the lookup chain in sessions.post_message: try request headers
    first, fall back to ip-api on the public IP if the direct address is
    private (e.g. localhost). Failures collapse to nulls — the banner
    handles that case with a "we couldn't tell" message.
    """
    from geo import client_ip, fetch_public_ip, _is_private_ipv4, ip_to_geo

    direct = client_ip(request)
    if direct and not _is_private_ipv4(direct):
        public_ip: Optional[str] = direct
    else:
        public_ip = await fetch_public_ip()

    geo = ip_to_geo(public_ip) if public_ip else None
    return {
        "data": {
            "ip": public_ip,
            "city": geo.get("city") if geo else None,
            "region": geo.get("region") if geo else None,
            "region_name": geo.get("region_name") if geo else None,
            "zip": geo.get("zip") if geo else None,
        }
    }
