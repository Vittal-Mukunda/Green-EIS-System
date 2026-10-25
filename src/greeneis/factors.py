"""The factor library: every emission factor, calorific value and density with its source and year.

Rule: no factor enters the library without a value, a unit (fixed by the column name), a source label
and a year. A factor's `status` says how far it is verified:

- ``source_verified``: read in the primary document named in `source`
- ``derived_reading``: the primary document needs interpretation (for example a misprinted unit)
- ``assumed``: no source; a placeholder that raises a flag wherever it is used
- ``unverified``: taken from a secondary source and not yet checked

Values are kept as ``Decimal`` so calculations are exact and reproducible.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
STATUSES = ("source_verified", "derived_reading", "assumed", "unverified")
PHASES = ("solid", "liquid", "gas")

ELECTRICITY_ITEM = "grid_electricity"


class FactorError(ValueError):
    """A factor is missing, malformed or lacks provenance."""


@dataclass(frozen=True)
class FuelFactor:
    """Emission factors in kg per TJ, NCV in TJ per kt (CSTEP's units, with the kg/TJ reading of ref 4.3)."""

    id: str
    name: str
    phase: str
    ncv_tj_per_kt: Decimal
    ef_co2_kg_per_tj: Decimal
    ef_ch4_kg_per_tj: Decimal
    ef_n2o_kg_per_tj: Decimal
    density_kg_per_l: Decimal | None
    density_status: str
    source: str
    source_year: int
    status: str
    flags: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class GridFactor:
    """Grid electricity factor in tCO2 per MWh (CO2 only)."""

    id: str
    name: str
    ef_t_co2_per_mwh: Decimal
    fiscal_year: str
    boundary: str
    source: str
    source_year: int
    status: str
    note: str


def _decimal(row: dict[str, str], column: str, where: str) -> Decimal:
    raw = (row.get(column) or "").strip()
    if not raw:
        raise FactorError(f"{where}: '{column}' is empty")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise FactorError(f"{where}: '{column}' = {raw!r} is not a number") from exc
    if value < 0:
        raise FactorError(f"{where}: '{column}' is negative")
    return value


def _text(row: dict[str, str], column: str, where: str) -> str:
    raw = (row.get(column) or "").strip()
    if not raw:
        raise FactorError(f"{where}: '{column}' is empty (every factor needs a source and a year)")
    return raw


def _year(row: dict[str, str], where: str) -> int:
    raw = _text(row, "source_year", where)
    if not raw.isdigit() or not 1990 <= int(raw) <= 2100:
        raise FactorError(f"{where}: source_year {raw!r} is not a plausible year")
    return int(raw)


def _status(row: dict[str, str], column: str, where: str) -> str:
    value = _text(row, column, where)
    if value not in STATUSES:
        raise FactorError(f"{where}: {column} {value!r} is not one of {STATUSES}")
    return value


def parse_fuels(rows: list[dict[str, str]]) -> dict[str, FuelFactor]:
    fuels: dict[str, FuelFactor] = {}
    for row in rows:
        fuel_id = _text(row, "id", "fuels.csv")
        where = f"fuels.csv[{fuel_id}]"
        if fuel_id in fuels:
            raise FactorError(f"{where}: duplicate id")
        phase = _text(row, "phase", where)
        if phase not in PHASES:
            raise FactorError(f"{where}: phase {phase!r} is not one of {PHASES}")
        density_raw = (row.get("density_kg_per_l") or "").strip()
        density = _decimal(row, "density_kg_per_l", where) if density_raw else None
        density_status = (row.get("density_status") or "").strip()
        if density is not None:
            density_status = _status(row, "density_status", where)
        fuels[fuel_id] = FuelFactor(
            id=fuel_id,
            name=_text(row, "name", where),
            phase=phase,
            ncv_tj_per_kt=_decimal(row, "ncv_tj_per_kt", where),
            ef_co2_kg_per_tj=_decimal(row, "ef_co2_kg_per_tj", where),
            ef_ch4_kg_per_tj=_decimal(row, "ef_ch4_kg_per_tj", where),
            ef_n2o_kg_per_tj=_decimal(row, "ef_n2o_kg_per_tj", where),
            density_kg_per_l=density,
            density_status=density_status,
            source=_text(row, "source", where),
            source_year=_year(row, where),
            status=_status(row, "status", where),
            flags=tuple(f for f in (row.get("flags") or "").split(";") if f.strip()),
            note=(row.get("note") or "").strip(),
        )
    return fuels


def parse_grids(rows: list[dict[str, str]]) -> dict[str, GridFactor]:
    grids: dict[str, GridFactor] = {}
    for row in rows:
        grid_id = _text(row, "id", "grid.csv")
        where = f"grid.csv[{grid_id}]"
        if grid_id in grids:
            raise FactorError(f"{where}: duplicate id")
        grids[grid_id] = GridFactor(
            id=grid_id,
            name=_text(row, "name", where),
            ef_t_co2_per_mwh=_decimal(row, "ef_t_co2_per_mwh", where),
            fiscal_year=_text(row, "fiscal_year", where),
            boundary=_text(row, "boundary", where),
            source=_text(row, "source", where),
            source_year=_year(row, where),
            status=_status(row, "status", where),
            note=(row.get("note") or "").strip(),
        )
    return grids


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class FactorLibrary:
    """Lookup of fuel and grid factors by id. Unknown ids raise; nothing defaults silently."""

    def __init__(self, fuels: dict[str, FuelFactor], grids: dict[str, GridFactor]):
        self._fuels = fuels
        self._grids = grids

    @classmethod
    def from_directory(cls, directory: Path = DATA_DIR) -> FactorLibrary:
        return cls(
            parse_fuels(_read(directory / "fuels.csv")), parse_grids(_read(directory / "grid.csv"))
        )

    def fuel(self, fuel_id: str) -> FuelFactor:
        try:
            return self._fuels[fuel_id]
        except KeyError:
            known = ", ".join(sorted(self._fuels))
            raise FactorError(f"no factor for fuel {fuel_id!r}; the library has: {known}") from None

    def grid(self, grid_id: str) -> GridFactor:
        try:
            return self._grids[grid_id]
        except KeyError:
            known = ", ".join(sorted(self._grids))
            raise FactorError(f"no grid factor {grid_id!r}; the library has: {known}") from None

    @property
    def fuels(self) -> tuple[FuelFactor, ...]:
        return tuple(self._fuels.values())

    @property
    def grids(self) -> tuple[GridFactor, ...]:
        return tuple(self._grids.values())

    def is_fuel(self, item_id: str) -> bool:
        return item_id in self._fuels


@lru_cache(maxsize=1)
def default_library() -> FactorLibrary:
    return FactorLibrary.from_directory()
