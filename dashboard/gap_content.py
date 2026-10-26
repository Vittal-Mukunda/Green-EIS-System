"""What each analysis page shows that is specific to its research gap.

`pages_gap` gives every analysis page the same eight parts (A to H). The parts that depend on the research
question are written here, one set per gap: the data and scope (C), the method (D), the real-data results
(E) and the findings (F). Every number is read through `gap_data` / `findings` or computed from the factor
library; where a source file is missing the section says so. Nothing here substitutes invented data for a
result that cannot be computed: gaps whose question the available data cannot answer say that, and name
the data that would be needed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import findings
import gap_data
import plotly.graph_objects as go
import sections
import streamlit as st
import worked_example
from components.alerts import callout
from components.charts import SERIES, show
from components.citations import cite, note_html
from components.data_table import Column, Html, table_html
from components.empty_state import empty_state
from components.kpi_card import stat_strip
from components.markup import esc, render, section
from components.plain import in_plain_words, pct
from components.status_badge import badge
from pages_reference import (
    calculation_formulas,
    fuel_factor_table,
    grid_factor_table,
    trust_class_table,
)
from pages_study import PLAIN as HYPOTHESIS_PLAIN
from pages_study import VERDICT_TONE

from greeneis import gaps, hotspot, references, whatif
from greeneis.factors import default_library
from greeneis.recommend import RULES
from greeneis.study.headline import Headline

ESTIMATED_COLOUR, DEFAULT_COLOUR = sections.ESTIMATED_COLOUR, sections.DEFAULT_COLOUR
PERIOD = "ASI 2023-24 (the survey year ending March 2024), open factories with at most 50 persons"


@dataclass(frozen=True)
class Findings:
    """The six things the findings part must say (specification, part F)."""

    shows: str
    numbers: str
    comparisons: str
    answerable: str
    relation: str
    cannot: str


@dataclass(frozen=True)
class Content:
    scope: Callable[[], None]
    method: Callable[[], None]
    results: Callable[[], None]
    findings: Callable[[], Findings]


# ---- helpers ------------------------------------------------------------------------------------
def _main() -> Headline | None:
    return gap_data.result(gap_data.MAIN_FILE)


def _missing(name: str = gap_data.MAIN_FILE) -> None:
    empty_state(
        "The real results file is not available",
        f"Expected outputs/{name}. Regenerate it with the commands under Limitations and reproducibility.",
        "science",
    )


def _unavailable(why: str, needed: str) -> None:
    callout("warn", "This cannot be analysed with the data in hand.", f"{why} Needed: {needed}")


def _funnel(log: dict) -> None:
    steps = [
        ("Factories in the ASI 2023-24 file", log["factories in file"]),
        ("Open (status 1)", log["open factories"]),
        ("With persons recorded", log["open with persons recorded"]),
        ("At most 50 persons (small)", log["small (persons <= max_employees)"]),
        (
            "Usable industry code",
            log["small (persons <= max_employees)"] - log["dropped: industry code unusable"],
        ),
        ("With at least one usable fuel line", log["factories with at least one item"]),
    ]
    rows, previous = [], None
    for name, n in steps:
        rows.append([name, f"{n:,}", "" if previous is None else f"{previous - n:,}"])
        previous = n
    render(
        table_html(
            [
                Column("Step"),
                Column("Factories left", numeric=True),
                Column("Left out here", numeric=True),
            ],
            rows,
        )
    )


def _hypothesis_table(ids: tuple[str, ...]) -> None:
    data = gap_data.raw(gap_data.MAIN_FILE)
    if data is None:
        _missing()
        return
    rows = []
    for h in ids:
        t = data["tests"][h]
        p = t["adjusted_p"]
        rows.append(
            [
                h,
                HYPOTHESIS_PLAIN.get(h, t["statement"]),
                Html(badge(t["verdict"].capitalize(), VERDICT_TONE.get(t["verdict"], ""))),
                f"{p:.3f}" if p is not None else None,
                f"{t['n_rows']:,}",
                f"{t['n_clusters']:,}",
            ]
        )
    render(
        table_html(
            [
                Column("H"),
                Column("In plain words"),
                Column("Verdict"),
                Column("Adjusted p", numeric=True, note="Holm"),
                Column("Rows", numeric=True),
                Column("Clusters", numeric=True, note="states"),
            ],
            rows,
        )
    )
    st.caption(
        "'Supported' means the pre-specified condition for proving the hypothesis wrong was rejected, "
        "not that the claim is established. 0.005 is the smallest adjusted p that 1,000 bootstrap draws "
        "can give. Compare the Rows column: a verdict that rests on few rows is weak."
    )


def _sensitivity_table() -> None:
    runs = [
        ("Main run: gas read as LPG, up to 50 persons", gap_data.MAIN_FILE),
        ("Declared sensitivity: gas read as natural gas", gap_data.SENS_NATGAS_FILE),
        ("Declared sensitivity: up to 100 persons", gap_data.SENS_100_FILE),
    ]
    rows = []
    for label, name in runs:
        head = gap_data.result(name)
        if head is None:
            continue
        rows.append(
            [label, f"{head.factories:,}"]
            + [
                Html(badge(head.verdicts[h].capitalize(), VERDICT_TONE.get(head.verdicts[h], "")))
                for h in ("H1", "H2", "H3", "H4", "H5")
            ]
        )
    if rows:
        render(
            table_html(
                [Column("Run"), Column("Factories", numeric=True)]
                + [Column(h) for h in ("H1", "H2", "H3", "H4", "H5")],
                rows,
            )
        )
        st.caption(
            "Only these two sensitivity runs and the textile cut were declared in advance "
            "(docs/RESEARCH_DESIGN.md section 10); no other variation was tried."
        )


def _method_check_note() -> None:
    callout("info", "Method check, not a result.", worked_example.LABEL)


# =========================================================================================
# Gap 1
# =========================================================================================
def scope_1() -> None:
    main, ev = gap_data.raw(gap_data.MAIN_FILE), gap_data.evidence()
    if main is None or ev is None:
        _missing()
        return
    log, cov = main["provenance"]["data_log"], ev["coverage"]
    stat_strip(
        [
            (
                "Factories analysed",
                f"{log['factories with at least one item']:,}",
                "with a usable fuel line",
            ),
            ("Small factories", f"{cov['small_factories']:,}", "open, at most 50 persons"),
            ("States", f"{log['clusters (states)']}", "price groups and bootstrap clusters"),
            ("Reporting year", "2023-24", "one year only"),
        ]
    )
    st.markdown(
        "**Sources.** ASI 2023-24 unit-level file (MoSPI), read with the layout document. "
        "**Units of analysis.** Factories (anonymous returns), not companies; no company or sector "
        "report is used on this page. **Variables.** Quantity, purchase value and rate for the fixed "
        "fuel lines, number of persons, state, industry code."
    )
    section("From the file to the analysis", "Everything left out is counted")
    _funnel(log)
    section("Which fuel lines carry a quantity", "Counted over the small factories")
    lines = [
        ("Electricity purchased and consumed", "kWh", log["records: grid_electricity"], True),
        ("Coal consumed", "tonnes", log["records: coal"], True),
        ("Gas consumed (read as LPG)", "kg", log["records: lpg"], True),
    ] + [(n, "none", c, False) for n, c in cov["no_quantity_lines"].items()]
    render(
        table_html(
            [
                Column("Fixed line in the return"),
                Column("Quantity unit"),
                Column("Factories reporting a value", numeric=True),
                Column("Usable as a quantity"),
            ],
            [
                [
                    name,
                    unit,
                    f"{n:,}",
                    Html(badge("Yes", "ok") if usable else badge("No: value only", "warn")),
                ]
                for name, unit, n, usable in lines
            ],
        )
    )
    with st.expander("Assumptions and data-quality concerns"):
        st.markdown(
            "- Gas is read as LPG (the schedule does not say); reading it as natural gas changed no verdict.\n"
            "- At most 50 persons is a placeholder limit; 100 persons was run as a declared sensitivity.\n"
            "- The survey multiplier is ignored: figures describe the factories in the file, not the "
            "population.\n"
            "- The reported rate always equals value divided by quantity, so a price taken from other "
            "factories is independent of this factory's own entry but not of the survey's.\n"
            "- Quantities are what the factory reported. They are not metered, so reporting slips are in "
            "the reference."
        )


def method_1() -> None:
    st.markdown(
        "1. Select open factories with at most 50 persons and a usable industry code.\n"
        "2. For each fixed fuel line with both a quantity and a value, form the case: item, reported "
        "quantity, purchase value, persons, sector, state.\n"
        "3. Count how many small factories report each line, and how many report spend on lines that carry "
        "no quantity.\n"
        "4. Work each quantity out the way a unit without meters would: **Estimated** from the bill, "
        "**Default** from a sector average.\n"
        "5. Compare each with the reported quantity and summarise the absolute relative error by fuel."
    )
    st.latex(
        r"\varepsilon_i=\frac{|\tilde x_i-x_i|}{x_i},\qquad "
        r"\tilde x_i^{\text{Est}}=\frac{V_i}{\bar p_{s}},\qquad "
        r"\tilde x_i^{\text{Def}}=\bar q_{\text{sector}}\times n_i"
    )
    st.caption(
        "x is the reported quantity, V the purchase value, the bar-p the median price of the same fuel "
        "in the same state computed from other factories only (at least four), the bar-q the sector's median "
        "quantity per person and n the factory's persons. In simple words: a bill divided by a typical "
        "price, against a guess from how many people work there."
    )


def results_1() -> None:
    ev, head = gap_data.evidence(), _main()
    if ev is None or head is None:
        _missing()
        return
    main = gap_data.raw(gap_data.MAIN_FILE)
    log, cov = main["provenance"]["data_log"], ev["coverage"]
    section("Which fuel lines carry a quantity?", f"Small factories reporting each line, {PERIOD}")
    names = ["Electricity (quantity)", "Coal (quantity)", "Gas, read as LPG (quantity)"] + [
        f"{n} (spend only)" for n in cov["no_quantity_lines"]
    ]
    counts = [log["records: grid_electricity"], log["records: coal"], log["records: lpg"]] + list(
        cov["no_quantity_lines"].values()
    )
    colours = [ESTIMATED_COLOUR] * 3 + [DEFAULT_COLOUR] * len(cov["no_quantity_lines"])
    fig = go.Figure(
        go.Bar(
            y=names,
            x=counts,
            orientation="h",
            marker_color=colours,
            text=[f"{c:,}" for c in counts],
            textposition="outside",
        )
    )
    fig.update_layout(
        xaxis_title="Small factories reporting the line (count, ASI 2023-24)",
        height=340,
        showlegend=False,
        margin={"l": 240, "b": 60, "r": 60},
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(range=[0, max(counts) * 1.15])
    show(fig)
    both = cov["usable_and_spend_without_quantity"]
    in_plain_words(
        f"Almost every small factory reports electricity with a quantity. But "
        f"{cov['spend_without_quantity_any_line']:,} of the {cov['small_factories']:,} also report money "
        "spent on petrol, diesel and oil or on other fuel with no quantity attached, so those fuels cannot "
        "be turned into a quantity from the return at all.",
        "Dark blue bars are lines with a quantity; amber bars carry a rupee value only.",
    )
    section("What a factory reports", "Every small factory falls in exactly one row")
    rows = [
        ("A usable quantity only", cov["usable_quantity"] - both),
        ("A usable quantity and spend on a line with no quantity", both),
        ("Spend on a line with no quantity only", cov["spend_without_quantity_only"]),
        ("Neither", cov["neither"]),
    ]
    render(
        table_html(
            [Column("Reports"), Column("Factories", numeric=True), Column("Share", numeric=True)],
            [[n, f"{c:,}", pct(c / cov["small_factories"], 1)] for n, c in rows],
        )
    )
    st.caption(f"The four rows add up to {sum(c for _, c in rows):,}, the small factories counted.")
    section("Can a quantity be recovered from the bill?", "Where a quantity does exist")
    sections.trust_proxy_error(head)


def findings_1() -> Findings:
    ev, head = gap_data.evidence(), _main()
    if ev is None or head is None:
        return Findings(*(("Not available: the result file is missing.",) * 6))
    cov = ev["coverage"]
    fuels = {f.name: f for f in head.fuels}
    per_fuel = "; ".join(
        f"{n}: Estimated {pct(f.estimated_median)}, Default {pct(f.default_median)}"
        for n, f in fuels.items()
    )
    return Findings(
        shows=(
            f"{cov['usable_quantity']:,} of {cov['small_factories']:,} small factories report a "
            "usable quantity for electricity, coal or gas, and "
            f"{cov['spend_without_quantity_any_line']:,} report spend on a fuel line that has no "
            "quantity. A quantity worked out from a bill is close to the reported one for electricity "
            "and less close for coal and LPG; a sector-average guess is far off for all three."
        ),
        numbers=f"Median error by fuel: {per_fuel}.",
        comparisons=(
            "Estimated against Default, fuel by fuel. The overall median "
            f"({pct(head.estimated_median)} against {pct(head.default_median)}) mostly describes "
            "electricity, which makes up most of the records."
        ),
        answerable=(
            "Partly. For electricity, coal and LPG in registered factories, yes. For diesel, furnace "
            "oil and other fuels, no: the return holds no quantity. For informal units, not at all."
        ),
        relation=(
            f"{cite('cstep2018')} say industry-wise fuel data are missing for petroleum products and "
            "for part of coal. The ASI returns show the same pattern one level down: the fuel lines "
            "that carry only a value are petroleum lines. This is consistent with their statement; it "
            f"does not test their national totals. {cite('ceew2018')} ask for validated data; the "
            "reported quantities used here are not validated either."
        ),
        cannot=(
            "It cannot show what informal units record, whether monthly entry is workable for them, or "
            "how well bill-based estimates perform for liquid fuels."
        ),
    )


# =========================================================================================
# Gap 2
# =========================================================================================
def scope_2() -> None:
    head, main = _main(), gap_data.raw(gap_data.MAIN_FILE)
    if head is None or main is None:
        _missing()
        return
    off, total = findings.cstep_agreement()
    stat_strip(
        [
            ("Factories tested", f"{head.factories:,}", f"{head.records:,} fuel records"),
            ("States", f"{head.states}", "bootstrap clusters"),
            ("Hypotheses", "H1 to H3", "of five; H4 and H5 are on the Gap 3 page"),
            ("CSTEP cells recomputed", f"{total}", f"{off} disagree with CSTEP's own factors"),
        ]
    )
    st.markdown(
        "**Sources.** ASI 2023-24 for the error of the labels; two published national estimates "
        "(CSTEP 2018, CEEW 2018, reporting year 2015-16) and CSTEP's petroleum tables (2008-09 to "
        "2015-16) for the conflict between studies. **Units.** Factories (anonymous returns); no "
        "company reports are involved."
    )
    data_log = main["provenance"]["data_log"]
    st.caption(
        f"Left out: {data_log['dropped: industry code unusable']} factories for an unusable industry code, "
        f"{data_log['dropped: unit code not convertible']} records for an unconvertible unit; per profile, "
        + "; ".join(f"{k}: {v}" for k, v in main["descriptives"]["excluded"].items())
        + " (units for which a proxy could not be formed, e.g. no other factory in the state)."
    )
    with st.expander("Assumptions and data-quality concerns"):
        st.markdown(
            "- The scores (1.0, 0.6, 0.3) and ranges (5%, 25%, 50%) are **uncalibrated design choices**; "
            "the study tests them, it does not tune them.\n"
            "- The nominal range is read as a 90% interval for H2; that reading is not confirmed (V-25).\n"
            "- The record-keeping profiles are our assumptions about what a unit keeps, not observed "
            "behaviour (V-27).\n"
            "- Thresholds and proxies were fixed before the first real-data run and have not changed."
        )


def method_2() -> None:
    st.markdown(
        "**Trust index and uncertainty.** Each number is Measured, Estimated or Default and has a score s "
        "and an indicative range u. The footprint's index is an emissions-weighted average of the "
        "scores; its range is the root-sum-square of the weighted ranges."
    )
    st.latex(
        r"T=\frac{\sum_i E_i s_i}{\sum_i E_i}\qquad U=\frac{\sqrt{\sum_i (E_i u_i)^2}}{\sum_i E_i}"
    )
    trust_class_table()
    st.caption(
        "Root-sum-square assumes independent errors, which is optimistic when one price feeds several "
        "inputs (V-12). In simple words: the index is how much of the footprint rests on good numbers."
    )
    st.markdown(
        "**Tests.** H1 compares the error of Default and Estimated numbers (paired Wilcoxon, cluster "
        "bootstrap by state). H2 compares the 90th-percentile error of each class with its assumed "
        "range and the coverage of the nominal interval with the 80-95% band. H3 asks whether the index "
        "is negatively correlated with the error of the total (Spearman), pooled and within the "
        f"random-mix profile. Cluster bootstrap after {cite('efron1979')}; Holm correction across the five "
        f"hypotheses after {cite('holm1979')}."
    )
    render(
        note_html(
            "The data-quality-indicator idea behind the index follows "
            f"{cite('weidema1996')}, {cite('kuo2015')} and {cite('ghgp_uncertainty')}; those sources "
            "supply the idea, not the values used."
        )
    )
    st.markdown(
        "**CSTEP recomputation.** Each published emission figure for a petroleum fuel and year is "
        "recomputed from CSTEP's own consumption table and factors with the same arithmetic; a cell "
        "agrees when within 1% (or one unit of the last printed decimal). Disagreements are flagged, "
        "never corrected."
    )
    calculation_formulas()


def results_2() -> None:
    head = _main()
    section("The two national estimates", "Published figures, 2015-16")
    sections.national_totals()
    sections.brick_coal()
    sections.cstep_recompute()
    if head is None:
        _missing()
        return
    section("Hypotheses H1 to H3", f"Test of the labels, {PERIOD}")
    _hypothesis_table(("H1", "H2", "H3"))
    sections.trust_proxy_error(head)
    sections.trust_ranges(head)
    sections.trust_coverage(head)
    sections.trust_label(head)
    section("Does it hold when the settings change?", "Only the declared variations")
    _sensitivity_table()
    sections.placeholder_warning(head)


def findings_2() -> Findings:
    head = _main()
    if head is None:
        return Findings(*(("Not available: the result file is missing.",) * 6))
    off, total = findings.cstep_agreement()
    worst = max(head.fuels, key=lambda f: f.estimated_q90)
    return Findings(
        shows=(
            "Numbers worked out from a bill are much closer to the reported quantity than "
            "sector-average guesses, so the label orders error in the expected direction. But the "
            "ranges first assumed are wrong: too narrow for Default numbers, and too narrow for "
            f"{worst.name} even when Estimated."
        ),
        numbers=(
            f"Median error {pct(head.estimated_median)} (Estimated) against {pct(head.default_median)} "
            f"(Default). Default 90th percentile {pct(head.default_q90)} against an assumed "
            f"{pct(head.placeholder_default)}; {worst.name} Estimated 90th percentile "
            f"{pct(worst.estimated_q90)} against {pct(head.placeholder_estimated)}. Nominal 90% interval "
            f"covered {pct(head.coverage)} of factories. Index-error correlation {head.spearman_pooled:.2f} "
            f"pooled and {head.spearman_within_random_mix:.2f} within the mixed profile. "
            f"{off} of {total} CSTEP cells disagree with CSTEP's own factors."
        ),
        comparisons=(
            "Estimated against Default per fuel; the 90th-percentile error against the assumed range; "
            "the index against a naive predictor (share of emissions that is Default, "
            f"{head.naive_default_share_rho:.2f})."
        ),
        answerable=(
            "Partly. The question whether the labels predict error is answered for these factories and "
            "these proxies; the question whether the assumed ranges are right is answered no. A "
            "calibrated range per fuel, tested on a held-out year, is not yet available."
        ),
        relation=(
            f"{cite('ceew2018')} showed that its own estimate was far below other studies for brick-kiln "
            "coal and traced part of the gap to under-counted workers. This page does not resolve that "
            f"conflict. It addresses the other half of the gap, the reliability of individual figures, "
            f"and it finds that {cite('cstep2018')}'s petroleum table disagrees with its own factors in "
            f"{off} of {total} cells, for reasons unknown."
        ),
        cannot=(
            "It cannot show that the labels work for real owners (the profiles are our assumptions), "
            "cannot separate reporting slips from proxy error (the reference is reported, not "
            "metered), and cannot explain why CSTEP's cells disagree. 'Supported' is not 'established'."
        ),
    )


# =========================================================================================
# Gap 3
# =========================================================================================
def scope_3() -> None:
    head, ev = _main(), gap_data.evidence()
    if head is None or ev is None:
        _missing()
        return
    h = ev["hotspots"]
    stat_strip(
        [
            ("Factories with a fuel", f"{h['factories_with_a_fuel']:,}", "small, ASI 2023-24"),
            (
                "With two or more fuels",
                f"{h['multi_fuel_factories']:,}",
                "only these can be ranked",
            ),
            ("With one fuel", f"{h['single_fuel_factories']:,}", "nothing to rank"),
            (
                "Tests",
                "H4, H5",
                f"{head.rows_by_test['H4']:,} and {head.rows_by_test['H5']:,} rows",
            ),
        ]
    )
    st.markdown(
        "**Sources.** The same ASI 2023-24 case table as Gaps 1 and 2. **Variables.** Calculated "
        "emissions of electricity, coal and gas per factory. A factory has at most three sources, "
        "so every ranking here has at most three entries."
    )
    with st.expander("Assumptions and data-quality concerns"):
        st.markdown(
            f"- Thin lead means the top source leads the second by less than "
            f"{(head.thin_lead_below or 0.10) * 100:.0f} percentage points (placeholder, V-26).\n"
            "- H4 uses the bills-only profile: electricity Measured, fuels worked out from spend.\n"
            "- H5 needs two non-measured inputs, which bills-only rarely gives, so it rests on few factories (V-32).\n"
            "- Liquid fuels are absent from ASI quantities, so hotspots in diesel or furnace oil cannot appear."
        )


def method_3() -> None:
    st.markdown(
        "1. For each factory, calculate the emissions of each fuel from its reported quantity (engine and "
        "factor library, the same as everywhere).\n"
        "2. Rank the fuels by emissions. The **top source** is the largest; the **lead** is its share minus "
        "the second's.\n"
        "3. **H4:** degrade the inputs (bills-only profile), rank again, and count how often the top "
        "source is unchanged; compare thin leads with wide leads.\n"
        "4. **H5:** upgrade one input to Measured under three rules (largest source, least trusted, random) "
        "and compare how much the error of the total falls."
    )
    st.latex(r"\text{lead}=s_{(1)}-s_{(2)},\qquad s_i=\frac{E_i}{\sum_j E_j}")
    st.caption(
        f"The 'vital few' in the unit tool are the smallest set of sources that together reach "
        f"{int(hotspot.VITAL_FEW_SHARE * 100)}% of emissions. A hotspot is a priority for attention, not a "
        "finding about efficiency. In simple words: find the biggest mess first, and check you have not "
        "misjudged it."
    )


def results_3() -> None:
    head, ev = _main(), gap_data.evidence()
    if head is None or ev is None:
        _missing()
        return
    h = ev["hotspots"]
    section("How concentrated are the emissions?", f"Factories with two or more fuels, {PERIOD}")
    stat_strip(
        [
            (
                "Top source's share, median",
                pct(h["top_share_median"]),
                f"quartiles {pct(h['top_share_q25'])} to {pct(h['top_share_q75'])}",
            ),
            (
                "Lead over the second, median",
                pct(h["lead_median"]),
                "percentage points of the total",
            ),
            (
                "Thin lead",
                f"{h['thin_lead_factories']:,}",
                f"of {h['multi_fuel_factories']:,}, under {pct(h['thin_lead_below'])}",
            ),
        ]
    )
    counts = h["top_item_counts"]
    items = sorted(counts, key=lambda k: -counts[k])
    fig = go.Figure(
        go.Bar(
            x=[gap_data.FUEL_NAMES.get(i, i) for i in items],
            y=[counts[i] for i in items],
            marker_color=SERIES[0],
            text=[f"{counts[i]:,}" for i in items],
            textposition="outside",
        )
    )
    fig.update_layout(
        yaxis_title="Factories where it is the top source (count)",
        xaxis_title="Fuel that leads the factory's emissions (ASI 2023-24)",
        height=320,
        showlegend=False,
    )
    fig.update_yaxes(rangemode="tozero")
    show(fig)
    top = items[0]
    in_plain_words(
        f"Among {h['multi_fuel_factories']:,} factories with more than one fuel, "
        f"{gap_data.FUEL_NAMES.get(top, top).lower()} is the biggest source in "
        f"{pct(counts[top] / h['multi_fuel_factories'])}. In half of them the top source accounts for "
        f"{pct(h['top_share_median'])} or more of the total, so for most the choice of what to look at "
        "first is clear."
    )
    sections.trust_hotspots(head)
    sections.trust_textile(head, gap_data.result(gap_data.TEXTILE_FILE))
    with st.expander("Method check: the ranking for the reference document's invented example"):
        _method_check_note()
        ex = worked_example.build()
        render(
            table_html(
                [
                    Column("Rank"),
                    Column("Activity"),
                    Column("tCO2e", numeric=True),
                    Column("Share", numeric=True),
                    Column("Vital few"),
                ],
                [
                    [
                        r.rank,
                        r.name,
                        f"{r.co2e_t:,.2f}",
                        pct(float(r.share), 1),
                        "yes" if r.vital_few else "no",
                    ]
                    for r in ex.rows
                ],
                first_bold=False,
            )
        )


def findings_3() -> Findings:
    head, ev = _main(), gap_data.evidence()
    if head is None or ev is None:
        return Findings(*(("Not available: the result file is missing.",) * 6))
    h = ev["hotspots"]
    textile = gap_data.result(gap_data.TEXTILE_FILE)
    t4 = (
        f" For textile factories H4 is '{textile.verdicts['H4']}' on {textile.rows_by_test['H4']:,} rows and H5 '{textile.verdicts['H5']}' on {textile.rows_by_test['H5']:,}."
        if textile
        else ""
    )
    return Findings(
        shows=(
            "In most small factories with more than one fuel one source dominates, and that source "
            "stays on top when the data are reduced to bills. When the lead is thin the ranking is much "
            "less stable. Improving the largest source's data first beat the alternatives, on few factories."
        ),
        numbers=(
            f"Top source kept for {pct(head.top1_kept)} of {head.rows_by_test['H4']:,} factories "
            f"(thin lead: {pct(head.top1_thin_lead) if head.top1_thin_lead is not None else 'n/a'}). "
            f"Median top share {pct(h['top_share_median'])}; {h['thin_lead_factories']:,} of "
            f"{h['multi_fuel_factories']:,} have a thin lead. H5 margin over the best alternative "
            f"{head.h5_reduction.get('largest_first', float('nan')) - max((v for k, v in head.h5_reduction.items() if k != 'largest_first'), default=float('nan')):.3f} "
            f"on {head.h5_rows} factories.{t4}"
        ),
        comparisons=(
            "Top source under degraded data against the original ranking; thin against wide leads; "
            "largest-first against least-trusted-first and random improvement."
        ),
        answerable=(
            "Partly. Whether the top source is stable is answered for electricity-plus-coal-or-gas "
            "factories. Whether to fix the biggest first is only weakly supported, and for textiles it "
            "cannot be tested."
        ),
        relation=(
            f"{cite('cstep2018')} and {cite('ceew2018')} give totals by fuel and sector and no unit "
            "ranking, as is their purpose; the gap is the project's reading, not their statement. "
            f"{cite('halat2026')} report (abstract) that hotspots can be identified with approximate "
            "data; the stability found here is consistent with that."
        ),
        cannot=(
            "A factory has at most three sources here, so stability is an easy test; liquid fuels and "
            "many-activity units are absent. It says nothing about which source is cheapest to cut."
        ),
    )


# =========================================================================================
# Gap 4
# =========================================================================================
def scope_4() -> None:
    ev, head = gap_data.evidence(), _main()
    if ev is None or head is None:
        _missing(gap_data.EVIDENCE_FILE)
        return
    cl = ev["cost_link"]
    stat_strip(
        [
            ("Factories", f"{head.factories:,}", "small, ASI 2023-24"),
            ("Fuel lines", f"{len(cl)}", "electricity, coal, gas (as LPG)"),
            (
                "Fuel records",
                f"{sum(r['records'] for r in cl):,}",
                "each with a quantity and a value",
            ),
            (
                "Reported spend",
                f"INR {sum(r['spend_inr'] for r in cl) / 1e7:,.0f} crore",
                "sum of the three lines",
            ),
        ]
    )
    st.markdown(
        "**Sources.** The ASI 2023-24 purchase value of each fuel line, and the calculated emissions of "
        "its reported quantity (CSTEP 2018 fuel factors; CEA v20.0 grid factor, FY 2023-24). **Excluded.** "
        "Petrol, diesel, oil and other fuel: they carry a value but no quantity, so their emissions cannot "
        "be calculated and they are missing from the spend shares below."
    )
    callout(
        "warn",
        "Spend shares cover three fuels only.",
        "Money spent on petrol, diesel and oil is large but cannot be linked to emissions in this return, "
        "so 'share of spend' here means share of the spend that has a quantity.",
    )


def method_4() -> None:
    st.markdown(
        "1. Calculate the emissions of each fuel record from its reported quantity (engine and factor library).\n"
        "2. For each fuel, add up the spend and the emissions over all small factories and take each as a "
        "share of the three-fuel total.\n"
        "3. Rupees per tonne of CO2e: pooled (total spend over total emissions) and per record (median and "
        "quartiles).\n"
        "4. For each factory with two or more fuels, compare the fuel with the largest spend against the "
        "fuel with the largest emissions."
    )
    st.latex(
        r"\text{INR per tCO}_2\text{e}=\frac{V_f}{E_f},\qquad \text{share}_f=\frac{E_f}{\sum_g E_g}"
    )
    st.caption(
        "V is the reported purchase value and E the calculated emissions of fuel f. In simple words: how "
        "many rupees you pay for each tonne of CO2e that fuel causes. A fuel that is a bigger slice of "
        "emissions than of spend is polluting for its price; the reverse is costly for its emissions."
    )


def results_4() -> None:
    ev = gap_data.evidence()
    if ev is None:
        _missing(gap_data.EVIDENCE_FILE)
        return
    cl = sorted(ev["cost_link"], key=lambda r: -r["spend_share"])
    names = [gap_data.FUEL_NAMES.get(r["item"], r["item"]) for r in cl]
    section("Spend against emissions", f"Share of the three-fuel total, {PERIOD}")
    fig = go.Figure()
    fig.add_bar(
        x=names,
        y=[r["spend_share"] * 100 for r in cl],
        name="Share of reported spend",
        marker_color=SERIES[0],
        text=[pct(r["spend_share"], 1) for r in cl],
        textposition="outside",
    )
    fig.add_bar(
        x=names,
        y=[r["co2e_share"] * 100 for r in cl],
        name="Share of calculated emissions",
        marker_color=SERIES[2],
        text=[pct(r["co2e_share"], 1) for r in cl],
        textposition="outside",
    )
    fig.update_layout(
        barmode="group",
        yaxis_title="Share of total (%)",
        xaxis_title="Fuel line (ASI 2023-24)",
        height=360,
        legend={"orientation": "h", "y": 1.15},
    )
    fig.update_yaxes(range=[0, 105])
    show(fig)
    gaps_pp = {r["item"]: r["co2e_share"] - r["spend_share"] for r in cl}
    polluter = max(gaps_pp, key=gaps_pp.get)
    in_plain_words(
        f"{gap_data.FUEL_NAMES.get(polluter, polluter)} causes a bigger share of emissions "
        f"({pct(next(r['co2e_share'] for r in cl if r['item'] == polluter), 1)}) than of spending "
        f"({pct(next(r['spend_share'] for r in cl if r['item'] == polluter), 1)}); the other lines are the "
        "reverse. A unit that looks only at its bills would underrate that fuel.",
        "Bars of the same fuel are compared: amber taller than blue means polluting for its price.",
    )
    section("Rupees per tonne of CO2e", "Reported spend divided by calculated emissions")
    render(
        table_html(
            [
                Column("Fuel line"),
                Column("Records", numeric=True),
                Column("Spend", numeric=True, note="INR crore"),
                Column("Emissions", numeric=True, note="tCO2e"),
                Column("INR per tCO2e, pooled", numeric=True),
                Column("INR per tCO2e, median", numeric=True),
                Column("Middle half of factories", numeric=True, note="INR per tCO2e"),
            ],
            [
                [
                    gap_data.FUEL_NAMES.get(r["item"], r["item"]),
                    f"{r['records']:,}",
                    f"{r['spend_inr'] / 1e7:,.0f}",
                    f"{r['co2e_t']:,.0f}",
                    f"{r['inr_per_tco2e_pooled']:,.0f}",
                    f"{r['inr_per_tco2e_median']:,.0f}",
                    f"{r['inr_per_tco2e_q25']:,.0f} to {r['inr_per_tco2e_q75']:,.0f}",
                ]
                for r in cl
            ],
        )
    )
    cheapest = min(cl, key=lambda r: r["inr_per_tco2e_pooled"])
    dearest = max(cl, key=lambda r: r["inr_per_tco2e_pooled"])
    in_plain_words(
        f"{gap_data.FUEL_NAMES.get(cheapest['item'], cheapest['item'])} costs the least per tonne of CO2e "
        f"(about INR {cheapest['inr_per_tco2e_pooled']:,.0f}) and "
        f"{gap_data.FUEL_NAMES.get(dearest['item'], dearest['item'])} the most "
        f"(about INR {dearest['inr_per_tco2e_pooled']:,.0f}). A decision on price alone would favour the "
        "fuel that emits most for each rupee."
    )
    h = ev["hotspots"]
    section("Within a factory", "Do the biggest cost and the biggest emitter coincide?")
    stat_strip(
        [
            ("Factories with 2+ fuels", f"{h['multi_fuel_factories']:,}", "can be compared"),
            (
                "Different fuel",
                f"{h['biggest_cost_not_biggest_emitter']:,}",
                pct(h["biggest_cost_not_biggest_emitter"] / h["multi_fuel_factories"], 1)
                + " of them",
            ),
        ]
    )
    st.caption(
        "In these factories the fuel with the largest spend is not the fuel with the largest emissions, "
        "so a cost-only and an emission-only ranking would send them to different places."
    )
    with st.expander("Method check: the cost link for the reference document's invented example"):
        _method_check_note()
        ex = worked_example.build()
        render(
            table_html(
                [
                    Column("Activity"),
                    Column("Cost share", numeric=True),
                    Column("Emission share", numeric=True),
                    Column("INR per tCO2e", numeric=True),
                    Column("Reading"),
                ],
                [
                    [
                        r.name,
                        pct(float(r.cost_share), 1) if r.cost_share is not None else None,
                        pct(float(r.share), 1),
                        f"{r.inr_per_tco2e:,.0f}" if r.inr_per_tco2e is not None else None,
                        r.reading,
                    ]
                    for r in ex.rows
                ],
                first_bold=False,
            )
        )


def findings_4() -> Findings:
    ev = gap_data.evidence()
    if ev is None:
        return Findings(*(("Not available: the result file is missing.",) * 6))
    s = findings.summary(4)
    cl = ev["cost_link"]
    cheapest = min(cl, key=lambda r: r["inr_per_tco2e_pooled"])
    dearest = max(cl, key=lambda r: r["inr_per_tco2e_pooled"])
    name = gap_data.FUEL_NAMES.get
    return Findings(
        shows=(
            "Spend and emissions do not line up fuel by fuel: one fuel is a larger slice of emissions "
            "than of spend, and the rupees paid per tonne of CO2e differ several-fold between fuels."
        ),
        numbers=(
            s.key_finding + f" Pooled INR per tCO2e: {name(cheapest['item'], cheapest['item'])} "
            f"{cheapest['inr_per_tco2e_pooled']:,.0f}, {name(dearest['item'], dearest['item'])} "
            f"{dearest['inr_per_tco2e_pooled']:,.0f}."
        ),
        comparisons="Share of spend against share of emissions, per fuel; biggest cost item against biggest emitter, per factory.",
        answerable=(
            "Partly. That the cost link can be computed from real reported spend, and that it can change "
            "which fuel looks like the priority, is shown. Whether units decide differently because of it, "
            "and the effect of price volatility, are not."
        ),
        relation=(
            f"{cite('cstep2024')} (summary page) and {cite('helo2024')} (abstract) are cited for exposure "
            "to fuel-price rises and for cost and emission objectives that can conflict. The finding here "
            "that fuels differ several-fold in the rupees that buy a tonne of CO2e, so a price-only and "
            "an emission-only ranking can point different ways, is consistent with such a conflict, but "
            "these sources were not read in full and do not test it."
        ),
        cannot=(
            "It cannot show causes, price volatility over time, or marginal prices: the rate is the "
            "factory's average. It excludes petroleum products, which have a value but no quantity."
        ),
    )


# =========================================================================================
# Gap 5
# =========================================================================================
def scope_5() -> None:
    lib = default_library()
    stat_strip(
        [
            ("Fuel factors", f"{len(lib.fuels)}", "CSTEP 2018"),
            ("Grid factor", "0.727", "tCO2/MWh, CEA v20.0, FY 2023-24 average"),
            ("Recommendation rules", f"{len(RULES)}", "each with a source and a caution"),
            ("Unit-level data", "none", "no audited before-and-after figures"),
        ]
    )
    st.markdown(
        "**Sources.** The published factors in the library and the rule library. **What is missing.** Any "
        "real unit's energy use before and after a change. No company, sector or reporting period applies: "
        "this page works on published factors only."
    )
    callout(
        "warn",
        "No unit-level result is shown.",
        "A what-if on an invented unit would be a made-up result, so none is shown. The simulator is "
        "verified against the reference document's hand calculation in the method check below.",
    )


def method_5() -> None:
    st.markdown(
        "1. Each fuel's three gases are weighted by their warming potentials and divided by the energy "
        "to give kg CO2e per gigajoule delivered; electricity uses the grid factor.\n"
        "2. A scenario changes an activity, moves part of one fuel's *energy* to another fuel, or "
        "replaces part of grid electricity; emissions and cost are recalculated.\n"
        "3. For electrification, the break-even is the largest share of the fuel's energy that an "
        "electric route may use for the same useful work and still emit no more."
    )
    st.latex(
        r"I_f=\frac{\mathrm{CO_2}+28\,\mathrm{CH_4}+265\,\mathrm{N_2O}}{1000},\quad "
        r"I_{\text{grid}}=\frac{\text{kg CO}_2/\text{MWh}}{3.6},\quad "
        r"\beta_f=\frac{I_f}{I_{\text{grid}}}"
    )
    st.caption(
        "I is in kg CO2e per GJ (fuel factors in kg/TJ). beta is the break-even share. In simple words: "
        "switching to electricity helps only if the electric machine does the same job using less than "
        "this share of the energy. The grid factor is CO2 only, as CEA gives it. Costs, capital and "
        "reliability are not in this arithmetic."
    )


def results_5() -> None:
    lib = default_library()
    ids = [f.id for f in lib.fuels]
    inten = {i: float(whatif.kg_co2e_per_gj(i, lib)) for i in ids}
    grid = float(whatif.kg_co2e_per_gj("grid_electricity", lib))
    section("Emissions per unit of energy", "kg CO2e per GJ delivered, published factors")
    order = sorted(ids, key=lambda i: -inten[i])
    names = {f.id: f.name for f in lib.fuels}
    fig = go.Figure(
        go.Bar(
            y=[names[i] for i in order] + ["Grid electricity (FY 2023-24 average)"],
            x=[inten[i] for i in order] + [grid],
            orientation="h",
            marker_color=[SERIES[0]] * len(order) + [SERIES[1]],
            text=[f"{inten[i]:.1f}" for i in order] + [f"{grid:.1f}"],
            textposition="outside",
        )
    )
    fig.update_layout(
        xaxis_title="kg CO2e per GJ of energy delivered (before equipment efficiency)",
        height=420,
        showlegend=False,
        margin={"l": 280, "b": 60, "r": 50},
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(range=[0, max(max(inten.values()), grid) * 1.15])
    show(fig)
    in_plain_words(
        f"Per unit of energy, grid electricity ({grid:.0f} kg CO2e per GJ) emits more than every fuel in "
        "the library: it only wins if the electric machine needs far less energy for the same job."
    )
    interpreted = [f.name for f in lib.fuels if f.status != "source_verified"]
    if interpreted:
        st.caption(
            "Not fully verified in the source, so read with care: "
            + ", ".join(interpreted)
            + " (see V-02 in docs/VERIFY.md)."
        )
    section(
        "Break-even for electrification",
        "Largest share of the fuel's energy an electric route may use",
    )
    be = {i: float(whatif.electrification_breakeven(i, lib)) for i in ids}
    order = sorted(ids, key=lambda i: be[i])
    fig = go.Figure(
        go.Bar(
            x=[names[i] for i in order],
            y=[be[i] * 100 for i in order],
            marker_color=SERIES[1],
            text=[pct(be[i]) for i in order],
            textposition="outside",
        )
    )
    fig.update_layout(
        yaxis_title="Break-even share of the fuel's energy (%)",
        xaxis_title="Fuel being replaced",
        height=360,
        showlegend=False,
    )
    fig.update_yaxes(rangemode="tozero")
    show(fig)
    st.caption(
        "Arithmetic from the published factors, not a result about any unit. Efficiency of real electric "
        "equipment (for example heat pumps against resistance heating) decides which side of the line a "
        "unit is on."
    )
    section("Suggested actions and their sources", "The rule library, shown with its cautions")
    rows = []
    for r in RULES:
        links = ", ".join(
            cite(ref.key) if (ref := references.by_ref_id(s.strip())) else esc(s.strip())
            for s in r.sources.split(",")
        )
        rows.append(
            [
                r.id,
                ", ".join(r.items),
                ", ".join(r.equipment) or "any",
                r.action,
                r.caution,
                Html(links),
            ]
        )
    render(
        table_html(
            [
                Column("Rule"),
                Column("Applies to"),
                Column("Equipment"),
                Column("Action"),
                Column("Caution"),
                Column("Sources"),
            ],
            rows,
        )
    )
    with st.expander("Method check: the three reference scenarios on the invented example"):
        _method_check_note()
        ex = worked_example.build()
        render(
            table_html(
                [
                    Column("Scenario"),
                    Column("Baseline tCO2e", numeric=True),
                    Column("After tCO2e", numeric=True),
                    Column("Avoided tCO2e", numeric=True),
                ],
                [
                    [
                        o.titles[0],
                        f"{o.baseline_co2e_t:,.2f}",
                        f"{o.new_co2e_t:,.2f}",
                        f"{o.avoided_co2e_t:,.2f}",
                    ]
                    for o in ex.scenario_outcomes
                ]
                + [
                    [
                        "All together (applied in order)",
                        f"{ex.combined.baseline_co2e_t:,.2f}",
                        f"{ex.combined.new_co2e_t:,.2f}",
                        f"{ex.combined.avoided_co2e_t:,.2f}",
                    ]
                ],
                first_bold=False,
            )
        )
    _unavailable(
        "The question whether the suggested actions deliver their savings cannot be tested without "
        "measured energy use before and after a change.",
        "audited before-and-after energy data for a fuel switch or an efficiency measure in small units, "
        "and the CSTEP 2024 report itself.",
    )


def findings_5() -> Findings:
    s = findings.summary(5)
    coal = float(whatif.electrification_breakeven("coal"))
    return Findings(
        shows=(
            "The simulator's arithmetic is right (it reproduces the hand calculation), and the "
            "published factors show that electrifying a fuel-fired process lowers emissions only "
            "if the electric equipment is far more efficient."
        ),
        numbers=s.key_finding,
        comparisons=f"Fuel intensity against grid intensity; coal's break-even is {pct(coal)}.",
        answerable=(
            "No. Whether a manager can see realistic effects without an audit depends on whether the "
            "simulator's savings match measured ones, and no measured savings are available."
        ),
        relation=(
            f"{cite('cstep2024')} (summary page, via {cite('energetica2024')}) reports that options "
            "differ by cluster and that some electric options cut emissions while others fail on cost. "
            "The break-even arithmetic is consistent in kind with that, but the report itself was not "
            f"read. {cite('zocca2018')} and {cite('nist7850')} are unverified precedents for scenario tools."
        ),
        cannot=(
            "It cannot show savings for any unit, the cost or payback of an option, or that the rule "
            "library's actions suit a given cluster."
        ),
    )


# =========================================================================================
# Gap 6
# =========================================================================================
def scope_6() -> None:
    c = findings.library_counts()
    stat_strip(
        [
            ("Fuel factors", f"{c['fuels']}", f"{c['fuels_verified']} verified in the source"),
            ("Grid factors", f"{c['grids']}", f"{c['grids_verified']} verified in the source"),
            ("Tool reviews", "0", "none done"),
            ("User tests", "0", "protocol written, not run"),
        ]
    )
    st.markdown(
        "**Sources.** The factor library (`src/greeneis/data/`), and the sources named in the literature "
        "for SME carbon tools. **What can be inspected.** What GreenEIS contains. **What cannot.** What "
        "other tools contain: no feature review was done, and the cited sources are abstracts and vendor pages."
    )


def method_6() -> None:
    st.markdown(
        "1. Every factor is stored with value, unit, source label and year; a loader refuses an entry that "
        "lacks one.\n"
        "2. A status says how far the factor was checked: verified in the source document, needs "
        "interpretation, assumed, or unverified.\n"
        "3. The library is inspected for what it holds and what is missing."
    )
    st.caption(
        "In simple words: every number has a label saying where it came from and how sure we are. "
        "That is the part of the tool gap that can be checked here."
    )


def results_6() -> None:
    section("Fuel factors", "kg per TJ; NCV in TJ per kt")
    fuel_factor_table()
    section("Grid electricity", "tCO2 per MWh, CO2 only")
    grid_factor_table()
    st.caption(
        "Not in the library: pet coke, wood and other biomass, biodiesel, bio-CNG, and densities beyond "
        "diesel (V-23, V-24). Pet coke matters for textile wet processing."
    )
    section("Tools named in the literature", "What is known about each, and what was not checked")
    tools = [
        ("EcoVadis Carbon Estimator", "ecovadis_estimator"),
        ("Persefoni (SME carbon accounting)", "persefoni_sme"),
        ("Agrifood energy-source tool (Zocca et al.)", "zocca2018"),
        ("Digital reporting features for SMEs", "digital_reporting"),
        ("AI-assisted emission reporting for SMEs", "ai_reporting"),
    ]
    render(
        table_html(
            [
                Column("Tool or study"),
                Column("Source"),
                Column("How far checked"),
                Column("Feature review"),
            ],
            [
                [
                    name,
                    Html(cite(key)),
                    Html(badge(references.VERIFICATION[references.get(key).verification], "warn")),
                    "not done",
                ]
                for name, key in tools
            ],
            first_bold=False,
        )
    )
    callout(
        "info",
        "How to word the novelty.",
        "Pedigree-matrix data quality, commercial data-quality-to-uncertainty tools, SME scenario tools "
        "and Indian MSME calculators exist. The search was partial (V-15). The defensible statement is: we "
        "found no tool that combines a per-number trust label, a cost link and a what-if, applied to Indian "
        "informal-sector fuel data and tested; never 'first'.",
    )
    _unavailable(
        "Whether other tools demand data, expertise or fees that small units lack is a claim from "
        "abstracts and vendor pages; it has not been tested.",
        "a documented review of each tool (price, inputs, Indian factors, uncertainty handling) and a "
        "usability check with small-unit managers (docs/USABILITY_AND_BUYER_CHECK.md).",
    )


def findings_6() -> Findings:
    s = findings.summary(6)
    return Findings(
        shows="GreenEIS ships Indian factors with their sources, units and years, and says which are verified.",
        numbers=s.key_finding,
        comparisons="None can be made: no other tool was reviewed.",
        answerable="No. The gap is about other tools and about users, and neither was evaluated.",
        relation=(
            f"{cite('srilanka2024')}, {cite('digital_reporting')} and {cite('ai_reporting')} report "
            "barriers of expertise, tools and data for SMEs (abstracts). The library addresses the data "
            "barrier in part; it does not show the barriers are absent for GreenEIS."
        ),
        cannot="It cannot show that GreenEIS is easier, cheaper or better than any other tool.",
    )


# =========================================================================================
# Gap 7
# =========================================================================================
def scope_7() -> None:
    stat_strip(
        [
            ("Buyer or lender reviews", "0", "protocol written, not run"),
            ("Report", "1 page", "Markdown, from the engine"),
            ("Unit-level data", "none", "the report needs a unit's own numbers"),
        ]
    )
    st.markdown(
        "**Sources.** The report generator (`greeneis.report`) and the review protocol "
        "(`docs/USABILITY_AND_BUYER_CHECK.md`). **What is missing.** Any buyer's or lender's reaction, "
        "and any real unit's report."
    )


def method_7() -> None:
    st.markdown(
        "1. The report is built from the engine's results: total with an indicative range and the trust "
        "index, the top hotspots, the cost link, scenario results if any, and the method.\n"
        "2. It always prints the method, the data classes and the statement that it is an estimate and "
        "does not certify.\n"
        "3. A planned review would ask a few buyers or lenders whether such a page would help them; with "
        "three to five people nothing from it would be a statistic."
    )


def results_7() -> None:
    ex = worked_example.build()
    _unavailable(
        "No buyer or lender has seen a report, and no real unit has produced one, so whether the report "
        "answers buyer demands cannot be assessed.",
        "reviews by buyers or lenders of reports built from real small-unit data (protocol in "
        "docs/USABILITY_AND_BUYER_CHECK.md).",
    )
    section("What the report contains", "Structure only; the example is invented")
    _method_check_note()
    with st.expander("The one-page report for the reference document's invented example"):
        st.markdown(ex.report_markdown)
    text = ex.report_markdown.lower()
    checks = [
        ("States that it is an estimate and does not certify", "does not certify" in text),
        ("Prints the trust index and indicative range", "trust index" in text and "range" in text),
        ("Says the scores are indicative design values", "indicative" in text),
    ]
    render(
        table_html(
            [Column("Standing statement"), Column("Present in the generated report")],
            [
                [n, Html(badge("Yes", "ok") if ok else badge("Missing", "danger"))]
                for n, ok in checks
            ],
            first_bold=False,
        )
    )


def findings_7() -> Findings:
    s = findings.summary(7)
    return Findings(
        shows="The report generator works and always carries its limits. Nothing is known about buyers' reactions.",
        numbers=s.key_finding,
        comparisons="None can be made.",
        answerable="No. The research question concerns what buyers and lenders accept; no one has been asked.",
        relation=(
            f"The demand claim rests on {cite('t20_brief')} (a fragmentary extract whose title is not "
            f"established) and on {cite('srilanka2024')} (abstract). Neither was verified, so the "
            "originating source of the gap is open."
        ),
        cannot="It cannot show that any buyer or lender would accept, use or trust the report.",
    )


CONTENT: dict[int, Content] = {
    1: Content(scope_1, method_1, results_1, findings_1),
    2: Content(scope_2, method_2, results_2, findings_2),
    3: Content(scope_3, method_3, results_3, findings_3),
    4: Content(scope_4, method_4, results_4, findings_4),
    5: Content(scope_5, method_5, results_5, findings_5),
    6: Content(scope_6, method_6, results_6, findings_6),
    7: Content(scope_7, method_7, results_7, findings_7),
}

assert set(CONTENT) == {g.number for g in gaps.GAPS}, "every gap needs analysis content"
