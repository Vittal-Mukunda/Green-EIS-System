"""The reference document's worked example, run through the library, to verify arithmetic on the pages.

The example factory (`state.EXAMPLE_ROWS`) is invented: it is not a real unit and nothing on the research
pages is a result computed from it. It is used only in clearly labelled "method check" panels, to show
that the hotspot, cost-link, what-if and report code reproduces the hand calculations in the reference
document (38.97 tCO2e; scenarios 0.82, 1.89, 2.62 and 5.33 tCO2e; tests/test_analysis_modules.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal as D

import state

from greeneis import hotspot, report, whatif
from greeneis.engine import Activity, Footprint, calculate
from greeneis.trust import TrustConfig, band, total_uncertainty, trust_index

LABEL = (
    "Method check on the reference document's invented example factory. These numbers are not a "
    "result and not a real unit; they only show that the code reproduces the hand calculation."
)

SCENARIOS = (
    whatif.ActivityChange("Diesel (generator and vehicle)", D(15)),
    whatif.ActivityChange("Coal (boiler)", D(10)),
    whatif.ElectricityShift(D(20)),
)


@dataclass(frozen=True)
class Example:
    activities: list[Activity]
    footprint: Footprint
    rows: list[hotspot.HotspotRow]
    trust_index: D
    uncertainty: D
    band: str
    scenario_outcomes: list[whatif.Outcome]
    combined: whatif.Outcome
    report_markdown: str


def build() -> Example:
    activities, errors, _ = state.frame_to_activities(state.example_frame())
    if errors:  # the fixture is fixed; a failure here is a bug, not data
        raise RuntimeError("; ".join(errors))
    cfg = TrustConfig()
    fp = calculate(activities)
    index, unc = trust_index(fp, cfg), total_uncertainty(fp, cfg)
    return Example(
        activities=activities,
        footprint=fp,
        rows=hotspot.pareto(fp),
        trust_index=index,
        uncertainty=unc,
        band=band(index, cfg),
        scenario_outcomes=[whatif.run(activities, [s]) for s in SCENARIOS],
        combined=whatif.run(activities, list(SCENARIOS)),
        report_markdown=report.build_report(
            state.EXAMPLE_NAME, state.EXAMPLE_PERIOD, activities, cfg
        ),
    )
