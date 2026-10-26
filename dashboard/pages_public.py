"""The public pages: Home, Research gaps, National picture, How far to trust a number, Data and sources.

These pages explain real results to a visitor who has not seen the study. Every figure on them is read
from a published source file (`src/greeneis/data/national.csv`, the CSTEP recomputation, or the ASI
2023-24 aggregate result files in `outputs/`); nothing here is typed in, and a result file marked
synthetic is never shown. They stay inside what the data support: ASI returns are reported, not metered,
and cover registered factories.
"""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import state
import streamlit as st
import vocab
from components.alerts import ESTIMATE_NOTE, PLACEHOLDER_NOTE, callout
from components.charts import FOCUS, SERIES, show
from components.data_table import Column, Html, table_html
from components.empty_state import empty_state
from components.kpi_card import stat_strip
from components.markup import render, section
from components.navigation import link_button
from components.page_header import page_header
from components.plain import in_plain_words, one_in, pct
from components.status_badge import badge
from pages_study import PLAIN as HYPOTHESIS_PLAIN
from pages_study import VERDICT_TONE

from greeneis.national import load_national
from greeneis.study.headline import Headline
from greeneis.study.headline import load as load_headline
from greeneis.validation import compare_cstep

OUTPUTS = Path(__file__).resolve().parents[1] / "outputs"
MAIN_FILE = "study_asi_2023-24.json"
TEXTILE_FILE = "study_asi_2023-24_explor_nic13.json"

ESTIMATED_COLOUR, DEFAULT_COLOUR = "#24557a", "#b7791f"

PROFILE_NAMES = {
    "minimal": "No records: every number a default guess",
    "random_mix": "A mix of measured, estimated and default",
    "bills_only": "Only bills kept: electricity measured, fuels worked out from spend",
    "invoices_main": "Invoices kept for electricity and the main fuel",
}

SOURCE_TONE = {"read_in_original": "ok", "cited_by_original": "info"}
SOURCE_TEXT = {
    "read_in_original": "Read in the original",
    "cited_by_original": "Cited by the original",
}


def _result(name: str) -> Headline | None:
    """A real study result, or None if the file is missing or marked synthetic. Public pages never show
    synthetic results."""
    path = OUTPUTS / name
    if not path.is_file():
        return None
    head = load_headline(path)
    return None if head.synthetic else head


def _need_result(head: Headline | None) -> bool:
    if head is not None:
        return False
    empty_state(
        "The real results file is not available",
        f"Expected outputs/{MAIN_FILE}, produced from the ASI 2023-24 file by python -m greeneis.study.run.",
        "science",
    )
    return True


# ---- Home --------------------------------------------------------------------------------------
def home(ctx: state.Context) -> None:
    head = _result(MAIN_FILE)
    tested = f"{head.factories:,} small factories" if head else "small factories"
    page_header(
        "Can a small factory trust its own energy numbers?",
        "GreenEIS turns a unit's electricity and fuel bills into emissions, and labels every number "
        "Measured, Estimated or Default so the manager knows how far to believe it. This page shows what "
        "happened when that idea was tested on real factory returns.",
        compared="Numbers worked out from a bill and a typical price, against a generic sector-average guess; "
        f"both checked against what {tested} reported to the government.",
        read="Percentages are errors against the quantity the factory reported. 'Half within 6%' means the "
        "middle factory was off by 6%.",
        page="Home",
    )
    if _need_result(head):
        return
    multi_fuel = head.rows_by_test["H4"]
    stat_strip(
        [
            (
                "Real factories tested",
                f"{head.factories:,}",
                f"ASI 2023-24, up to 50 workers, {head.states} states",
            ),
            (
                "Bill and typical price",
                pct(head.estimated_median),
                "typical error of an Estimated number",
            ),
            ("Sector-average guess", pct(head.default_median), "typical error of a Default number"),
            (
                "Biggest source stayed biggest",
                pct(head.top1_kept),
                f"of {multi_fuel:,} factories with 2+ fuels, bills only",
            ),
        ]
    )
    in_plain_words(
        f"Working out a fuel quantity from the rupees paid and a typical local price was usually close: half "
        f"of the estimates were within {pct(head.estimated_median)}. Guessing from the sector average was "
        f"usually far off: half were within {pct(head.default_median)}, and {one_in(0.1)} was off by more "
        f"than {pct(head.default_q90)}. That is why GreenEIS puts a label on every number instead of "
        "showing one total as if it were certain.",
    )

    section("What was found", "Details and caveats are on the pages linked below")
    st.markdown(
        f"""
1. **The label means something.** Estimated numbers were far closer to the reported quantity than Default
   ones. The ordering held in every variation we tried.
2. **The ranges we first assumed were wrong.** The stated uncertainty for Default numbers (plus or minus
   {pct(head.placeholder_default)}) is far too small: nine in ten Default errors were within
   {pct(head.default_q90)}. For coal and LPG the Estimated range is too small too. Each fuel needs its own range.
3. **The biggest source of emissions is usually still the biggest** when a unit keeps only its bills
   ({pct(head.top1_kept)} of the {multi_fuel:,} factories with more than one fuel; less when the lead was thin).
4. **Fix-the-biggest-first is only weakly supported.** It rests on {head.h5_rows} factories.
"""
    )
    section("Where to go next")
    cols = st.columns(3)
    with cols[0]:
        link_button("The seven research gaps", "Research gaps", "home_gaps", vocab.PAGES)
        link_button("National estimates disagree", "National picture", "home_national", vocab.PAGES)
    with cols[1]:
        link_button("How far to trust a number", "Trust in numbers", "home_trust", vocab.PAGES)
        link_button("Data and sources", "Data and sources", "home_sources", vocab.PAGES)
    with cols[2]:
        link_button("Try it on your own bills", "Data entry", "home_entry", vocab.PAGES)
        link_button("Factors and method", "Factors and method", "home_factors", vocab.PAGES)

    callout(
        "warn",
        "What this does not show.",
        "The returns are what each factory reported, not metered. ASI covers registered factories, not the "
        "informal units the research is ultimately about. It is one year, and it has no diesel or furnace "
        "oil, which matter most for the smallest units. The record-keeping profiles are our assumptions "
        "about what a unit keeps, not observed behaviour. " + ESTIMATE_NOTE,
    )


# ---- Research gaps -----------------------------------------------------------------------------
def research_gaps(ctx: state.Context) -> None:
    page_header(
        "Research gaps",
        "Seven gaps in the evidence on emissions from small and informal manufacturing, what GreenEIS does "
        "about each, what the real data say, and how far each is actually settled.",
        read="'Status' is deliberately modest. A built feature is not a proven one: only gap 2 has been "
        "tested on real data, and only partly.",
    )
    head = _result(MAIN_FILE)
    nat = load_national()
    cstep, ceew = nat["cstep_informal_total"], nat["ceew_informal_total"]
    brick = nat["ceew_brick_coal"]
    others = [nat[k] for k in ("greentech_brick_coal", "cpcb_brick_coal", "mnre_brick_coal")]
    lo, hi = min(o.low for o in others), max(o.high for o in others)

    missing = "The real results file is not available."
    found_1 = found_2 = found_3 = missing
    if head is not None:
        found_1 = (
            f"{head.factories:,} real small factories' own reported returns were used to test what can "
            "be recovered when only bills exist. No real unit-level energy audit has been obtained yet."
        )
        found_2 = (
            f"Estimated numbers: half within {pct(head.estimated_median)}. Default numbers: half within "
            f"{pct(head.default_median)}. The ranges first assumed were too narrow."
        )
        thin = (
            f" ({pct(head.top1_thin_lead)} when the lead was thin)"
            if head.top1_thin_lead is not None
            else ""
        )
        found_3 = (
            f"The top hotspot stayed the top hotspot for {pct(head.top1_kept)} of the "
            f"{head.rows_by_test['H4']:,} factories with more than one fuel{thin}. "
            f"Fixing the biggest first rests on only {head.h5_rows} factories."
        )

    rows = [
        (
            "1",
            "No firm-level, regularly updated fuel and energy data for informal units",
            "CSTEP: industry-wise data missing for petroleum and gas, and for 45% of coal. CEEW: no official "
            "energy statistics, and surveys lack validation. Both ask for firm-level data.",
            "Monthly data entry by the unit itself, each line labelled by how well it is known.",
            found_1,
            ("Partly addressed", "warn"),
            "Data entry",
        ),
        (
            "2",
            "Estimates carry unquantified uncertainty, and the numbers conflict",
            f"CSTEP {cstep.low:g} vs CEEW {ceew.low:g} {cstep.unit} ({cstep.year}). Brick-kiln coal "
            f"{brick.low:g} Mt (CEEW) vs {lo:g} to {hi:g} Mt in other studies.",
            "A trust label on every number, rolled up into a trust index and a range.",
            found_2,
            ("Evidence on real data", "ok"),
            "Trust in numbers",
        ),
        (
            "3",
            "National studies do not tell one factory what to fix first",
            "Both studies report national or sectoral totals only.",
            "A ranking of the unit's own activities (hotspots).",
            found_3,
            ("Partly: priority rule weak", "warn"),
            "Hotspots",
        ),
        (
            "4",
            "Emissions are not linked to cost",
            "Energy is a large share of MSME cost and fuel prices are volatile; cost and emission goals can "
            "conflict (as cited in the project reference document).",
            "Rupees and emissions side by side for each activity.",
            "Built and checked by hand calculation. Not yet tested with real users or real bills.",
            ("Built, not validated", "warn"),
            "Hotspots",
        ),
        (
            "5",
            "Decarbonisation evidence is cluster-level and needs audits and engineers",
            "A recent CSTEP study needed two years and 66 units; finance often needs audit reports that small "
            "units cannot prepare (as cited in the project reference document).",
            "A what-if page and rule-based suggestions that need no audit.",
            "Built on the real CSTEP fuel factors. The savings are arithmetic on the unit's own numbers, "
            "not audited results.",
            ("Built, not validated", "warn"),
            "What-if",
        ),
        (
            "6",
            "SME carbon tools demand data, expertise or fees, and few are specific to Indian MSME fuels",
            "Barriers named in SME carbon-accounting studies cited by the project reference document.",
            "Indian CSTEP and CEA factors built in, minimal inputs, free, every factor and source shown.",
            "Our search for similar tools was partial. We found no tool that combines a per-number trust "
            "label, a rupee link and a what-if; that is not a claim to be first.",
            ("Partial search", "warn"),
            "Factors and method",
        ),
        (
            "7",
            "Suppliers face buyer demands for emission data but lack the means to answer",
            "Lost-contract risk is argued in a policy brief cited by the project reference document.",
            "A one-page report that always prints the method and the 'estimates, not certified' note.",
            "Built. No buyer or lender has reviewed it yet; the review protocol is written but not run.",
            ("Built, not tested with buyers", "warn"),
            "Report",
        ),
    ]
    render(
        table_html(
            [Column("#"), Column("The gap"), Column("Status")],
            [
                [n, gap, Html(badge(status[0], status[1]))]
                for n, gap, _e, _d, _f, status, _p in rows
            ],
        )
    )
    callout(
        "info",
        "Why most statuses are modest.",
        "A gap is settled only when it has been tested on real data. Gap 2 has (on ASI returns, not on "
        "informal units). Gaps 1 and 3 are partly tested. Gaps 4 to 7 are built and checked by hand, but "
        "nobody outside this project has used them yet.",
    )
    for n, gap, evidence, does, data, status, page in rows:
        with st.container(border=True):
            render(badge(status[0], status[1]))
            st.markdown(f"**Gap {n}. {gap}**")
            st.markdown(f"**In the literature.** {evidence}")
            st.markdown(f"**What GreenEIS does.** {does}")
            st.markdown(f"**What the real data show.** {data}")
            link_button(f"Gap {n}: {page}", page, f"gap_{n}", vocab.PAGES)
    st.caption(
        "The gaps and their evidence follow Table 5.1 of the project reference document. Its sources S1 "
        "(CSTEP) and S2 (CEEW) were read in the original reports; the rest are quoted through the "
        "reference document."
    )


def _ratio_range(flagged: list) -> str:
    """The published figure as a share of the recomputed one, over the cells that disagree."""
    if not flagged:
        return "n/a"
    ratios = [float(c.ratio) for c in flagged]
    low, high = min(ratios), max(ratios)
    return pct(low) if pct(low) == pct(high) else f"{pct(low)} to {pct(high)}"


# ---- National picture --------------------------------------------------------------------------
def national_picture(ctx: state.Context) -> None:
    page_header(
        "National picture",
        "How much the published estimates of India's informal-sector emissions disagree, and whether one "
        "of them agrees with its own arithmetic.",
        compared="Two independent national estimates for 2015-16, and CEEW's brick-kiln coal against other studies.",
        read="Each bar or point is a published figure with its source. These are other groups' numbers; "
        "GreenEIS did not compute them.",
    )
    nat = load_national()
    cstep, ceew = nat["cstep_informal_total"], nat["ceew_informal_total"]
    brick = nat["ceew_brick_coal"]
    others = [nat[k] for k in ("greentech_brick_coal", "cpcb_brick_coal", "mnre_brick_coal")]
    lo, hi = min(o.low for o in others), max(o.high for o in others)
    stat_strip(
        [
            ("CSTEP estimate", f"{cstep.low:g} {cstep.unit}", f"{cstep.year}, fuel-supply method"),
            ("CEEW estimate", f"{ceew.low:g} {ceew.unit}", f"{ceew.year}, demand-side method"),
            ("Brick-kiln coal, CEEW", f"{brick.low:g} Mt", f"other studies: {lo:g} to {hi:g} Mt"),
        ]
    )

    section("Two national totals, two methods")
    fig = go.Figure(
        go.Bar(
            x=["CSTEP 2018", "CEEW 2018"],
            y=[float(cstep.low), float(ceew.low)],
            marker_color=[SERIES[0], SERIES[1]],
            text=[f"{cstep.low:g}", f"{ceew.low:g}"],
            textposition="outside",
            hovertemplate="%{x}: %{y} MtCO2e<extra></extra>",
        )
    )
    fig.update_layout(yaxis_title="MtCO2e, 2015-16", height=320, showlegend=False)
    fig.update_yaxes(rangemode="tozero")
    show(fig)
    in_plain_words(
        f"Two research groups, using different methods, put the informal sector's emissions at about "
        f"{ceew.low:g} to {cstep.low:g} million tonnes of CO2e for 2015-16. The totals are close; the "
        "details underneath are not, and neither group gives an uncertainty for its figure. Both exclude "
        "process emissions.",
        "Bars start at zero, so the small difference between them is shown at its true size.",
    )

    section("Brick-kiln coal: where the estimates split apart")
    coal = [brick, *others]
    fig = go.Figure()
    for est in coal:
        xs = [float(est.low), float(est.high)] if est.is_range else [float(est.low)]
        name = est.source.split(",")[0].split(" (")[0]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=[name] * len(xs),
                mode="lines+markers",
                line={"width": 6, "color": FOCUS if est.id == brick.id else SERIES[2]},
                marker={"size": 11, "color": FOCUS if est.id == brick.id else SERIES[2]},
                hovertemplate=f"{name}: {est.low:g}"
                + (f" to {est.high:g}" if est.is_range else "")
                + " Mt coal<extra></extra>",
                showlegend=False,
            )
        )
    fig.update_layout(
        margin={"b": 72}, xaxis_title="Coal used by brick kilns, million tonnes", height=340
    )
    fig.update_xaxes(rangemode="tozero")
    fig.update_yaxes(autorange="reversed")
    show(fig)
    in_plain_words(
        f"For the same industry, the estimates of coal burned range from {brick.low:g} to {hi:g} million "
        f"tonnes, and the highest is about {float(hi / brick.low):.1f} times CEEW's. CEEW tested its own method on bricks, found "
        "its figure far below the others, and traced part of the gap to under-counted workers in the survey "
        "it used. This is the kind of disagreement a label on each number is meant to make visible.",
        "A dot is a single estimate; a line is a range. The dark one is CEEW's.",
    )
    render(
        table_html(
            [
                Column("Figure"),
                Column("Low", numeric=True),
                Column("High", numeric=True),
                Column("Unit"),
                Column("Year"),
                Column("Source"),
                Column("Status"),
            ],
            [
                [
                    e.label,
                    f"{e.low:g}",
                    f"{e.high:g}",
                    e.unit,
                    e.year,
                    e.source,
                    Html(badge(SOURCE_TEXT[e.status], SOURCE_TONE[e.status], tip=e.note)),
                ]
                for e in nat.values()
            ],
        )
    )

    section("Does CSTEP's petroleum table agree with its own factors?")
    cells = compare_cstep()
    agree = sum(c.matches for c in cells)
    by_col: dict[str, list] = {}
    for c in cells:
        by_col.setdefault(c.column, []).append(c)
    fig = go.Figure()
    fig.add_bar(
        y=list(by_col),
        x=[sum(c.matches for c in v) for v in by_col.values()],
        name="Agrees within 1%",
        orientation="h",
        marker_color=SERIES[1],
    )
    fig.add_bar(
        y=list(by_col),
        x=[sum(not c.matches for c in v) for v in by_col.values()],
        name="Does not agree",
        orientation="h",
        marker_color=DEFAULT_COLOUR,
    )
    fig.update_layout(
        barmode="stack",
        margin={"b": 72},
        xaxis_title="Years (of 8)",
        height=320,
        legend={"orientation": "h", "y": 1.15},
    )
    fig.update_yaxes(autorange="reversed")
    show(fig)
    furnace = [c for c in by_col["FO"] if not c.matches]
    in_plain_words(
        f"We recomputed {len(cells)} published emission figures for petroleum fuels from CSTEP's own "
        f"consumption table and factors. {agree} agree. {len(cells) - agree} do not. For furnace oil from "
        f"2012-13, the published figure is only {pct(float(min(c.ratio for c in furnace)))} to "
        f"{pct(float(max(c.ratio for c in furnace)))} of what its own inputs give. We do not know why, "
        "and we have not contacted the authors. We flag it; we do not correct it.",
        "Each bar is one fuel column of CSTEP's table, split into the years that agree and the years that do not.",
    )
    render(
        table_html(
            [
                Column("Fuel column"),
                Column("Years that agree", numeric=True),
                Column("Years that do not agree"),
                Column("Published as share of recomputed"),
            ],
            [
                [
                    name,
                    f"{sum(c.matches for c in v)} of {len(v)}",
                    ", ".join(c.year for c in v if not c.matches) or "none",
                    _ratio_range([c for c in v if not c.matches]),
                ]
                for name, v in by_col.items()
            ],
        )
    )
    st.caption(
        "Natural gas is excluded: CSTEP gives it by volume and the library has no sourced volumetric calorific "
        "value. CSTEP's factor tables also print 'kt/TJ' where the magnitudes are kg/TJ; the library uses kg/TJ."
    )


# ---- Trust in numbers --------------------------------------------------------------------------
def trust_in_numbers(ctx: state.Context) -> None:
    page_header(
        "Trust in numbers",
        "Whether the Measured, Estimated and Default labels tell you how far to believe a number, tested "
        "against what real small factories reported.",
        compared="For each factory fuel, a number worked out the way a unit without meters would work it "
        "out, against the quantity the factory reported to the government.",
        read="An error of 6% means the worked-out number was 6% away from the reported one. The middle of "
        "all errors is called the median; the 90th percentile is the error that nine in ten stay below.",
    )
    head = _result(MAIN_FILE)
    if _need_result(head):
        return
    stat_strip(
        [
            (
                "Factories",
                f"{head.factories:,}",
                f"{head.records:,} fuel records, {head.states} states",
            ),
            ("Source", "ASI 2023-24", "small factories, up to 50 workers"),
            ("Reference", "Reported", "not metered, so reporting slips are in the 'truth'"),
        ]
    )
    callout(
        "warn",
        "Read this first.",
        "The 'true' quantity is what the factory reported in its return. A Default or Estimated number is "
        "our proxy for it, applied by us, not by the owners. The proxies: Estimated = rupees spent divided "
        "by the typical price of that fuel in the same state; Default = the sector's median use per worker "
        "times this factory's workers.",
    )

    section(
        "How close is a number worked out from a bill?", "Median error by fuel, lower is better"
    )
    names = [f.name for f in head.fuels]
    fig = go.Figure()
    fig.add_bar(
        x=names,
        y=[f.estimated_median * 100 for f in head.fuels],
        name="Estimated: spend divided by typical price",
        marker_color=ESTIMATED_COLOUR,
        text=[pct(f.estimated_median) for f in head.fuels],
        textposition="outside",
    )
    fig.add_bar(
        x=names,
        y=[f.default_median * 100 for f in head.fuels],
        name="Default: sector average times workers",
        marker_color=DEFAULT_COLOUR,
        text=[pct(f.default_median) for f in head.fuels],
        textposition="outside",
    )
    fig.update_layout(
        barmode="group",
        yaxis_title="Median error (%)",
        height=360,
        legend={"orientation": "h", "y": 1.15},
    )
    fig.update_yaxes(rangemode="tozero")
    show(fig)
    e = {f.item: f for f in head.fuels}
    elec = e.get("grid_electricity")
    in_plain_words(
        (
            f"For electricity, half of the numbers worked out from the bill were within {pct(elec.estimated_median)} "
            f"of the reported units, because tariffs are nearly the same across a state. "
            if elec
            else ""
        )
        + "Coal and LPG are less exact because prices vary more. A generic sector-average guess is far worse "
        f"for every fuel: the middle error is about {pct(head.default_median)}.",
        "Electricity is 90% of the records, so the overall figure mostly describes electricity.",
    )

    section(
        "Are the uncertainty ranges honest?",
        "90th percentile error against the range first assumed",
    )
    fig = go.Figure(
        go.Bar(
            x=names,
            y=[f.estimated_q90 * 100 for f in head.fuels],
            marker_color=ESTIMATED_COLOUR,
            text=[pct(f.estimated_q90) for f in head.fuels],
            textposition="outside",
            hovertemplate="%{x}: nine in ten within %{y:.0f}%<extra></extra>",
        )
    )
    fig.add_hline(
        y=head.placeholder_estimated * 100,
        line_dash="dash",
        line_color=DEFAULT_COLOUR,
        annotation_text=f"Range first assumed: plus or minus {pct(head.placeholder_estimated)}",
        annotation_position="top left",
    )
    fig.update_layout(yaxis_title="90th percentile error (%)", height=340, showlegend=False)
    fig.update_yaxes(rangemode="tozero")
    show(fig)
    worst = max(head.fuels, key=lambda f: f.estimated_q90)
    in_plain_words(
        f"We first assumed an Estimated number is good to plus or minus {pct(head.placeholder_estimated)}. "
        f"That holds for electricity but not for {worst.name}, where nine in ten estimates were within "
        f"{pct(worst.estimated_q90)}. For Default numbers we assumed plus or minus "
        f"{pct(head.placeholder_default)}; nine in ten were within {pct(head.default_q90)}, so the assumed "
        "range was far too small. The ranges on the pages of this site are therefore placeholders to be "
        "replaced fuel by fuel, not findings.",
        "Bars taller than the dashed line mean the assumed range would miss more than one in ten true values.",
    )

    section(
        "Does the range contain the truth?",
        "Share of factories whose stated range included the reported quantity",
    )
    order = [p for p in PROFILE_NAMES if p in head.coverage_by_profile]
    fig = go.Figure(
        go.Bar(
            y=[PROFILE_NAMES[p] for p in order],
            x=[head.coverage_by_profile[p] * 100 for p in order],
            orientation="h",
            marker_color=ESTIMATED_COLOUR,
            text=[pct(head.coverage_by_profile[p]) for p in order],
            textposition="outside",
        )
    )
    fig.add_vline(
        x=90,
        line_dash="dash",
        line_color=DEFAULT_COLOUR,
        annotation_text="90%",
        annotation_position="top",
    )
    fig.update_layout(
        margin={"b": 72},
        xaxis_title="Factories whose range contained the reported quantity (%)",
        height=320,
        showlegend=False,
    )
    fig.update_xaxes(range=[0, 112])
    fig.update_yaxes(autorange="reversed")
    show(fig)
    in_plain_words(
        f"When a unit keeps no records, the stated range contained the reported quantity for only "
        f"{pct(head.coverage_by_profile['minimal'])} of factories; with a mixture it was "
        f"{pct(head.coverage_by_profile['random_mix'])}. Only when most numbers come from bills or invoices "
        "does it come close to what a range should deliver. Overall, "
        f"{pct(head.coverage)} of factories were covered.",
        "The dashed line is where a 90% range would sit. Reading the assumed ranges as 90% ranges is itself "
        "an assumption we have not yet confirmed.",
    )

    section(
        "Does the label predict the error?",
        "Rank correlation between the trust index and the error",
    )
    st.markdown(
        f"- Across all factories the correlation between the trust index and the error is "
        f"**{head.spearman_pooled:.2f}** (minus one is a perfect match in the opposite direction).\n"
        f"- Within the mixed profile alone it is **{head.spearman_within_random_mix:.2f}**.\n"
        f"- A naive rule, the share of emissions that is Default, scores {head.naive_default_share_rho:.2f} "
        "in the same test (positive, because more Default means more error)."
    )
    multi = (
        f"Among the {head.multi_item_factories:,} factories with two or more fuels the link is weaker "
        "(about -0.8 in a follow-up check described in docs/RESULTS_ASI_2023-24.md), though still "
        "stronger than the naive rule."
        if head.multi_item_factories
        else ""
    )
    in_plain_words(
        "The label orders factories by error very well, but most of that is structural: nearly every "
        f"factory has a single fuel, so its label fixes its error. {multi}".strip(),
    )

    section(
        "Is the biggest source usually the one to fix?", "Hotspot stability and the priority rule"
    )
    if head.top1_thin_lead is not None and head.top1_thick_lead is not None:
        fig = go.Figure(
            go.Bar(
                x=["All factories", "Lead under 10 points", "Lead 10 points or more"],
                y=[head.top1_kept * 100, head.top1_thin_lead * 100, head.top1_thick_lead * 100],
                marker_color=[ESTIMATED_COLOUR, DEFAULT_COLOUR, ESTIMATED_COLOUR],
                text=[pct(head.top1_kept), pct(head.top1_thin_lead), pct(head.top1_thick_lead)],
                textposition="outside",
            )
        )
        fig.update_layout(
            yaxis_title="Biggest source still biggest (%)", height=320, showlegend=False
        )
        fig.update_yaxes(range=[0, 112])
        show(fig)
        in_plain_words(
            f"With only bills to go on, the unit's biggest source of emissions was still the biggest in "
            f"{pct(head.top1_kept)} of the {head.rows_by_test['H4']:,} factories with more than one "
            "fuel (a single-fuel factory has nothing to rank). When its lead over the second was under 10 percentage points, "
            f"that fell to {pct(head.top1_thin_lead)}, so a close call is worth double-checking. A factory here "
            "has at most three sources, so this is an easy test.",
        )
    if head.h5_reduction:
        labels = {
            "largest_first": "Improve the biggest source first",
            "lowest_trust_first": "Improve the least trusted first",
            "random": "Improve in random order",
        }
        fig = go.Figure(
            go.Bar(
                x=[labels.get(k, k) for k in head.h5_reduction],
                y=[v * 100 for v in head.h5_reduction.values()],
                marker_color=[SERIES[1], SERIES[0], "#9aa5a0"],
                text=[pct(v) for v in head.h5_reduction.values()],
                textposition="outside",
            )
        )
        fig.update_layout(
            yaxis_title="Average reduction in total error (%)", height=320, showlegend=False
        )
        fig.update_yaxes(rangemode="tozero")
        show(fig)
        in_plain_words(
            "Improving the data of the biggest source first reduced the error in the total more than the "
            f"alternatives did. But this rests on only {head.h5_rows} factories, so treat it as weak "
            "support, not proof.",
        )

    section("Textile factories only", "Exploratory cut, declared before it was run")
    textile = _result(TEXTILE_FILE)
    if textile is not None:
        render(
            table_html(
                [
                    Column("Question"),
                    Column("All small factories"),
                    Column("Textile only (exploratory)"),
                ],
                [
                    [
                        HYPOTHESIS_PLAIN[h],
                        Html(
                            badge(
                                head.verdicts[h].capitalize(),
                                VERDICT_TONE.get(head.verdicts[h], ""),
                            )
                            + f" {head.rows_by_test[h]:,} rows"
                        ),
                        Html(
                            badge(
                                textile.verdicts[h].capitalize(),
                                VERDICT_TONE.get(textile.verdicts[h], ""),
                            )
                            + f" {textile.rows_by_test[h]:,} rows"
                        ),
                    ]
                    for h in head.verdicts
                ],
                first_bold=False,
            )
        )
        in_plain_words(
            f"Among {textile.factories:,} textile factories the Estimated-versus-Default ordering held "
            f"(median errors {pct(textile.estimated_median)} against {pct(textile.default_median)}). The "
            "hotspot and priority questions could not be tested: too few textile factories use more than "
            "one tracked fuel. Real unit data are needed for that.",
        )
    else:
        st.caption("The textile cut is not available in this deployment.")

    if head.placeholder_status == "placeholder":
        callout("danger", "These are placeholders, not calibrated scores.", PLACEHOLDER_NOTE)


# ---- Data and sources --------------------------------------------------------------------------
def data_and_sources(ctx: state.Context) -> None:
    page_header(
        "Data and sources",
        "Every data source behind this site, what was taken from it, and what is not shown and why.",
        read="'Terms' says whether the source's reuse conditions have been read. Where they have not, only "
        "aggregate results are published here and no factory-level row.",
    )
    head = _result(MAIN_FILE)
    in_file = (
        f" from the file's {head.factories_in_file:,} factories"
        if head and head.factories_in_file
        else ""
    )
    asi_rows = (
        f"{head.factories:,} small factories ({head.records:,} fuel records){in_file}"
        if head
        else "results file not available"
    )
    render(
        table_html(
            [
                Column("Source"),
                Column("Year"),
                Column("Used for"),
                Column("What was taken"),
                Column("Terms"),
            ],
            [
                [
                    "CSTEP, informal-sector emissions report",
                    "2018",
                    "Fuel factors, calorific values, national estimate, petroleum tables",
                    "Tables 2 to 4 (factors), 7 and 8 (recomputed); 110 MtCO2e",
                    "Published report; read in the original",
                ],
                [
                    "CEEW, informal-sector emissions report",
                    "2018",
                    "National estimate, brick-kiln coal",
                    "105 MtCO2e; 26 Mt brick coal and the studies it compares with",
                    "Published report; read in the original",
                ],
                [
                    "CEA CO2 Baseline Database v20.0, Table S",
                    "FY2023-24",
                    "Grid electricity factor",
                    "0.727 tCO2/MWh (average); 0.757 (combined margin). CO2 only",
                    "Published; newer versions may exist",
                ],
                [
                    "Annual Survey of Industries (MoSPI), unit-level file",
                    "2023-24",
                    "Testing the trust labels on real factories",
                    asi_rows,
                    "Portal terms not yet read: only aggregate results are published here",
                ],
                [
                    "SAMEEKSHA and BEE cluster profiles",
                    "various",
                    "Background on clusters only",
                    "Nothing in the numbers on this site",
                    "No terms stated; not used for any figure",
                ],
            ],
        )
    )
    section("Download the aggregate results")
    st.caption(
        "Aggregates only: test statistics, error summaries and counts. No factory-level row leaves the "
        "machine the ASI file is on."
    )
    for name, label in (
        (MAIN_FILE, "Main run: all small factories (JSON)"),
        (TEXTILE_FILE, "Textile factories only, exploratory (JSON)"),
    ):
        path = OUTPUTS / name
        if path.is_file():
            st.download_button(
                label, path.read_bytes(), file_name=name, mime="application/json", key=f"dl_{name}"
            )
    section("What is not here, and why")
    st.markdown(
        """
- **No unit-level energy audits.** The public BEE audit reports for Pali, Indore and Ludhiana could not be
  obtained (removed from the live site; archive copies were rate-limited). Cluster profiles hold only typical
  values.
- **No factory-level rows from ASI.** The portal's terms of use have not been read.
- **No diesel, furnace oil or biomass.** The ASI file reports no quantity for them, and the factor library
  does not yet have a verified source for biomass or pet coke.
- **One year.** A true test on a held-out year needs the earlier ASI rounds, which need a free login.
"""
    )
