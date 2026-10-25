"""Hotspots (Pareto of emissions by activity) and the cost link (what each activity costs, in rupees and
in emissions), ref sections 6.6 and 6.7.

The "vital few" are the smallest set of activities, taken from the largest down, that together reach the
threshold share (80%). A hotspot is a priority for attention, not a finding about efficiency.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .engine import Footprint

VITAL_FEW_SHARE = Decimal("0.8")

READING = {
    "both": "Costly and polluting: a clear priority.",
    "emissions": "Polluting but cheap: hard to justify on cost alone.",
    "cost": "Costly but low in emissions: an efficiency candidate.",
    "minor": "Minor on both.",
}


@dataclass(frozen=True)
class HotspotRow:
    rank: int
    position: int  # index in the footprint's results
    name: str
    item_id: str
    data_class: str
    co2e_t: Decimal
    share: Decimal
    cumulative_share: Decimal
    vital_few: bool
    cost_inr: Decimal | None
    cost_share: Decimal | None
    inr_per_tco2e: Decimal | None
    reading: str


def pareto(fp: Footprint, vital_share: Decimal = VITAL_FEW_SHARE) -> list[HotspotRow]:
    total = fp.total_co2e_t
    ordered = sorted(enumerate(fp.results), key=lambda p: (-p[1].co2e_t, p[0]))
    costs = [r.activity.cost_inr for r in fp.results if r.activity.cost_inr is not None]
    cost_total = sum(costs, Decimal(0))
    n = len(fp.results)
    equal = Decimal(1) / n if n else Decimal(0)

    rows: list[HotspotRow] = []
    cumulative = Decimal(0)
    reached = False
    for rank, (position, r) in enumerate(ordered, start=1):
        share = r.co2e_t / total if total else Decimal(0)
        cumulative += share
        in_few = not reached  # the activity that reaches the threshold is the last one included
        if cumulative >= vital_share:
            reached = True
        cost = r.activity.cost_inr
        cost_share = cost / cost_total if cost is not None and cost_total > 0 else None
        per_t = cost / r.co2e_t if cost is not None and r.co2e_t > 0 else None
        reading = ""
        if cost_share is not None:
            hi_e, hi_c = share >= equal, cost_share >= equal
            reading = READING[
                "both" if hi_e and hi_c else "emissions" if hi_e else "cost" if hi_c else "minor"
            ]
        rows.append(
            HotspotRow(
                rank=rank,
                position=position,
                name=r.activity.name,
                item_id=r.activity.item_id,
                data_class=r.activity.data_class,
                co2e_t=r.co2e_t,
                share=share,
                cumulative_share=cumulative,
                vital_few=in_few,
                cost_inr=cost,
                cost_share=cost_share,
                inr_per_tco2e=per_t,
                reading=reading,
            )
        )
    return rows


def cost_complete(fp: Footprint) -> bool:
    """True when every activity has a cost, so the cost shares cover the whole unit."""
    return all(r.activity.cost_inr is not None for r in fp.results)
