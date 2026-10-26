"""Published national and sectoral estimates, kept as data with their source and year.

These are other people's published numbers, quoted so a reader can see how far they disagree. Nothing
here is computed by GreenEIS. Each row says whether the figure was read in the original document
(``read_in_original``), is a figure the original cites from another study (``cited_by_original``), and
the unit is in the row, never implied.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from .factors import DATA_DIR

STATUSES = ("read_in_original", "cited_by_original")


class NationalError(ValueError):
    """A national estimate is missing its value, unit, source or year."""


@dataclass(frozen=True)
class NationalEstimate:
    id: str
    label: str
    low: Decimal
    high: Decimal
    unit: str
    year: str
    source: str
    status: str
    note: str

    @property
    def is_range(self) -> bool:
        return self.low != self.high


def _required(row: dict[str, str], column: str, where: str) -> str:
    raw = (row.get(column) or "").strip()
    if not raw:
        raise NationalError(
            f"{where}: '{column}' is empty (every estimate needs a unit, source and year)"
        )
    return raw


def _number(row: dict[str, str], column: str, where: str) -> Decimal:
    raw = _required(row, column, where)
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise NationalError(f"{where}: '{column}' = {raw!r} is not a number") from exc


def parse(rows: list[dict[str, str]]) -> dict[str, NationalEstimate]:
    out: dict[str, NationalEstimate] = {}
    for row in rows:
        est_id = _required(row, "id", "national.csv")
        where = f"national.csv[{est_id}]"
        if est_id in out:
            raise NationalError(f"{where}: duplicate id")
        status = _required(row, "status", where)
        if status not in STATUSES:
            raise NationalError(f"{where}: status {status!r} is not one of {STATUSES}")
        low, high = _number(row, "value_low", where), _number(row, "value_high", where)
        if high < low:
            raise NationalError(f"{where}: value_high is below value_low")
        out[est_id] = NationalEstimate(
            id=est_id,
            label=_required(row, "label", where),
            low=low,
            high=high,
            unit=_required(row, "unit", where),
            year=_required(row, "year", where),
            source=_required(row, "source", where),
            status=status,
            note=(row.get("note") or "").strip(),
        )
    return out


@lru_cache(maxsize=1)
def load_national() -> dict[str, NationalEstimate]:
    with (DATA_DIR / "national.csv").open(encoding="utf-8", newline="") as handle:
        return parse(list(csv.DictReader(handle)))
