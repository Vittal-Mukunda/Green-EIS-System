"""One-line summaries of each research gap's evidence, computed from the result files.

The Study page ("Evidence available"), the analysis pages (findings) and the Overall Findings table all
call `summary(n)`, so a number is worded and computed once and cannot differ between pages. Nothing is
typed in: each figure is read through `gap_data` or computed from the factor library. When a source file
is missing the summary says so and `available` is False.
"""

from __future__ import annotations

from dataclasses import dataclass

import gap_data
import worked_example

from greeneis import whatif
from greeneis.factors import default_library
from greeneis.study.headline import Headline
from greeneis.validation import compare_cstep

pct = gap_data.pct


@dataclass(frozen=True)
class Summary:
    available: bool
    data_and_method: str
    key_finding: str
    short: str
    supporting: str
    limitation: str


def _names(items: list[str]) -> str:
    return (
        ", ".join(items[:-1]) + f" and {items[-1]}"
        if len(items) > 1
        else (items[0] if items else "")
    )


def cstep_agreement() -> tuple[int, int]:
    """(cells that disagree, cells compared) in the recomputation of CSTEP Table 8."""
    cells = compare_cstep()
    return sum(not c.matches for c in cells), len(cells)


def library_counts() -> dict[str, int]:
    lib = default_library()
    return {
        "fuels": len(lib.fuels),
        "fuels_verified": sum(f.status == "source_verified" for f in lib.fuels),
        "grids": len(lib.grids),
        "grids_verified": sum(g.status == "source_verified" for g in lib.grids),
    }


def _missing(what: str) -> Summary:
    return Summary(
        False, what, "Not available: the result file is missing.", "Not available", "", ""
    )


def gap_1() -> Summary:
    ev, head = gap_data.evidence(), gap_data.result(gap_data.MAIN_FILE)
    method = (
        "ASI 2023-24 unit-level file, open factories with at most 50 persons: counts of what each "
        "reports, then spend divided by a typical state price compared with the reported quantity."
    )
    if ev is None or head is None:
        return _missing(method)
    cov = ev["coverage"]
    lines = [n.lower() for n, c in cov["no_quantity_lines"].items() if c]
    return Summary(
        True,
        method,
        f"{cov['usable_quantity']:,} of {cov['small_factories']:,} small factories "
        f"({pct(cov['usable_quantity'] / cov['small_factories'])}) report a usable fuel quantity; "
        f"{cov['spend_without_quantity_any_line']:,} "
        f"({pct(cov['spend_without_quantity_any_line'] / cov['small_factories'])}) also report spend on "
        f"{_names(lines)} with no quantity. Where a quantity can be worked out from a bill, the median "
        f"error is {pct(head.estimated_median)} against {pct(head.default_median)} for a sector-average "
        "guess.",
        f"{pct(cov['usable_quantity'] / cov['small_factories'])} of small factories report a usable fuel "
        f"quantity; bill-based estimate off by {pct(head.estimated_median)} (median) against "
        f"{pct(head.default_median)} for a sector-average guess",
        "Gap 1 page: reporting coverage table and proxy-error chart.",
        "ASI covers registered factories and reported, not metered, quantities; no informal-unit data.",
    )


def gap_2() -> Summary:
    head = gap_data.result(gap_data.MAIN_FILE)
    method = (
        "Hypotheses H1 to H3 on ASI 2023-24 (cluster bootstrap by state, Holm correction), plus "
        "recomputation of CSTEP Table 8 from its own factors."
    )
    if head is None:
        return _missing(method)
    off, total = cstep_agreement()
    return Summary(
        True,
        method,
        f"Estimated numbers: median error {pct(head.estimated_median)}; Default: "
        f"{pct(head.default_median)}. The assumed Default range of plus or minus "
        f"{pct(head.placeholder_default)} was too narrow: nine in ten Default errors were within "
        f"{pct(head.default_q90)}, and the nominal 90% interval covered the reported quantity for "
        f"{pct(head.coverage)} of factories. {off} of {total} recomputed CSTEP cells disagree with "
        "CSTEP's own factors.",
        f"Estimated {pct(head.estimated_median)} against Default {pct(head.default_median)} median error; "
        f"assumed Default range plus or minus {pct(head.placeholder_default)}, 90th percentile error "
        f"{pct(head.default_q90)}",
        "Gap 2 page: proxy-error, range, coverage and CSTEP recomputation charts.",
        "Pooled figures are mostly electricity, and the labels' link to error is largely structural.",
    )


def gap_3() -> Summary:
    head = gap_data.result(gap_data.MAIN_FILE)
    method = (
        "H4 and H5 on ASI small factories with two or more tracked fuels, plus the share and lead of "
        "each factory's top source."
    )
    if head is None:
        return _missing(method)
    thin = (
        f" and {pct(head.top1_thin_lead)} when its lead was under "
        f"{(head.thin_lead_below or 0.1) * 100:.0f} points"
        if head.top1_thin_lead is not None
        else ""
    )
    return Summary(
        True,
        method,
        f"Under bills-only records the biggest source stayed the biggest for {pct(head.top1_kept)} of "
        f"{head.rows_by_test['H4']:,} factories with more than one fuel{thin}. 'Fix the biggest first' "
        f"rests on only {head.h5_rows} factories.",
        f"Top source kept for {pct(head.top1_kept)} of {head.rows_by_test['H4']:,} multi-fuel factories; "
        f"priority rule rests on {head.h5_rows} factories",
        "Gap 3 page: hotspot stability, priority-rule and top-source charts.",
        "A factory here has at most three sources; the priority-rule test is small and cannot be run "
        "for textiles.",
    )


def _cost_short(ev: dict) -> str:
    """The fuel whose share of emissions most exceeds its share of spend, in one clause."""
    cl = ev["cost_link"]
    top = max(cl, key=lambda r: r["co2e_share"] - r["spend_share"])
    h = ev["hotspots"]
    name = gap_data.FUEL_NAMES.get(top["item"], top["item"])
    return (
        f"{name}: {pct(top['spend_share'])} of spend, {pct(top['co2e_share'])} of emissions; biggest "
        f"cost item is not the biggest emitter in {pct(h['biggest_cost_not_biggest_emitter'] / h['multi_fuel_factories'])} "
        "of multi-fuel factories"
    )


def gap_4() -> Summary:
    ev = gap_data.evidence()
    method = (
        "Per fuel: reported spend against calculated emissions (engine and factor library) over all "
        "ASI small factories; per factory: whether the biggest rupee item is the biggest emitter."
    )
    if ev is None:
        return _missing(method)
    parts = [
        f"{gap_data.FUEL_NAMES.get(r['item'], r['item'])} {pct(r['spend_share'])} of spend and "
        f"{pct(r['co2e_share'])} of emissions"
        for r in ev["cost_link"]
    ]
    h = ev["hotspots"]
    return Summary(
        True,
        method,
        "; ".join(parts) + f". In {h['biggest_cost_not_biggest_emitter']:,} of "
        f"{h['multi_fuel_factories']:,} factories with more than one fuel "
        f"({pct(h['biggest_cost_not_biggest_emitter'] / h['multi_fuel_factories'])}) the biggest rupee "
        "item is not the biggest emitter.",
        _cost_short(ev),
        "Gap 4 page: spend-versus-emissions chart and rupees-per-tonne table.",
        "Spend is as reported in the return; only electricity, coal and gas have both a quantity and a "
        "value; price volatility is not analysed.",
    )


def gap_5() -> Summary:
    method = (
        "Arithmetic on the published factors: emissions per gigajoule for each fuel and the share of "
        "a fuel's energy an electric route may use before it emits more. No unit-level data."
    )
    coal = whatif.electrification_breakeven("coal")
    lpg = whatif.electrification_breakeven("lpg")
    return Summary(
        True,
        method,
        f"On the FY 2023-24 average grid, an electric route doing the same useful work as coal must "
        f"use under {pct(float(coal))} of coal's energy to emit less (LPG: {pct(float(lpg))}). This is "
        "factor arithmetic, not a measured saving: no audited before-and-after data exist here.",
        f"Electric route must use under {pct(float(coal))} of coal's energy to emit less; no measured "
        "savings available",
        "Gap 5 page: intensity table and break-even chart.",
        "No audited savings to test against; the simulator is verified by hand calculation only.",
    )


def gap_6() -> Summary:
    c = library_counts()
    method = (
        "Inspection of the factor library: value, unit, source and year per factor, and its status."
    )
    return Summary(
        True,
        method,
        f"The library holds {c['fuels']} fuel factors ({c['fuels_verified']} verified in the source "
        f"document) and {c['grids']} grid factors ({c['grids_verified']} verified), each with value, "
        "unit, source and year. No other SME tool was reviewed, so the claim that existing tools are "
        "lacking is untested.",
        f"{c['fuels']} fuel and {c['grids']} grid factors with sources; no other tool reviewed",
        "Gap 6 page: factor library table.",
        "No feature review of any tool and no user test; several cited sources lack authors or year.",
    )


def gap_7() -> Summary:
    method = (
        "Inspection of the generated one-page report (reference example) for its fixed statements."
    )
    text = worked_example.build().report_markdown.lower()
    has = {"does not certify": "does not certify" in text, "method note": "indicative" in text}
    ok = all(has.values())
    return Summary(
        True,
        method,
        "Not evaluated: no buyer or lender has reviewed a report. The generated report "
        + (
            "carries its standing statement that it is an estimate and does not certify."
            if ok
            else "is missing a standing statement (check report.py)."
        ),
        "Not evaluated: no buyer or lender has reviewed a report",
        "Gap 7 page: report structure and fixed statements.",
        "Whether buyers or lenders accept such a report is untested.",
    )


# The research question in one line, for the matrix (the full question is on each gap's page).
QUESTION_SHORT = {
    1: "How much of an energy bill can be turned into a fuel quantity, and how close is it?",
    2: "Do the labels predict error, and are the assumed ranges the right size?",
    3: "Does the biggest source stay biggest, and does fixing it first help most?",
    4: "Do the costliest activities also emit most, and what does a tonne cost?",
    5: "Can a manager see the effect of a change without an audit?",
    6: "What does GreenEIS offer that existing tools are said to lack?",
    7: "Does the one-page report give a buyer or lender what it needs?",
}

# A few words on the data and method of each gap, for the one-row-per-gap matrix (no numbers).
DATA_SHORT = {
    1: "ASI 2023-24 small factories: counts of what is reported; spend / typical price against reported quantity",
    2: "ASI 2023-24: hypotheses H1 to H3 (cluster bootstrap, Holm); recomputation of CSTEP Table 8",
    3: "ASI 2023-24 factories with 2+ fuels: H4, H5; share and lead of the top source",
    4: "ASI 2023-24: reported spend against calculated emissions per fuel; biggest cost item against biggest emitter",
    5: "Published factors: emissions per GJ and electrification break-even; no unit data",
    6: "Inspection of the factor library; no tool review",
    7: "Check of the generated report on the invented example; no buyer review",
}

# Where each gap's evidence comes from, for the traceability table (no numbers).
TRACE = {
    1: (
        "ASI 2023-24; quantity, value, persons, state, industry code",
        "Case table; counts by fuel line; spend / state price against reported quantity",
        "study_asi_2023-24.json; gap_evidence_asi_2023-24.json",
    ),
    2: (
        "ASI 2023-24; published national estimates; CSTEP Tables 7 and 8",
        "H1 to H3 (cluster bootstrap, Holm); recomputation of 56 cells",
        "study_asi_2023-24.json (and sensitivity and textile files); national.csv; validation.py",
    ),
    3: (
        "ASI 2023-24; calculated emissions of electricity, coal, gas",
        "H4 and H5; share and lead of the top source",
        "study_asi_2023-24.json; gap_evidence_asi_2023-24.json",
    ),
    4: (
        "ASI 2023-24; purchase value and calculated emissions per fuel line",
        "Spend and emission shares; INR per tCO2e; cost item against emitter",
        "gap_evidence_asi_2023-24.json",
    ),
    5: (
        "Factor library (CSTEP 2018; CEA v20.0); rule library",
        "Intensity per GJ; electrification break-even; hand-checked scenarios",
        "whatif.py; recommend.py (no result file)",
    ),
    6: (
        "Factor library; sources named in the literature",
        "Inspection of what the library holds; no tool review",
        "factors.py; data/fuels.csv; data/grid.csv (no result file)",
    ),
    7: (
        "Report generator output for the reference example",
        "Check of the report's standing statements; no buyer review",
        "report.py (no result file)",
    ),
}

_BUILDERS = {1: gap_1, 2: gap_2, 3: gap_3, 4: gap_4, 5: gap_5, 6: gap_6, 7: gap_7}


def summary(number: int) -> Summary:
    return _BUILDERS[number]()


def main_headline() -> Headline | None:
    return gap_data.result(gap_data.MAIN_FILE)
