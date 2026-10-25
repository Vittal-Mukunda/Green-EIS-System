"""The emission calculator: activity data x NCV x emission factor, in exact ``Decimal`` arithmetic.

For a fuel i (CSTEP's chain, ref section 6.4):

    energy (TJ)  = quantity (kt) x NCV (TJ/kt)
    CO2 (t)      = energy x EF_CO2 (kg/TJ) / 1000       (same for CH4 and N2O)
    CO2e (t)     = CO2 + GWP_CH4 x CH4 + GWP_N2O x N2O

Grid electricity: CO2e (t) = MWh x grid factor (tCO2/MWh). The CEA factor is CO2 only.

Nothing is rounded here and nothing defaults silently: an unknown fuel, an unsupported unit or a missing
density raises ``EngineError``. Where a result leans on an assumption it carries a flag (for example
``assumed_density``); the trust score reads those flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from .factors import ELECTRICITY_ITEM, FactorError, FactorLibrary, default_library

DATA_CLASSES: Final = ("measured", "estimated", "default")
DEFAULT_GRID_ID: Final = "cea_v20_2023_24_avg"

# 100-year global warming potentials as used by CSTEP (AR5). Parameterised on purpose (V-05).
GWP_AR5: Final = {"ch4": Decimal(28), "n2o": Decimal(265)}

_KT_PER_UNIT: Final = {"kg": Decimal("0.000001"), "t": Decimal("0.001"), "kt": Decimal(1)}
_LITRES_PER_UNIT: Final = {"L": Decimal(1), "kL": Decimal(1000)}
_MWH_PER_UNIT: Final = {"kWh": Decimal("0.001"), "MWh": Decimal(1), "GWh": Decimal(1000)}
_TJ_PER_MWH: Final = Decimal("0.0036")  # 3.6 GJ per MWh


class EngineError(ValueError):
    """The input cannot be calculated honestly."""


@dataclass(frozen=True)
class Activity:
    """One line of a unit's monthly data: what was used, how much, and how well it is known."""

    item_id: str  # a fuel id from the factor library, or "grid_electricity"
    quantity: Decimal
    unit: str
    data_class: str = "estimated"
    cost_inr: Decimal | None = None
    label: str = ""  # the unit's own name for it ("Boiler coal")
    equipment: str = ""  # boiler, furnace, kiln, dg_set, ... (used by the recommendation rules)
    grid_id: str = DEFAULT_GRID_ID

    def __post_init__(self) -> None:
        if self.data_class not in DATA_CLASSES:
            raise EngineError(f"data_class {self.data_class!r} is not one of {DATA_CLASSES}")
        if self.quantity < 0:
            raise EngineError(f"{self.name}: quantity is negative")
        if self.cost_inr is not None and self.cost_inr < 0:
            raise EngineError(f"{self.name}: cost is negative")

    @property
    def name(self) -> str:
        return self.label or self.item_id


@dataclass(frozen=True)
class ActivityResult:
    activity: Activity
    energy_tj: Decimal
    co2_t: Decimal
    ch4_t: Decimal
    n2o_t: Decimal
    co2e_t: Decimal
    factor_id: str
    factor_source: str
    factor_status: str
    flags: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class Footprint:
    results: tuple[ActivityResult, ...]

    @property
    def total_co2e_t(self) -> Decimal:
        return sum((r.co2e_t for r in self.results), Decimal(0))

    @property
    def total_energy_tj(self) -> Decimal:
        return sum((r.energy_tj for r in self.results), Decimal(0))

    def shares(self) -> dict[str, Decimal]:
        """Each activity's share of the total, by position in `results` as 'index:name' keys."""
        total = self.total_co2e_t
        if total == 0:
            return {f"{i}:{r.activity.name}": Decimal(0) for i, r in enumerate(self.results)}
        return {f"{i}:{r.activity.name}": r.co2e_t / total for i, r in enumerate(self.results)}


def _fuel_mass_kt(activity: Activity, library: FactorLibrary) -> tuple[Decimal, tuple[str, ...]]:
    fuel = library.fuel(activity.item_id)
    unit = activity.unit
    if unit in _KT_PER_UNIT:
        return activity.quantity * _KT_PER_UNIT[unit], ()
    if unit in _LITRES_PER_UNIT:
        if fuel.density_kg_per_l is None:
            raise EngineError(
                f"{activity.name}: {fuel.name} cannot be entered in {unit}; the library has no "
                "density for it. Enter kg or tonnes."
            )
        kg = activity.quantity * _LITRES_PER_UNIT[unit] * fuel.density_kg_per_l
        flags = ("assumed_density",) if fuel.density_status == "assumed" else ()
        return kg * _KT_PER_UNIT["kg"], flags
    if unit in ("m3", "Nm3", "SCM"):
        raise EngineError(
            f"{activity.name}: volumetric gas is not supported until a volumetric NCV and density "
            "are sourced (V-02). Enter kg or tonnes."
        )
    raise EngineError(f"{activity.name}: unit {unit!r} is not supported for fuels")


def canonical_quantity(
    activity: Activity, library: FactorLibrary | None = None
) -> tuple[Decimal, str]:
    """The activity's quantity in the common unit: kg for a fuel, kWh for electricity. Used to combine
    lines entered in different units (litres and kilograms of the same fuel, say)."""
    library = library or default_library()
    try:
        if activity.item_id == ELECTRICITY_ITEM:
            if activity.unit not in _MWH_PER_UNIT:
                raise EngineError(f"{activity.name}: electricity must be in kWh, MWh or GWh")
            return activity.quantity * _MWH_PER_UNIT[activity.unit] * Decimal(1000), "kWh"
        kt, _ = _fuel_mass_kt(activity, library)
    except FactorError as exc:
        raise EngineError(str(exc)) from exc
    return kt * Decimal(1_000_000), "kg"


def calculate_activity(
    activity: Activity,
    library: FactorLibrary | None = None,
    gwp: dict[str, Decimal] | None = None,
) -> ActivityResult:
    library = library or default_library()
    gwp = gwp or GWP_AR5
    try:
        if activity.item_id == ELECTRICITY_ITEM:
            return _electricity(activity, library)
        return _fuel(activity, library, gwp)
    except FactorError as exc:
        raise EngineError(str(exc)) from exc


def _electricity(activity: Activity, library: FactorLibrary) -> ActivityResult:
    if activity.unit not in _MWH_PER_UNIT:
        raise EngineError(f"{activity.name}: electricity must be in kWh, MWh or GWh")
    grid = library.grid(activity.grid_id)
    mwh = activity.quantity * _MWH_PER_UNIT[activity.unit]
    co2 = mwh * grid.ef_t_co2_per_mwh
    flags = ("factor_not_source_verified",) if grid.status != "source_verified" else ()
    return ActivityResult(
        activity=activity,
        energy_tj=mwh * _TJ_PER_MWH,
        co2_t=co2,
        ch4_t=Decimal(0),
        n2o_t=Decimal(0),
        co2e_t=co2,
        factor_id=grid.id,
        factor_source=grid.source,
        factor_status=grid.status,
        flags=flags,
    )


def _fuel(activity: Activity, library: FactorLibrary, gwp: dict[str, Decimal]) -> ActivityResult:
    fuel = library.fuel(activity.item_id)
    kt, unit_flags = _fuel_mass_kt(activity, library)
    energy = kt * fuel.ncv_tj_per_kt
    thousand = Decimal(1000)
    co2 = energy * fuel.ef_co2_kg_per_tj / thousand
    ch4 = energy * fuel.ef_ch4_kg_per_tj / thousand
    n2o = energy * fuel.ef_n2o_kg_per_tj / thousand
    flags = (*fuel.flags, *unit_flags)
    if fuel.status not in ("source_verified",):
        flags = (*flags, "factor_not_source_verified")
    return ActivityResult(
        activity=activity,
        energy_tj=energy,
        co2_t=co2,
        ch4_t=ch4,
        n2o_t=n2o,
        co2e_t=co2 + gwp["ch4"] * ch4 + gwp["n2o"] * n2o,
        factor_id=fuel.id,
        factor_source=fuel.source,
        factor_status=fuel.status,
        flags=tuple(dict.fromkeys(flags)),
    )


def calculate(
    activities: list[Activity] | tuple[Activity, ...],
    library: FactorLibrary | None = None,
    gwp: dict[str, Decimal] | None = None,
) -> Footprint:
    library = library or default_library()
    return Footprint(tuple(calculate_activity(a, library, gwp) for a in activities))
