"""Client-IP discovery + public-IPv4 → city/region/zip lookup.

Used by the chat handler to seed the agent's `request_context` with the
visitor's approximate location (so "near me" queries can resolve to a ZIP
without asking) and by `/api/meta/whoami` to power the privacy banner that
tells the user exactly what the agent sees.

`client_ip` reads proxy headers first (X-Forwarded-For, CF-Connecting-IP,
etc.), then falls back to `request.client.host`. `fetch_public_ip` is the
loopback escape hatch — when the FastAPI process and the browser run on the
same box (local dev), `request.client.host` is 127.0.0.1, so we go through
multiple public-IP services to find the egress address. `ip_to_geo` resolves
a public IPv4 to {ip, city, region, region_name, zip, country, lat, lng} via
ip-api.com's free endpoint (45 req/min, no key). Private and non-US IPs
resolve to None.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Optional, Tuple

import httpx


# --- Client IP from request ------------------------------------------------

def _client_ip_from_headers(headers) -> Optional[str]:
    """Pick the real client IP out of proxy headers. `headers` is a Mapping
    (e.g. `Request.headers`). Returns None if no usable hint is present."""
    fwd = headers.get("x-forwarded-for") or headers.get("forwarded")
    if fwd:
        # X-Forwarded-For can be "client, proxy1, proxy2" — first is the client.
        ip = fwd.split(",")[0].strip()
        if ip:
            return ip
    for h in ("x-real-ip", "cf-connecting-ip", "true-client-ip"):
        v = headers.get(h)
        if v:
            return v.strip()
    return None


def client_ip(request) -> Optional[str]:
    """Extract the client IP from a Starlette/FastAPI Request."""
    ip = _client_ip_from_headers(request.headers)
    if ip:
        return ip
    return request.client.host if request.client else None


# --- Public-IP lookup (for localhost dev / NAT'd deployments) ---------------
#
# `request.client.host` is loopback when the FastAPI process and the browser
# are on the same machine, which makes IP-based geo useless. We try several
# zero-config public-IP services until one returns a usable IPv4. The answer
# is the same for every session sharing the same egress, so it's cached
# process-wide with a short TTL.

_PUBLIC_IP_CACHE: dict = {"ip": None, "fetched_at": 0.0}
_PUBLIC_IP_TTL_S = 300  # 5 minutes


async def fetch_public_ip(timeout: float = 3.0) -> Optional[str]:
    """Return the machine's public-facing IPv4, or None on failure.

    Tries multiple public-IP services in order — different corporate
    proxies block different ones (e.g. LinkedIn blocks ipify but allows
    AWS' checkip). First one that returns a sane IPv4 wins. Cached for
    5 minutes per process — public IP doesn't churn faster than that
    for any sane network.
    """
    now = time.time()
    cached = _PUBLIC_IP_CACHE.get("ip")
    if cached and (now - _PUBLIC_IP_CACHE["fetched_at"]) < _PUBLIC_IP_TTL_S:
        return cached
    # Each entry is (url, json_field): json_field=None means plain-text body.
    sources: list[Tuple[str, Optional[str]]] = [
        ("https://checkip.amazonaws.com", None),
        ("https://ifconfig.me/ip", None),
        ("https://ipinfo.io/ip", None),
        ("https://api.ipify.org?format=json", "ip"),
    ]
    async with httpx.AsyncClient(timeout=timeout) as c:
        for url, field in sources:
            try:
                r = await c.get(url)
                r.raise_for_status()
                if field:
                    ip = (r.json() or {}).get(field)
                else:
                    ip = r.text.strip()
                if ip and not _is_private_ipv4(ip):
                    _PUBLIC_IP_CACHE["ip"] = ip
                    _PUBLIC_IP_CACHE["fetched_at"] = now
                    return ip
            except (httpx.HTTPError, ValueError, OSError):
                continue
    return None


def _is_private_ipv4(ip: str) -> bool:
    """Cheap RFC1918 / loopback check so we don't hit ip-api.com for LAN IPs."""
    if not ip:
        return True
    parts = ip.split(".")
    if len(parts) != 4:
        return True  # IPv6 or garbage — treat as non-resolvable for our US-only use
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return True
    return (
        ip.startswith("127.")
        or ip.startswith("10.")
        or (a == 172 and 16 <= b <= 31)
        or ip.startswith("192.168.")
        or ip == "0.0.0.0"
    )


# --- IP → richer geo record -------------------------------------------------

@lru_cache(maxsize=4096)
def ip_to_geo(ip: str) -> Optional[dict]:
    """Resolve a public IPv4 to {ip, city, region, region_name, zip, country,
    lat, lng}. Returns None for private / non-US / errors. Cached per process.
    """
    if not ip or _is_private_ipv4(ip):
        return None
    url = (
        "http://ip-api.com/json/"
        + urllib.parse.quote(ip)
        + "?fields=status,country,region,regionName,city,zip,lat,lon,query"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "health/1.0"})
        with urllib.request.urlopen(req, timeout=3) as r:
            body = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    if body.get("status") != "success":
        return None
    return {
        "ip": body.get("query") or ip,
        "city": body.get("city") or None,
        "region": body.get("region") or None,
        "region_name": body.get("regionName") or None,
        "zip": (body.get("zip") or "").strip()[:10] or None,
        "country": body.get("country") or None,
        "lat": body.get("lat"),
        "lng": body.get("lon"),
    }
