"""Fiscal-year labels. Indian FY runs April to March; the canonical label is 'FY2024-25'."""

from __future__ import annotations

import re

_FY_RE = re.compile(r"^(?:FY)?(\d{2}|\d{4})-(\d{2}|\d{4})$")


class FiscalYearError(ValueError):
    pass


def normalize_fy(raw: str) -> str:
    """'2024-25', 'FY 2024-25', 'FY2024-2025', 'FY24-25' -> 'FY2024-25'.

    Both years must be present and consecutive. A bare 'FY25' or '2025' is rejected: whether it
    means the year ending March 2025 is a convention, and no label is guessed.
    """
    text = re.sub(r"[\s_]+", "", raw.strip().upper().replace("–", "-").replace("—", "-"))
    m = _FY_RE.match(text)
    if not m:
        raise FiscalYearError(f"fiscal year {raw!r} must look like FY2024-25 (both years given)")
    first, second = m.groups()
    if len(first) == 2:
        # two-digit start year: only unambiguous with a two-digit end year (FY24-25)
        if len(second) != 2:
            raise FiscalYearError(f"fiscal year {raw!r} is ambiguous; write FY2024-25")
        start = 2000 + int(first)
    else:
        start = int(first)
    end_two = int(second[-2:])
    if len(second) == 4 and int(second) != start + 1:
        raise FiscalYearError(f"fiscal year {raw!r}: years are not consecutive")
    if end_two != (start + 1) % 100:
        raise FiscalYearError(f"fiscal year {raw!r}: years are not consecutive")
    return f"FY{start}-{(start + 1) % 100:02d}"


def start_year(fy: str) -> int:
    return int(fy[2:6])


def shift_fy(fy: str, years: int) -> str:
    """Canonical label `years` fiscal years after `fy` (negative for earlier)."""
    start = start_year(fy) + years
    return f"FY{start}-{(start + 1) % 100:02d}"
