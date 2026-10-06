"""Synthetic BRSR-like data in manual-entry CSV format, with planted defects (dry runs and tests).

Nothing here describes a real company. The file is written in the same format a human would fill in,
with values in mixed as-reported units, so the dry run exercises the real ingest -> standardize ->
validate -> KPI path. Planted defects are known in advance so tests can check the validators find
exactly them.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from gauge.config import IndicatorsConfig, StudyConfig
from gauge.kpi.formula import CONTEXT
from gauge.quality import validators as q
from gauge.standardize.units import factor_to_canonical


@dataclass(frozen=True)
class Defect:
    """A defect planted in the synthetic data and the validator rule that must catch it."""

    symbol: str
    fy: str | None
    indicator: str | None
    rule: str
    what: str


SYNTHETIC_DEFECTS = (
    Defect(
        "SYNA1", "FY2024-25", "energy_renewable", q.RENEWABLE_LE_TOTAL, "renewable = 1.2 x total"
    ),
    Defect(
        "SYNB2",
        "FY2023-24",
        "water_consumption",
        q.CONSUMPTION_LE_WITHDRAWAL,
        "consumption = 1.3 x withdrawal",
    ),
    Defect(
        "SYNA3",
        "FY2022-23",
        "waste_recovered",
        q.RECOVERED_LE_GENERATED,
        "recovered = 1.1 x generated",
    ),
    Defect("SYNB3", "FY2022-23", "waste_generated", q.MISSING_INDICATOR, "value omitted"),
    Defect(
        "SYNB1", None, None, q.BOUNDARY_CHANGE, "standalone in the first year, consolidated after"
    ),
    Defect("SYNA2", "FY2024-25", "scope2_emissions", q.CHANGE_2Y, "Scope 2 multiplied by 3.5"),
)

# As-reported unit spellings a synthetic company may use, per measurement group.
_REPORTED_UNITS = {
    "revenue": ["INR crore", "INR lakh"],
    "energy": ["GJ", "MWh", "TJ"],
    "water": ["kL", "m3", "Mn Lt"],
    "waste": ["t", "kg", "MT"],
    "emissions": ["tCO2e", "MT"],
}
_GROUP = {
    "revenue_from_operations": "revenue",
    "energy_total": "energy",
    "energy_renewable": "energy",
    "water_withdrawal": "water",
    "water_consumption": "water",
    "waste_generated": "waste",
    "waste_recovered": "waste",
    "scope1_emissions": "emissions",
    "scope2_emissions": "emissions",
}
_SECTOR_SCALE = [1.0, 0.35, 0.7, 0.5]
_THREE_DP = Decimal("0.001")
HEADER = [
    "company",
    "nse_symbol",
    "sector",
    "fy",
    "indicator",
    "value",
    "unit",
    "boundary",
    "assured",
    "source_url",
    "page_ref",
]


def synthetic_symbol(sector_index: int, company_index: int) -> str:
    return f"SYN{chr(ord('A') + sector_index)}{company_index}"


def _to_reported(canonical: Decimal, unit: str, canonical_unit: str) -> Decimal:
    """Express a canonical value in the unit a company 'reported' it in (3 decimal places)."""
    quotient = CONTEXT.divide(canonical, factor_to_canonical(unit, canonical_unit))
    return quotient.quantize(_THREE_DP, context=CONTEXT)


def _apply_defects(symbol, fy, first_fy, canonical, boundary):
    """Plant the defects for (symbol, fy). Returns (boundary, omitted indicators, defects hit)."""
    omitted: set[str] = set()
    hit: list[Defect] = []
    for d in SYNTHETIC_DEFECTS:
        if d.symbol != symbol:
            continue
        if d.rule == q.BOUNDARY_CHANGE:
            if fy == first_fy:
                boundary = "standalone"
                hit.append(d)
            continue
        if d.fy != fy:
            continue
        if d.rule == q.RENEWABLE_LE_TOTAL:
            canonical["energy_renewable"] = round(canonical["energy_total"] * 1.2)
        elif d.rule == q.CONSUMPTION_LE_WITHDRAWAL:
            canonical["water_consumption"] = round(canonical["water_withdrawal"] * 1.3)
        elif d.rule == q.RECOVERED_LE_GENERATED:
            canonical["waste_recovered"] = round(canonical["waste_generated"] * 1.1)
        elif d.rule == q.MISSING_INDICATOR:
            omitted.add(d.indicator)
        elif d.rule == q.CHANGE_2Y:
            canonical[d.indicator] = round(canonical[d.indicator] * 3.5)
        hit.append(d)
    return boundary, omitted, hit


def write_synthetic_manual_csv(
    cfg: StudyConfig, indicators: IndicatorsConfig, path: Path
) -> list[Defect]:
    """Write seeded synthetic filings for every sector x company x trend year. Returns the defects
    that were planted (those whose company exists in this configuration)."""
    rng = random.Random(cfg.runs.master_seed)
    canon_unit = {i.code: i.unit for i in indicators.indicators}
    fys = cfg.study.trend_fys
    planted: list[Defect] = []
    rows: list[list[str]] = []

    for si, sector in enumerate(cfg.study.sectors):
        scale = _SECTOR_SCALE[si % len(_SECTOR_SCALE)]
        for ci in range(1, cfg.study.companies_per_sector + 1):
            symbol = synthetic_symbol(si, ci)
            name = f"Synthetic {symbol[3:]} Ltd"
            revenue, growth = rng.uniform(5000, 40000), rng.uniform(0.04, 0.14)
            energy_i, emis_i = rng.uniform(150, 700) * scale, rng.uniform(20, 120) * scale
            scope2_share = rng.uniform(0.15, 0.45)
            water_i, waste_i = rng.uniform(300, 4000) * scale, rng.uniform(1, 12) * scale
            renew, recovery = rng.uniform(5, 50), rng.uniform(40, 95)
            drift, renew_step = rng.uniform(-0.10, 0.05), rng.uniform(0.0, 4.0)
            units = {group: rng.choice(options) for group, options in _REPORTED_UNITS.items()}
            assured = "yes" if ci % 2 else "no"

            for t, fy in enumerate(fys):
                back = len(fys) - 1 - t  # years before the analysis year
                rev = revenue / (1 + growth) ** back
                factor = 1 / (1 + drift) ** back
                energy, emissions = rev * energy_i * factor, rev * emis_i * factor
                water, waste = rev * water_i * factor, rev * waste_i * factor
                share = max(1.0, renew - renew_step * back)
                canonical = {
                    "revenue_from_operations": round(rev),
                    "energy_total": round(energy),
                    "energy_renewable": round(energy * share / 100),
                    "scope1_emissions": round(emissions * (1 - scope2_share)),
                    "scope2_emissions": round(emissions * scope2_share),
                    "water_consumption": round(water),
                    "water_withdrawal": round(water * rng.uniform(1.1, 1.6)),
                    "waste_generated": round(waste),
                    "waste_recovered": round(waste * recovery / 100),
                }
                boundary, omitted, hit = _apply_defects(
                    symbol, fy, fys[0], canonical, "consolidated"
                )
                planted.extend(d for d in hit if d not in planted)

                for code, unit_canon in canon_unit.items():
                    if code in omitted:
                        continue
                    unit = units[_GROUP[code]]
                    value = _to_reported(Decimal(canonical[code]), unit, unit_canon)
                    rows.append(
                        [
                            name,
                            symbol,
                            sector.name,
                            fy,
                            code,
                            format(value, "f"),
                            unit,
                            boundary,
                            assured,
                            "synthetic://dry-run",
                            "synthetic",
                        ]
                    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return planted
