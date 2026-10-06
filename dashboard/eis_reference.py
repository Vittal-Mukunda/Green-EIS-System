"""The reference pages: the metrics guide and the about page. They explain; they do not compare."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from components.markup import esc, render
from eis_common import Ctx, colour_key, header, kpi_title, people_of, section

from gauge.db.session import session_scope
from gauge.viewdata import (
    CAPABILITIES,
    GLOSSARY,
    LIMITS,
    METRIC_NOTES,
    MOVEMENT_TOLERANCE_PCT,
    NEGLIGIBLE_SPREAD_PCT,
    RULE_NOTES,
    explain_value,
    fmt_number,
    headline_counts,
    kpi_matrix,
    kpi_years,
    metric_catalog,
    pretty_unit,
)
from gauge.viewdata_ui import formula_latex

# ---- Metrics guide ---------------------------------------------------------------------------------
UNITS_USED = (
    ("₹ crore", "Ten million rupees, the unit of revenue."),
    ("GJ", "Gigajoule, a unit of energy. 1 GJ is about 278 kilowatt-hours."),
    ("tCO2e", "Tonnes of carbon dioxide equivalent, a unit of greenhouse-gas emissions."),
    ("kL", "Kilolitre, 1,000 litres of water."),
    ("t", "Tonne, 1,000 kilograms."),
)


def page_metrics(ctx: Ctx) -> None:
    with session_scope(ctx.engine) as s:
        years = kpi_years(s)
    people = people_of(ctx)
    header(
        "Metrics guide",
        "What each number means, in plain words, with a worked example from a real company.",
        "Nothing: this page explains the metrics used on every other page.",
        "Open a metric to see what it measures, how it is computed, which direction is good, and what "
        "to watch out for.",
    )
    section("Explain any value", "choose a metric and type a value")
    catalog = [m for m in metric_catalog(ctx.indicators) if m["kind"] == "derived"]
    labels = {kpi_title(m["label"], m["unit"]): m for m in catalog}
    left, right = st.columns(2)
    water = next((i for i, m in enumerate(labels.values()) if m["code"] == "water_intensity"), 0)
    chosen = labels[left.selectbox("Metric", list(labels), index=water, key="explain_metric")]
    value = right.number_input("Value", min_value=0.0, value=498.0, step=1.0, key="explain_value")
    st.success(explain_value(chosen["code"], float(value)))
    notes = METRIC_NOTES[chosen["code"]]
    st.caption(f"{notes['reading']} {notes['caution']}")
    section(
        "The five metrics",
        "each is an intensity or a share, so companies of different size can be compared",
    )
    example = None
    if years:
        with session_scope(ctx.engine) as s:
            example = kpi_matrix(s, years[-1], ctx.indicators)
    indicator_labels = {i.code: i.label for i in ctx.indicators.indicators}
    specs = {k.code: k for k in ctx.indicators.kpis}
    for i, m in enumerate(catalog):
        notes = METRIC_NOTES[m["code"]]
        worked = ""
        if example is not None and not example.empty:
            part = example[(example["kpi"] == m["code"]) & (example["data check"] == "")]
            if not part.empty:
                row = part.iloc[len(part) // 2]
                worked = (
                    f"{people.label(row['code'])} reported {fmt_number(row['value'])} {m['unit']} in {years[-1]}. "
                    + explain_value(m["code"], float(row["value"]), row["sector median"])
                )
        with st.expander(f"{m['label']} ({m['unit']})", expanded=i == 0):
            render(
                '<div class="eis-guide">'
                f'<div><div class="k">What it measures</div><div class="v">{esc(notes["means"])}</div></div>'
                f'<div><div class="k">Unit</div><div class="v">{esc(m["unit"])} · {esc(m["better"])} is better</div></div>'
                "</div>"
            )
            spec = specs.get(m["code"])
            if spec is not None:
                st.latex(formula_latex(spec.formula, indicator_labels))
            example_html = (
                f'<div class="full"><div class="k">Worked example</div><div class="v">{esc(worked)}</div></div>'
                if worked
                else ""
            )
            render(
                '<div class="eis-guide">'
                f'<div class="full"><div class="k">How it is computed</div><div class="v">{esc(notes["how"])}</div></div>'
                f'<div><div class="k">How to interpret it</div><div class="v">{esc(notes["reading"])}</div></div>'
                f'<div><div class="k">Important limitation</div><div class="v">{esc(notes["caution"])}</div></div>'
                f"{example_html}</div>"
            )
    section("The figures the metrics are computed from")
    inputs = pd.DataFrame(
        [
            {
                "Figure": i.label,
                "Unit": pretty_unit(i.unit),
                "What it is": METRIC_NOTES[i.code]["means"],
                "Watch out": METRIC_NOTES[i.code]["caution"],
            }
            for i in ctx.indicators.indicators
        ]
    )
    st.dataframe(inputs, hide_index=True, width="stretch")
    section("Units used")
    rows = "".join(
        f'<tr><td class="firstcol"><b>{esc(unit)}</b></td><td>{esc(text)}</td></tr>'
        for unit, text in UNITS_USED
    )
    render(
        f'<div class="eis-tablewrap"><table class="eis-table"><tbody>{rows}</tbody></table></div>'
    )


# ---- About -----------------------------------------------------------------------------------------
DOES = (
    "Standardises the environmental figures of BRSR filings into one set of units.",
    "Validates every figure with fixed rules, and flags what fails.",
    "Computes five metrics with exact arithmetic, the same way every time.",
    "Places each company among others in its own sector, on intensities and shares.",
    "Shows, for any figure, the filing, its SHA-256 fingerprint and the retrieval date.",
    "Records a person's check of a figure against its filing, with name and date.",
)
DOES_NOT = (
    "Rank raw emissions or any total that grows with company size.",
    "Rate a company's environmental performance, or give an ESG score.",
    "Compare sectors with each other.",
    "Treat a data check as a finding that a company misreported.",
    "Use a language model on the evidence pages: plain-language readings come from fixed templates.",
    "Give a legal finding of compliance, or financial advice.",
    "Use an external industry benchmark: medians come from this study sample.",
)
DATA_SOURCES = (
    "BRSR filings (Principle 6 environmental indicators) of listed companies, downloaded by hand and read from their XBRL files.",
    "Where an XBRL unit label was wrong, the system corrected it from the PDF filing; each correction is recorded.",
    "Each filing is kept with its file name, SHA-256 fingerprint and retrieval date.",
    "Disclosures are self-reported by the companies.",
)


def _bullets(items) -> str:
    rows = "".join(f'<li style="margin:5px 0;font-size:13.5px">{esc(i)}</li>' for i in items)
    return f'<ul style="margin:0;padding-left:18px">{rows}</ul>'


def page_about(ctx: Ctx) -> None:
    with session_scope(ctx.engine) as s:
        counts = headline_counts(s)
        years = kpi_years(s)
    people = people_of(ctx)
    header(
        "About this system",
        "What the system can do, how to read a position, what the words mean, and where it stops.",
        "Nothing: this page describes the system.",
    )
    section("What Green EIS is")
    render(
        '<div class="eis-grid cols-2">'
        '<div class="eis-card"><div class="eis-label">Green EIS</div>'
        '<p style="margin:6px 0 0;font-size:13.5px;line-height:1.55">An evidence-first system that turns the '
        "sustainability disclosures (BRSR) of large listed Indian companies into comparable, traceable "
        "environmental metrics. Its purpose is not the chart: it is the chain of assurance behind each "
        "number, from the filing to the figure to the human check.</p></div>"
        '<div class="eis-card"><div class="eis-label">What an EIS is</div>'
        '<p style="margin:6px 0 0;font-size:13.5px;line-height:1.55">An enterprise information system collects '
        "data, standardises and validates it, and gives managers a reliable view for monitoring, comparison "
        "and decisions. Green EIS applies that idea to sustainability disclosures: an executive overview, "
        "drill-down to company and figure, management by exception, and an audit trail.</p></div></div>"
    )
    section("What it does and does not do")
    render(
        '<div class="eis-grid cols-2">'
        '<div class="eis-card"><div class="eis-label" style="color:var(--accent)">The system does</div>'
        f'<div style="margin-top:6px">{_bullets(DOES)}</div></div>'
        '<div class="eis-card"><div class="eis-label" style="color:var(--warn)">The system does not</div>'
        f'<div style="margin-top:6px">{_bullets(DOES_NOT)}</div></div></div>'
    )
    section("Limitations", "read these before using a figure")
    limits = "".join(f'<div style="margin:4px 0">{esc(limit)}</div>' for limit in LIMITS)
    render(
        '<div class="eis-callout warn"><span class="eis-icon" aria-hidden="true">warning</span>'
        f"<div>{limits}</div></div>"
    )
    section("Pilot scope")
    scope = (
        ("Companies", str(counts["companies"]), "large listed Indian companies"),
        ("Sectors", str(len(people.sectors())), ", ".join(people.sectors())),
        ("Fiscal years", str(len(years)), ", ".join(years) if years else "none"),
        ("Filings", str(counts["filings"]), "each with a SHA-256 fingerprint"),
    )
    cards = "".join(
        f'<div class="eis-card flat"><div class="eis-kpi"><span class="eis-kpi-label">{esc(k)}</span>'
        f'<span class="eis-kpi-value">{esc(v)}</span><span class="eis-kpi-sub">{esc(n)}</span></div></div>'
        for k, v, n in scope
    )
    render(f'<div class="eis-grid cols-4">{cards}</div>')
    section("Data sources and methodology")
    method = (
        "Standardise units, then validate with fixed rules (a part cannot exceed its whole, and so on).",
        "Compute five metrics with exact decimal arithmetic: three intensities per ₹ crore of revenue and two shares.",
        "Take the median, P25 and P75 of each sector from this sample, using only figures that pass the checks.",
        f"Place a company in its sector's better, middle or weaker third; within {NEGLIGIBLE_SPREAD_PCT:g}% of the median there is no clear difference.",
        f"Call a year-on-year change under {MOVEMENT_TOLERANCE_PCT:g}% about the same.",
    )
    render(
        '<div class="eis-grid cols-2">'
        f'<div class="eis-card flat"><div class="eis-label">Data sources</div>{_bullets(DATA_SOURCES)}</div>'
        f'<div class="eis-card flat"><div class="eis-label">Methodology</div>{_bullets(method)}</div></div>'
    )
    section("What the system does for you")
    st.dataframe(
        pd.DataFrame(
            [
                {"Capability": c, "Where": ", ".join(v), "What it does for you": d}
                for c, v, d in CAPABILITIES
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    section("How to read a position")
    for line in (
        "Every KPI is an intensity (per ₹ crore of revenue) or a share, so companies of different size can be compared. Raw totals are never ranked.",
        "A company is placed among the companies in its **own sector** that pass the data-quality checks: better third, middle third or weaker third, taking the KPI's direction into account (lower is better for intensities, higher for the shares).",
        f"When a sector's values lie within {NEGLIGIBLE_SPREAD_PCT:g}% of their median the system says **no clear difference** instead of ranking them.",
        "A figure that fails an error check, such as more waste recovered than generated, is shown but **not ranked** and is left out of the sector median. A breach of under 1% is treated as rounding and the figure is still ranked, though the register and the compliance check still report it.",
        f"A year-on-year change under {MOVEMENT_TOLERANCE_PCT:g}% is called **about the same**.",
    ):
        st.markdown(f"- {line}")
    colour_key()
    section("What the data-quality flags mean")
    st.dataframe(
        pd.DataFrame([{"Rule": r, "What it checks": d} for r, d in RULE_NOTES.items()]),
        hide_index=True,
        width="stretch",
    )
    section("Glossary")
    for term, definition in GLOSSARY.items():
        st.markdown(f"**{term}.** {definition}")
