"""The five pages for one unit: Data entry, Summary, Hotspots, What-if, Report.

Pages call components and the `greeneis` package; they never write CSS or HTML structure of their own.
Every number comes from the engine, the trust score, the hotspot module or the what-if module.
"""

from __future__ import annotations

from decimal import Decimal

import plotly.graph_objects as go
import state
import streamlit as st
from components.alerts import (
    ESTIMATE_NOTE,
    EXAMPLE_NOTE,
    PLACEHOLDER_NOTE,
    SCOPE_NOTE,
    callout,
)
from components.charts import show
from components.data_table import Column, Html, name_cell, table_html
from components.empty_state import empty_state
from components.format import fmt_inr, fmt_pct, fmt_t
from components.kpi_card import stat_strip
from components.markup import render, section
from components.navigation import open_page
from components.page_header import page_header
from components.status_badge import badge, data_class_badge, trust_band_badge
from plotly.subplots import make_subplots

from greeneis import hotspot, recommend, whatif
from greeneis import report as report_module
from greeneis import trust as trust_module
from greeneis.engine import ELECTRICITY_ITEM
from greeneis.factors import default_library

CLASS_COLOURS = {"measured": "#2e7d5b", "estimated": "#24557a", "default": "#b7791f"}


def _need_data(ctx: state.Context, page: str) -> bool:
    """Say so and return True when there is nothing to show yet."""
    if ctx.has_data:
        return False
    empty_state(
        "No activities yet",
        "Enter at least one fuel or electricity line on the Data entry page.",
        "edit_note",
    )
    st.button(
        "Go to Data entry", key=f"goto_entry_{page}", on_click=open_page, args=("Data entry",)
    )
    return True


def _problems(ctx: state.Context) -> None:
    if ctx.errors:
        callout(
            "danger",
            f"{len(ctx.errors)} row(s) are left out of the results.",
            " ".join(ctx.errors),
        )
    if ctx.warnings:
        callout("warn", "Check these.", " ".join(ctx.warnings))


# ---- Data entry --------------------------------------------------------------------------------
def data_entry(ctx: state.Context) -> None:
    ss = st.session_state
    page_header(
        "Data entry",
        "One period of a unit's energy, fuel and cost data. Each line says how well that number is known.",
        read="Pick the item, enter the quantity in the unit on your bill or register, and say whether the "
        "number is Measured, Estimated or Default. A line you are unsure about should be Estimated or Default.",
    )
    if ctx.is_example:
        callout("info", "Example data.", EXAMPLE_NOTE)

    left, mid, right = st.columns([2, 2, 2])
    left.text_input("Unit name", key="unit_name")
    periods = list(ss["periods"])
    mid.selectbox("Period", periods, key="period")
    with right:
        new_period = st.text_input("Add a period", placeholder="e.g. June 2026", key="new_period")
        if st.button("Add period", key="add_period") and state.add_period(new_period):
            st.rerun()

    period = ss["period"]
    sales = st.number_input(
        "Sales in this period (INR lakh, optional)",
        min_value=0.0,
        value=float(ss["sales"].get(period, 0.0)),
        step=1.0,
        key=f"sales_{period}",
        help="Used only to show emissions per rupee of sales.",
    )
    ss["sales"][period] = sales

    names = list(state.item_names())
    section("Activities", "Add a row with the + at the bottom of the table")
    edited = st.data_editor(
        ss["bases"][period],
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=f"editor::{period}::{ss['editor_version']}",
        column_config={
            "Item": st.column_config.SelectboxColumn("Item", options=names, width="large"),
            "Name": st.column_config.TextColumn(
                "Name", help="Your own name for it, e.g. Boiler coal"
            ),
            "Quantity": st.column_config.NumberColumn("Quantity", min_value=0.0, format="%.2f"),
            "Unit": st.column_config.SelectboxColumn("Unit", options=state.UNITS, width="small"),
            "Data class": st.column_config.SelectboxColumn(
                "Data class", options=list(state.CLASS_LABELS)
            ),
            "Cost (INR)": st.column_config.NumberColumn("Cost (INR)", min_value=0.0, format="%.0f"),
            "Equipment": st.column_config.SelectboxColumn("Equipment", options=state.EQUIPMENT),
        },
    )
    edited = edited.reset_index(drop=True)
    if not edited.equals(ss["periods"][period].reset_index(drop=True)):
        ss["periods"][period] = edited
        st.rerun()  # so the sidebar and the other pages see the edit at once

    _problems(ctx)
    section("What the data classes mean")
    render(
        table_html(
            [Column("Class"), Column("Meaning"), Column("Examples")],
            [
                [
                    Html(data_class_badge("measured")),
                    "Directly metered, billed or weighed for the period.",
                    "Electricity bill; fuel invoice with a quantity; a flow meter.",
                ],
                [
                    Html(data_class_badge("estimated")),
                    "Worked out from something else you know.",
                    "Generator hours times rated consumption; coal from opening and closing stock; spend divided by price.",
                ],
                [
                    Html(data_class_badge("default")),
                    "A generic value because nothing better exists.",
                    "A sector average; an assumed coal grade.",
                ],
            ],
            first_bold=False,
        )
    )

    section("Load, save or reset")
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        "Download all periods (CSV)",
        state.all_periods_csv(),
        file_name="greeneis_inputs.csv",
        mime="text/csv",
        key="dl_inputs",
    )
    upload = c2.file_uploader(
        "Upload a CSV", type="csv", key="ul_inputs", label_visibility="collapsed"
    )
    if upload is not None and ss.get("_uploaded_name") != (upload.name, upload.size):
        count, error = state.load_csv(upload.getvalue())
        ss["_uploaded_name"] = (upload.name, upload.size)
        if error:
            callout("danger", "Upload failed.", error)
        else:
            st.rerun()
    if c3.button("Start with a blank table", key="blank_table"):
        ss["bases"], ss["periods"], ss["sales"], ss["scenarios"] = {}, {}, {}, []
        state.replace_period("Period 1", state.empty_frame())
        ss["period"], ss["unit_name"] = "Period 1", ""
        st.rerun()
    if st.button("Reload the illustrative example", key="reload_example"):
        ss["bases"], ss["periods"], ss["sales"], ss["scenarios"] = {}, {}, {}, []
        state.replace_period(state.EXAMPLE_PERIOD, state.example_frame())
        ss["period"], ss["unit_name"] = state.EXAMPLE_PERIOD, state.EXAMPLE_NAME
        st.rerun()


# ---- Summary -----------------------------------------------------------------------------------
def summary(ctx: state.Context) -> None:
    page_header(
        "Summary",
        "Total emissions for the chosen period, how far to believe them, and where they come from.",
        read="The trust index runs from 0 to 1: the share of emissions backed by measured data, with "
        "estimated and default data counting for less. The range is an indicative band, not a measured error.",
    )
    if ctx.is_example:
        callout("info", "Example data.", EXAMPLE_NOTE)
    _problems(ctx)
    if _need_data(ctx, "summary"):
        return
    fp, cfg = ctx.footprint, ctx.cfg
    total = fp.total_co2e_t
    index = trust_module.trust_index(fp, cfg)
    u = trust_module.total_uncertainty(fp, cfg)
    band = trust_module.band(index, cfg)
    interval = trust_module.interval(fp, cfg)
    rows = hotspot.pareto(fp)
    top = rows[0]
    items = [
        ("Total emissions", f"{fmt_t(total)} tCO2e", ctx.period),
        (
            "Data trust index",
            f"{float(index):.2f}" if index is not None else "n/a",
            f"{band} trust",
        ),
        (
            "Indicative range",
            f"{fmt_t(interval[0])} to {fmt_t(interval[1])}" if interval else "n/a",
            f"plus or minus {fmt_pct(u)}",
        ),
        ("Largest hotspot", top.name, f"{fmt_pct(top.share)} of emissions"),
    ]
    stat_strip(items)
    if ctx.sales_lakh:
        st.caption(f"Emissions per INR lakh of sales: {float(total / ctx.sales_lakh):,.3f} tCO2e.")

    section("Emissions by activity", "Colour shows how well each number is known")
    fig = go.Figure()
    for cls in ("measured", "estimated", "default"):
        sub = [r for r in rows if r.data_class == cls]
        if not sub:
            continue
        fig.add_bar(
            y=[r.name for r in sub],
            x=[float(r.co2e_t) for r in sub],
            orientation="h",
            name=cls.capitalize(),
            marker_color=CLASS_COLOURS[cls],
            text=[fmt_pct(r.share) for r in sub],
            textposition="outside",
            hovertemplate="%{y}: %{x:,.2f} tCO2e<extra>" + cls + "</extra>",
        )
    fig.update_layout(
        height=120 + 46 * len(rows),
        xaxis_title="tCO2e",
        yaxis={"autorange": "reversed"},
        legend={"orientation": "h", "y": 1.12},
        barmode="stack",
    )
    show(fig)

    section("How far to believe it")
    contrib = trust_module.variance_contributions(fp, cfg)
    biggest = max(contrib, key=contrib.get)
    act = fp.results[biggest].activity
    if act.data_class != "measured":
        callout(
            "info",
            "Improve this data first.",
            f"{act.name} ({act.data_class}) is {fmt_pct(contrib[biggest], 0)} of the total uncertainty. "
            "Weighing deliveries, logging running hours or keeping invoices for it would shrink the range most.",
        )
    flags = trust_module.flag_counts(fp)
    for flag, n in flags.items():
        callout(
            "warn",
            "Assumption.",
            f"{trust_module.FLAG_TEXT.get(flag, flag)} ({n} activit{'y' if n == 1 else 'ies'})",
        )
    render(trust_band_badge(band))
    if cfg.status == "placeholder":
        st.caption(PLACEHOLDER_NOTE)
    st.caption(SCOPE_NOTE + " " + ESTIMATE_NOTE)


# ---- Hotspots ----------------------------------------------------------------------------------
def hotspots(ctx: state.Context) -> None:
    page_header(
        "Hotspots",
        "Which activities cause most of the emissions, and what each costs in rupees and in emissions.",
        compared="Activities within this unit, largest first. Not compared with other units.",
        read="The few activities up to the 80% line are the vital few. A hotspot is a priority for attention, "
        "not a verdict on how efficient the unit is.",
    )
    _problems(ctx)
    if _need_data(ctx, "hotspots"):
        return
    fp = ctx.footprint
    rows = hotspot.pareto(fp)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(
        x=[r.name for r in rows],
        y=[float(r.co2e_t) for r in rows],
        marker_color=[CLASS_COLOURS[r.data_class] for r in rows],
        name="tCO2e",
        hovertemplate="%{x}: %{y:,.2f} tCO2e<extra></extra>",
    )
    fig.add_scatter(
        x=[r.name for r in rows],
        y=[float(r.cumulative_share) * 100 for r in rows],
        mode="lines+markers",
        name="Cumulative share",
        line={"color": "#14532d"},
        secondary_y=True,
    )
    # the 80% line is its own trace: add_hline on a secondary axis syncs its ticks to the primary axis
    fig.add_scatter(
        x=[r.name for r in rows],
        y=[80] * len(rows),
        mode="lines",
        name="80% of emissions",
        line={"color": "#9aa39e", "dash": "dash"},
        hoverinfo="skip",
        secondary_y=True,
    )
    top_bar = max(float(r.co2e_t) for r in rows) or 1.0
    fig.update_yaxes(
        title_text="tCO2e", range=[0, top_bar * 1.15], secondary_y=False, showgrid=True
    )
    fig.update_yaxes(
        title_text="Cumulative share (%)",
        range=[0, 105],
        tickmode="array",
        tickvals=[0, 20, 40, 60, 80, 100],
        showgrid=False,
        secondary_y=True,
    )
    fig.update_layout(height=380, legend={"orientation": "h", "y": 1.12})
    show(fig)
    st.caption("Bar colour: green Measured, blue Estimated, amber Default.")

    section("Hotspot table")
    cols = [
        Column("Activity"),
        Column("tCO2e", numeric=True),
        Column("Share", numeric=True),
        Column("Cumulative", numeric=True),
        Column("Data class"),
        Column("Cost", numeric=True, note="INR"),
        Column("Cost share", numeric=True),
        Column("INR per tCO2e", numeric=True),
        Column("Reading"),
    ]
    body = []
    for r in rows:
        name = name_cell(r.name, badge("Vital few", "accent") if r.vital_few else "")
        body.append(
            [
                name,
                fmt_t(r.co2e_t),
                fmt_pct(r.share),
                fmt_pct(r.cumulative_share),
                Html(data_class_badge(r.data_class)),
                fmt_inr(r.cost_inr) if r.cost_inr is not None else None,
                fmt_pct(r.cost_share) if r.cost_share is not None else None,
                fmt_inr(r.inr_per_tco2e) if r.inr_per_tco2e is not None else None,
                r.reading or None,
            ]
        )
    render(table_html(cols, body))
    if not hotspot.cost_complete(fp):
        st.caption(
            "Costs are missing for some activities, so cost shares cover only those with a cost."
        )

    section("Suggestions", "From published MSME work; not engineering advice")
    equipment = {a.name: a.equipment for a in ctx.activities}
    recs = recommend.recommend(rows, equipment)
    if not recs:
        st.caption(
            "No rule matches these hotspots yet. Tag the equipment on the Data entry page to get suggestions."
        )
    for r in recs:
        tail = f" Caution: {r.caution}" if r.caution else ""
        st.markdown(f"- **{r.hotspot}.** {r.action}{tail} *(source: {r.sources})*")


# ---- What-if -----------------------------------------------------------------------------------
def _scenario_form(ctx: state.Context) -> None:
    lib = default_library()
    names = [a.name for a in ctx.activities]
    fuels = [a.name for a in ctx.activities if a.item_id != ELECTRICITY_ITEM]
    kind = st.selectbox(
        "Type of change",
        [
            "Use less of an activity",
            "Switch part of a fuel to another fuel",
            "Replace some grid electricity",
        ],
        key="scenario_kind",
    )
    with st.form("scenario_form", clear_on_submit=False):
        if kind == "Use less of an activity":
            target = st.selectbox("Activity", names)
            pct = st.slider("Use this much less (%)", 0, 100, 10)
            built = lambda: whatif.ActivityChange(target, Decimal(pct))  # noqa: E731
        elif kind == "Switch part of a fuel to another fuel":
            source = st.selectbox("From", fuels) if fuels else None
            to_names = {f.name: f.id for f in lib.fuels}
            to_name = st.selectbox("To", list(to_names))
            pct = st.slider("Share of the fuel's energy moved (%)", 0, 100, 25)
            price = st.number_input(
                "Price of the new fuel (INR per kg, 0 if unknown)", min_value=0.0, value=0.0
            )
            built = lambda: whatif.FuelSwitch(  # noqa: E731
                source or "",
                Decimal(pct),
                to_names[to_name],
                Decimal(str(price)) if price > 0 else None,
                to_name,
            )
        else:
            pct = st.slider("Share of grid electricity replaced (%)", 0, 100, 20)
            ef = st.number_input(
                "Emission factor of the replacement (tCO2 per MWh, 0 = emission-free)",
                min_value=0.0,
                value=0.0,
            )
            cost = st.number_input(
                "Cost of the replacement (INR per kWh, 0 = unknown or free)",
                min_value=0.0,
                value=0.0,
            )
            built = lambda: whatif.ElectricityShift(  # noqa: E731
                Decimal(pct), Decimal(str(ef)), Decimal(str(cost)) if cost > 0 else None
            )
        if st.form_submit_button("Add this scenario"):
            st.session_state["scenarios"].append(built())
            st.rerun()


def what_if(ctx: state.Context) -> None:
    page_header(
        "What-if",
        "Try a change to this unit's inputs and see what it does to emissions and energy cost, before spending money.",
        read="Scenarios are applied in the order listed, so overlapping changes are not double counted. "
        "Capital cost and electricity banking are not included.",
    )
    _problems(ctx)
    if _need_data(ctx, "whatif"):
        return
    ss = st.session_state
    section("Scenarios")
    if not ss["scenarios"]:
        st.caption("No scenarios yet. Add one below.")
    for i, s in enumerate(list(ss["scenarios"])):
        c1, c2 = st.columns([8, 1], vertical_alignment="center")
        c1.markdown(f"**{i + 1}.** {s.title()}")
        if c2.button("Remove", key=f"rm_scenario_{i}"):
            ss["scenarios"].pop(i)
            st.rerun()
    _scenario_form(ctx)

    if not ss["scenarios"]:
        return
    try:
        singles = [whatif.run(ctx.activities, [s]) for s in ss["scenarios"]]
        combined = whatif.run(ctx.activities, ss["scenarios"])
    except whatif.ScenarioError as exc:
        callout("danger", "A scenario cannot be applied.", str(exc))
        return

    section("Results", "Per period; avoided emissions are positive")
    body = [
        [
            o.titles[0],
            fmt_t(o.avoided_co2e_t),
            f"{float(o.pct_of_total):.1f}%",
            fmt_inr(o.cost_saved_inr),
        ]
        for o in singles
    ]
    if len(singles) > 1:
        body.append(
            [
                "All scenarios together",
                fmt_t(combined.avoided_co2e_t),
                f"{float(combined.pct_of_total):.1f}%",
                fmt_inr(combined.cost_saved_inr),
            ]
        )
    render(
        table_html(
            [
                Column("Scenario"),
                Column("tCO2e avoided", numeric=True),
                Column("% of total", numeric=True),
                Column("Energy cost saved", numeric=True, note="INR"),
            ],
            body,
        )
    )

    acts, extra_t, _ = whatif.apply_all(ctx.activities, ss["scenarios"])
    from greeneis.engine import calculate

    before, after = calculate(ctx.activities), calculate(acts)
    fig = go.Figure()
    for r in before.results:
        fig.add_bar(name=r.activity.name, x=["Before"], y=[float(r.co2e_t)])
    for r in after.results:
        fig.add_bar(
            name=r.activity.name,
            x=["After"],
            y=[float(r.co2e_t)],
            showlegend=r.activity.name not in {b.activity.name for b in before.results},
        )
    if extra_t:
        fig.add_bar(name="Replacement source", x=["After"], y=[float(extra_t)])
    fig.update_layout(
        barmode="stack", height=360, yaxis_title="tCO2e", legend={"orientation": "h", "y": -0.2}
    )
    show(fig)

    with st.expander("Abatement cost (needs an investment figure)"):
        st.caption(
            "(annualised investment minus annual energy saving) divided by tonnes avoided per year."
        )
        a, b = st.columns(2)
        invest = a.number_input(
            "Annualised investment (INR per year)", min_value=0.0, value=0.0, key="abate_inv"
        )
        months = b.number_input(
            "Months covered by this period", min_value=1, value=1, key="abate_months"
        )
        if invest > 0 and combined.avoided_co2e_t > 0 and combined.cost_saved_inr is not None:
            factor = Decimal(12) / Decimal(int(months))
            per_t = whatif.abatement_cost(
                Decimal(str(invest)),
                combined.cost_saved_inr * factor,
                combined.avoided_co2e_t * factor,
            )
            verdict = "pays for itself" if per_t < 0 else "costs money per tonne avoided"
            st.markdown(
                f"**INR {per_t:,.0f} per tCO2e** ({verdict}), if this period repeats across a year."
            )


# ---- Report ------------------------------------------------------------------------------------
def report(ctx: state.Context) -> None:
    page_header(
        "Report",
        "A one-page summary to share with a buyer, a lender or your own team.",
        read="It always prints the method, the data classes and the trust index, so it cannot be used to overstate performance.",
    )
    _problems(ctx)
    if _need_data(ctx, "report"):
        return
    outcomes = []
    for s in st.session_state["scenarios"]:
        try:
            outcomes.append(whatif.run(ctx.activities, [s]))
        except whatif.ScenarioError:
            continue
    text = report_module.build_report(ctx.unit_name, ctx.period, ctx.activities, ctx.cfg, outcomes)
    if ctx.is_example:
        callout("info", "Example data.", EXAMPLE_NOTE)
    st.download_button(
        "Download the report (Markdown)",
        text,
        file_name="greeneis_report.md",
        mime="text/markdown",
        key="dl_report",
    )
    section("Preview")
    with st.container(border=True):
        st.markdown(text)
