"""What-if scenarios: change a unit's inputs, recompute emissions and cost (ref section 6.8).

Three scenario types cover most small-unit ideas:

- ``ActivityChange``: use y% less of an activity (cut idle running, tune a boiler, fix leaks)
- ``FuelSwitch``: move y% of one fuel's *energy* to another fuel
- ``ElectricityShift``: replace z% of grid electricity by another source (rooftop solar)

Assumptions to state wherever results are shown: cost scales in proportion to quantity for a reduced
activity; a switched-to fuel's cost needs a price from the user; solar capital cost and banking
arrangements are outside this model. Scenarios apply in the order given, so overlapping scenarios are
handled sequentially rather than added.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from .engine import DEFAULT_GRID_ID, ELECTRICITY_ITEM, GWP_AR5, Activity, Footprint, calculate
from .factors import FactorLibrary, default_library

HUNDRED = Decimal(100)
_KG_PER_KT = Decimal(1_000_000)


class ScenarioError(ValueError):
    """The scenario does not make sense for this unit."""


def _find(activities: list[Activity], target: str) -> int:
    matches = [i for i, a in enumerate(activities) if a.name == target]
    if not matches:
        raise ScenarioError(f"no activity named {target!r}")
    if len(matches) > 1:
        raise ScenarioError(
            f"{len(matches)} activities are named {target!r}; give them distinct names"
        )
    return matches[0]


def _check_pct(value: Decimal, what: str) -> None:
    if not Decimal(0) <= value <= HUNDRED:
        raise ScenarioError(f"{what} must be between 0 and 100")


@dataclass(frozen=True)
class ActivityChange:
    target: str  # the activity's name (label, or item id when unlabelled)
    reduction_pct: Decimal

    def title(self) -> str:
        return f"{self.target}: use {self.reduction_pct}% less"


@dataclass(frozen=True)
class FuelSwitch:
    source: str
    share_pct: Decimal  # of the source's energy moved to the new fuel
    to_item_id: str
    to_cost_inr_per_kg: Decimal | None = None  # None: the cost effect is unknown
    to_label: str = ""

    def title(self) -> str:
        return f"{self.source}: move {self.share_pct}% of its energy to {self.to_label or self.to_item_id}"


@dataclass(frozen=True)
class ElectricityShift:
    share_pct: Decimal
    other_ef_t_per_mwh: Decimal = Decimal(0)  # 0 treats the replacement as emission-free
    other_cost_inr_per_kwh: Decimal | None = None  # None: the replacement is treated as free

    def title(self) -> str:
        return f"Replace {self.share_pct}% of grid electricity (e.g. rooftop solar)"


Scenario = ActivityChange | FuelSwitch | ElectricityShift


@dataclass(frozen=True)
class Outcome:
    titles: tuple[str, ...]
    baseline_co2e_t: Decimal
    new_co2e_t: Decimal
    baseline_cost_inr: Decimal | None
    new_cost_inr: Decimal | None

    @property
    def avoided_co2e_t(self) -> Decimal:
        return self.baseline_co2e_t - self.new_co2e_t

    @property
    def pct_of_total(self) -> Decimal:
        if self.baseline_co2e_t == 0:
            return Decimal(0)
        return self.avoided_co2e_t / self.baseline_co2e_t * HUNDRED

    @property
    def cost_saved_inr(self) -> Decimal | None:
        if self.baseline_cost_inr is None or self.new_cost_inr is None:
            return None
        return self.baseline_cost_inr - self.new_cost_inr


def _apply(
    activities: list[Activity], scenario: Scenario, library: FactorLibrary
) -> tuple[list[Activity], Decimal, Decimal | None]:
    """Return the changed activities, any extra emissions (t) and any extra cost (None = unknown)."""
    acts = list(activities)
    if isinstance(scenario, ActivityChange):
        _check_pct(scenario.reduction_pct, "reduction")
        i = _find(acts, scenario.target)
        keep = (HUNDRED - scenario.reduction_pct) / HUNDRED
        a = acts[i]
        acts[i] = replace(
            a,
            quantity=a.quantity * keep,
            cost_inr=None if a.cost_inr is None else a.cost_inr * keep,
        )
        return acts, Decimal(0), Decimal(0)

    if isinstance(scenario, FuelSwitch):
        _check_pct(scenario.share_pct, "share")
        i = _find(acts, scenario.source)
        a = acts[i]
        if not library.is_fuel(a.item_id):
            raise ScenarioError("a fuel switch needs a fuel as its source")
        source_fp = calculate([a], library)
        moved_tj = source_fp.results[0].energy_tj * scenario.share_pct / HUNDRED
        target = library.fuel(scenario.to_item_id)
        moved_kg = moved_tj / target.ncv_tj_per_kt * _KG_PER_KT
        keep = (HUNDRED - scenario.share_pct) / HUNDRED
        acts[i] = replace(
            a,
            quantity=a.quantity * keep,
            cost_inr=None if a.cost_inr is None else a.cost_inr * keep,
        )
        acts.append(
            Activity(
                item_id=scenario.to_item_id,
                quantity=moved_kg,
                unit="kg",
                data_class="estimated",
                cost_inr=None
                if scenario.to_cost_inr_per_kg is None
                else moved_kg * scenario.to_cost_inr_per_kg,
                label=scenario.to_label or target.name,
                equipment=a.equipment,
            )
        )
        extra_cost = Decimal(0) if scenario.to_cost_inr_per_kg is not None else None
        return acts, Decimal(0), extra_cost

    _check_pct(scenario.share_pct, "share")
    grid = [i for i, a in enumerate(acts) if a.item_id == ELECTRICITY_ITEM]
    if len(grid) != 1:
        raise ScenarioError("an electricity shift needs exactly one grid electricity activity")
    i = grid[0]
    a = acts[i]
    keep = (HUNDRED - scenario.share_pct) / HUNDRED
    shifted_kwh = _kwh(a) * scenario.share_pct / HUNDRED
    acts[i] = replace(
        a,
        quantity=a.quantity * keep,
        cost_inr=None if a.cost_inr is None else a.cost_inr * keep,
    )
    extra_t = shifted_kwh / Decimal(1000) * scenario.other_ef_t_per_mwh
    extra_cost = (
        shifted_kwh * scenario.other_cost_inr_per_kwh
        if scenario.other_cost_inr_per_kwh is not None
        else Decimal(0)
    )
    return acts, extra_t, extra_cost


def _kwh(a: Activity) -> Decimal:
    return a.quantity * {"kWh": Decimal(1), "MWh": Decimal(1000), "GWh": Decimal(1_000_000)}[a.unit]


def apply_all(
    activities: list[Activity], scenarios: list[Scenario], library: FactorLibrary | None = None
) -> tuple[list[Activity], Decimal, Decimal | None]:
    """Apply the scenarios in order. Returns the changed activities, the extra emissions (t) from any
    replacement source, and the extra cost (None when it is unknown)."""
    library = library or default_library()
    acts = list(activities)
    extra_t = Decimal(0)
    extra_cost: Decimal | None = Decimal(0)
    for s in scenarios:
        acts, t, c = _apply(acts, s, library)
        extra_t += t
        extra_cost = None if extra_cost is None or c is None else extra_cost + c
    return acts, extra_t, extra_cost


def run(
    activities: list[Activity],
    scenarios: list[Scenario],
    library: FactorLibrary | None = None,
    gwp: dict[str, Decimal] | None = None,
) -> Outcome:
    """Apply the scenarios in order and compare with the baseline."""
    library = library or default_library()
    base = calculate(activities, library, gwp)
    acts, extra_t, extra_cost = apply_all(activities, scenarios, library)
    new = calculate(acts, library, gwp)
    return Outcome(
        titles=tuple(s.title() for s in scenarios),
        baseline_co2e_t=base.total_co2e_t,
        new_co2e_t=new.total_co2e_t + extra_t,
        baseline_cost_inr=_total_cost(base),
        new_cost_inr=None
        if (nc := _total_cost(new)) is None or extra_cost is None
        else nc + extra_cost,
    )


def _total_cost(fp: Footprint) -> Decimal | None:
    costs = [r.activity.cost_inr for r in fp.results]
    if any(c is None for c in costs):
        return None
    return sum((c for c in costs if c is not None), Decimal(0))


def abatement_cost(
    annualised_investment_inr: Decimal, annual_saving_inr: Decimal, annual_tco2e_avoided: Decimal
) -> Decimal:
    """(annualised investment - annual energy saving) / annual tCO2e avoided, in rupees per tCO2e.
    Negative means the measure pays for itself. Needs an investment figure from the user."""
    if annual_tco2e_avoided <= 0:
        raise ScenarioError("no emissions are avoided, so an abatement cost is not defined")
    return (annualised_investment_inr - annual_saving_inr) / annual_tco2e_avoided


_GJ_PER_MWH = Decimal("3.6")


def kg_co2e_per_gj(
    item_id: str, library: FactorLibrary | None = None, gwp: dict[str, Decimal] | None = None
) -> Decimal:
    """Emissions per gigajoule of energy delivered, kg CO2e/GJ: a fuel's three gases weighted by the
    warming potentials, or the average grid factor for electricity (CO2 only, as the source gives it).
    This is energy at the point of use before any equipment efficiency, so it is not a like-for-like
    comparison of routes; `electrification_breakeven` adds the efficiency step."""
    library = library or default_library()
    gwp = gwp or GWP_AR5
    if item_id == ELECTRICITY_ITEM:
        return library.grid(DEFAULT_GRID_ID).ef_t_co2_per_mwh * Decimal(1000) / _GJ_PER_MWH
    f = library.fuel(item_id)
    kg_per_tj = (
        f.ef_co2_kg_per_tj + gwp["ch4"] * f.ef_ch4_kg_per_tj + gwp["n2o"] * f.ef_n2o_kg_per_tj
    )
    return kg_per_tj / Decimal(1000)


def electrification_breakeven(
    fuel_id: str, library: FactorLibrary | None = None, gwp: dict[str, Decimal] | None = None
) -> Decimal:
    """The largest fraction of the fuel's energy that an electric route may use to do the same useful
    work and still not emit more on the current average grid: fuel intensity divided by grid intensity.
    Below this fraction the electric route emits less. It says nothing about cost or capital."""
    return kg_co2e_per_gj(fuel_id, library, gwp) / kg_co2e_per_gj(ELECTRICITY_ITEM, library, gwp)
