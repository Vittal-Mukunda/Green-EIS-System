"""Sections of the real-data analysis, shared by the research-gap pages.

Each function draws one section (a chart and its plain reading) from a published source file: the
national estimates (`src/greeneis/data/national.csv`), the CSTEP recomputation, or the ASI 2023-24
aggregate result files in `outputs/`, loaded by `gap_data`. Nothing is typed in here, and a result file
marked synthetic is never shown. The sections stay inside what the data support: ASI returns are
reported, not metered, and cover registered factories.

They began as the pages National picture and Trust in numbers; those pages are no longer in the
navigation and their sections now sit on the Gap 1, 2 and 3 pages.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from components.alerts import PLACEHOLDER_NOTE, callout
from components.charts import FOCUS, SERIES, show
from components.data_table import Column, Html, table_html
from components.kpi_card import stat_strip
from components.markup import render, section
from components.plain import in_plain_words, pct
from components.status_badge import badge
from pages_study import PLAIN as HYPOTHESIS_PLAIN
from pages_study import VERDICT_TONE

from greeneis.national import load_national
from greeneis.study.headline import Headline
from greeneis.validation import compare_cstep

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


def _ratio_range(flagged: list) -> str:
    """The published figure as a share of the recomputed one, over the cells that disagree."""
    if not flagged:
        return "n/a"
    ratios = [float(c.ratio) for c in flagged]
    low, high = min(ratios), max(ratios)
    return pct(low) if pct(low) == pct(high) else f"{pct(low)} to {pct(high)}"


# ---- National picture (sections used by the Gap 2 page) ---------------------------------------
def _national() -> tuple[dict, object, object, object, list, object, object]:
    nat = load_national()
    cstep, ceew = nat["cstep_informal_total"], nat["ceew_informal_total"]
    brick = nat["ceew_brick_coal"]
    others = [nat[k] for k in ("greentech_brick_coal", "cpcb_brick_coal", "mnre_brick_coal")]
    lo, hi = min(o.low for o in others), max(o.high for o in others)
    return nat, cstep, ceew, brick, others, lo, hi


def national_totals() -> None:
    """The two published national totals, with their method and year."""
    nat, cstep, ceew, brick, others, lo, hi = _national()
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


def brick_coal() -> None:
    """Brick-kiln coal: CEEW against the other studies it cites."""
    nat, cstep, ceew, brick, others, lo, hi = _national()
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


def cstep_recompute() -> None:
    """Recompute CSTEP Table 8 from its Table 7 and its own factors."""
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


# ---- Trust in numbers (sections used by the Gap 1, 2 and 3 pages) -------------------------------
def trust_basis(head: Headline) -> None:
    """What the study compares, stated before any figure."""
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


def trust_proxy_error(head: Headline) -> None:
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
        f"Electricity is {pct(elec.records / head.records) if elec else 'most'} of the records, so the "
        "overall figure mostly describes electricity.",
    )


def trust_ranges(head: Headline) -> None:
    names = [f.name for f in head.fuels]
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


def trust_coverage(head: Headline) -> None:
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


def trust_label(head: Headline) -> None:
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
        "in a follow-up check described in docs/RESULTS_ASI_2023-24.md (exploratory, not pre-specified), "
        "though still stronger than the naive rule."
        if head.multi_item_factories
        else ""
    )
    in_plain_words(
        "The label orders factories by error very well, but most of that is structural: nearly every "
        f"factory has a single fuel, so its label fixes its error. {multi}".strip(),
    )


def trust_hotspots(head: Headline) -> None:
    section(
        "Is the biggest source usually the one to fix?", "Hotspot stability and the priority rule"
    )
    thin = f"{(head.thin_lead_below or 0.10) * 100:.0f}"
    if head.top1_thin_lead is not None and head.top1_thick_lead is not None:
        fig = go.Figure(
            go.Bar(
                x=["All factories", f"Lead under {thin} points", f"Lead {thin} points or more"],
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
            f"fuel (a single-fuel factory has nothing to rank). When its lead over the second was under {thin} percentage points, "
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


def trust_textile(head: Headline, textile: Headline | None) -> None:
    section("Textile factories only", "Exploratory cut, declared before it was run")
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


def placeholder_warning(head: Headline) -> None:
    if head.placeholder_status == "placeholder":
        callout("danger", "These are placeholders, not calibrated scores.", PLACEHOLDER_NOTE)
