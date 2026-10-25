"""A short rule library that maps a hotspot to a few actions, each with the caution to show and its source
(ref Table 6.4). The rules are suggestions drawn from published MSME work, not engineering advice.

Source status: the technology findings come from CSTEP's 2024 MSME decarbonisation work as reported by a
news article (ref S7, secondary); check them against the CSTEP report before quoting (V-13).
"""

from __future__ import annotations

from dataclasses import dataclass

from .engine import ELECTRICITY_ITEM
from .hotspot import HotspotRow

SOLID = ("coal", "lignite")
LIQUID_GAS = ("diesel", "furnace_oil", "lshs", "kerosene", "naphtha", "lpg", "natural_gas")


@dataclass(frozen=True)
class Rule:
    id: str
    items: tuple[str, ...]
    equipment: tuple[str, ...]  # empty: any equipment
    action: str
    caution: str
    sources: str


RULES = (
    Rule(
        "boiler_solid",
        SOLID,
        ("boiler", "thermic_fluid_heater", "thermopac"),
        "Boiler and thermic-fluid heater efficiency upgrades; heat recovery; solar thermal for low- and "
        "medium-temperature process heat.",
        "Efficiency alone may not suffice for deep decarbonisation.",
        "S4, S7",
    ),
    Rule(
        "furnace",
        SOLID + LIQUID_GAS,
        ("furnace",),
        "Furnace efficiency measures; consider an electric resistance furnace; bio-CNG as an "
        "alternative to piped gas.",
        "Depends on the cluster and the electricity tariff.",
        "S7",
    ),
    Rule(
        "kiln",
        SOLID + LIQUID_GAS,
        ("kiln",),
        "Kiln efficiency measures; an electric kiln can cut emissions.",
        "High capital cost may block viability.",
        "S7",
    ),
    Rule(
        "diesel_set",
        ("diesel",),
        ("dg_set", "boiler"),
        "Biodiesel blending; reduce idle running; shift to grid or rooftop solar.",
        "Check blend limits with the equipment supplier.",
        "S7, S4",
    ),
    Rule(
        "clustered_solid_fuel",
        SOLID,
        ("brick_kiln", "pottery_kiln", "jaggery_pan"),
        "Cleaner fuel and common combustion facilities.",
        "Informal and clustered; data are weak.",
        "S3, S1, S2",
    ),
    Rule(
        "electricity",
        (ELECTRICITY_ITEM,),
        (),
        "Efficient drives and HVAC; rooftop or open-access renewable electricity.",
        "Reported cluster-level savings for the top measures were a few percent (for example 4.36% for "
        "pressure die-casting in Bengaluru).",
        "S7, S4",
    ),
)

DATA_ADVICE = (
    "Improve the data for this activity first (weigh deliveries, log running hours, keep invoices): "
    "it is a large share of the total and not measured, so it dominates the uncertainty."
)


@dataclass(frozen=True)
class Recommendation:
    hotspot: str
    rule_id: str
    action: str
    caution: str
    sources: str


def recommend(
    hotspots: list[HotspotRow], equipment: dict[str, str], top: int = 3
) -> list[Recommendation]:
    """Recommendations for the `top` hotspots. `equipment` maps an activity name to its equipment tag
    (the Activity.equipment field); an activity with no tag matches only rules that accept any."""
    out: list[Recommendation] = []
    for h in hotspots[:top]:
        tag = equipment.get(h.name, "")
        for rule in RULES:
            if h.item_id in rule.items and (not rule.equipment or tag in rule.equipment):
                out.append(Recommendation(h.name, rule.id, rule.action, rule.caution, rule.sources))
        if h.data_class != "measured":
            out.append(Recommendation(h.name, "data", DATA_ADVICE, "", "design choice"))
    return out
