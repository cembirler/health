"""Shared DB utilities — currently just MRF date normalization.

Hospitals stamp `last_updated_on` in their MRFs using whatever format their
ops team prefers. We've seen at minimum:
  - YYYY-MM-DD   (ISO, ~65%)
  - M/D/YYYY     (US slash, ~35%)
  - M/D/YY       (2-digit year, rare)

Storage column is `VARCHAR(10)`, so we normalize to YYYY-MM-DD on ingest and
return None for anything we can't parse (instead of carrying junk forward).
"""

from __future__ import annotations

import re
from typing import Optional


_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_SLASH_4Y = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_SLASH_2Y = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2})$")
_DASH_4Y = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")


def normalize_mrf_date(s: Optional[str]) -> Optional[str]:
    """Return YYYY-MM-DD or None.

    Accepts:
      - '2026-03-04', '2026-3-4'      → '2026-03-04'
      - '3/4/2026', '03/04/2026'      → '2026-03-04'
      - '3/4/26'                       → '2026-03-04' (2-digit year: 50-99 → 19xx, else 20xx)
      - '3-4-2026'                     → '2026-03-04'

    Invalid or unparseable input returns None — never raises.
    """
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None

    m = _ISO.match(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _SLASH_4Y.match(s) or _DASH_4Y.match(s)
        if m:
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = _SLASH_2Y.match(s)
            if not m:
                return None
            mo, d, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
            y = 1900 + yy if yy >= 50 else 2000 + yy

    if not (1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"
