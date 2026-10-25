"""Engine validation against published figures.

CSTEP (2018, ref S1) prints petroleum-product consumption (Table 7, kt) and the resulting emissions
(Table 8, MtCO2e). Both tables were read from the report PDF on 2026-10-25. The engine recomputes
Table 8 from Table 7; a cell that disagrees by more than the tolerance is **flagged, never corrected**
(ref section 8.2). Natural gas is excluded: Table 7 gives it in MMSCM and the library has no sourced
volumetric NCV (V-02).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .engine import Activity, calculate_activity

YEARS = (
    "2008-09",
    "2009-10",
    "2010-11",
    "2011-12",
    "2012-13",
    "2013-14",
    "2014-15",
    "2015-16",
)

# CSTEP column -> library fuel id (HSDO and LDO share one factor set, so both map to diesel)
COLUMN_FUEL = {
    "LPG": "lpg",
    "Naphtha": "naphtha",
    "Kerosene": "kerosene",
    "HSDO": "diesel",
    "LDO": "diesel",
    "FO": "furnace_oil",
    "LSHS": "lshs",
}

# Table 7: consumption in kt, one row per year in YEARS
CONSUMPTION_KT = {
    "LPG": (63, 62, 73, 70, 44, 45, 52, 60),
    "Naphtha": (693, 559, 154, 163, 203, 240, 207, 37),
    "Kerosene": (128, 134, 139, 123, 115, 48, 117, 113),
    "HSDO": (1469, 1603, 2170, 2262, 2319, 1425, 1748, 1922),
    "LDO": (179, 150, 179, 178, 174, 181, 164, 184),
    "FO": (3848, 3653, 3516, 2916, 2356, 1984, 2175, 2564),
    "LSHS": (526, 320, 482, 291, 149, 44, 47, 29),
}

# Table 8: published emissions in MtCO2e
PUBLISHED_MT = {
    "LPG": ("0.19", "0.19", "0.22", "0.21", "0.13", "0.14", "0.16", "0.22"),
    "Naphtha": ("3.63", "2.02", "1.33", "0.59", "1.08", "0.68", "0.63", "0.16"),
    "Kerosene": ("0.41", "0.42", "0.44", "0.39", "0.37", "0.15", "0.37", "0.36"),
    "HSDO": ("4.70", "5.13", "6.94", "7.23", "7.42", "4.56", "5.59", "6.14"),
    "LDO": ("0.58", "0.48", "0.57", "0.57", "0.56", "0.58", "0.53", "0.59"),
    "FO": ("11.95", "11.35", "10.92", "9.06", "1.09", "0.96", "0.61", "0.84"),
    "LSHS": ("1.55", "0.94", "1.42", "0.86", "0.44", "0.13", "0.14", "0.09"),
}

TOLERANCE = Decimal("0.01")  # a recomputed value within 1% of the printed one is a match
ROUNDING = Decimal(
    "0.01"
)  # Table 8 prints two decimals: one unit in the last place is also a match


@dataclass(frozen=True)
class Comparison:
    column: str
    year: str
    quantity_kt: Decimal
    recomputed_mt: Decimal
    published_mt: Decimal
    ratio: Decimal  # published / recomputed
    matches: bool


def compare_cstep(tolerance: Decimal = TOLERANCE) -> list[Comparison]:
    rows = []
    for column, fuel in COLUMN_FUEL.items():
        for i, year in enumerate(YEARS):
            qty = Decimal(CONSUMPTION_KT[column][i])
            recomputed = calculate_activity(
                Activity(item_id=fuel, quantity=qty, unit="kt")
            ).co2e_t / Decimal(1_000_000)
            published = Decimal(PUBLISHED_MT[column][i])
            ratio = published / recomputed
            within = abs(published - recomputed) <= max(tolerance * recomputed, ROUNDING)
            rows.append(Comparison(column, year, qty, recomputed, published, ratio, within))
    return rows


def flagged(tolerance: Decimal = TOLERANCE) -> list[Comparison]:
    return [c for c in compare_cstep(tolerance) if not c.matches]
