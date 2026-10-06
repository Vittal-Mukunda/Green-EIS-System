"""The evidence pages of the dashboard: everything that reads the filings and the computed metrics.

Each page opens with the same header (what it shows, what is being compared, how to read it), puts a
unit on every number, and shows companies by their real names unless the sidebar switch asks for the
masked codes. Nothing here calls a model, and nothing changes a calculation: the pages arrange
figures that `gauge.viewdata` has already computed.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import streamlit as st
from components.alerts import DATA_CHECK_NOTE, STUDY_SAMPLE_NOTE, callout
from components.data_quality_table import exceptions_html, movements_html
from components.empty_state import empty_state
from components.icons import PAGE_ICONS, icon
from components.kpi_card import chain_strip_html, stat_strip
from components.markup import esc, render
from components.navigation import link_button
from eis_analysis import (
    page_companies,
    page_compare,
    page_query,
    page_scorecard,
    page_sectors,
)
from eis_assurance import (
    page_compliance,
    page_filings,
    page_flags,
    page_verification,
)
from eis_common import (
    Ctx,
    colour_key,
    open_page,
    people_of,
    section,
)
from eis_reference import page_about, page_metrics

from gauge import vocab
from gauge.db.session import session_scope
from gauge.viewdata import (
    LIMITS,
    data_as_of,
    flag_register,
    headline_counts,
    kpi_matrix,
    kpi_years,
)
from gauge.viewdata_ui import figures_failing_checks, fmt_figure, largest_movements

# ---- Home ------------------------------------------------------------------------------------------
HOME_CARDS = (
    (
        "KPI scorecard",
        "Every company, every metric",
        "All companies against all five metrics, each placed within its own sector.",
    ),
    (
        "Companies",
        "One company",
        "Its figures, what they mean, how it compares, and the evidence behind them.",
    ),
    (
        "Sectors",
        "One sector",
        "The study-sample median and spread for each metric, and who needs attention.",
    ),
    ("Compare companies", "Compare companies", "Put the companies you choose side by side."),
    (
        "Query and chart",
        "Ask for the data you want",
        "Choose metrics, companies and years; the chart is chosen and explained.",
    ),
    (
        "Compliance check",
        "Check what each filing discloses",
        "Is the information there, and is it internally consistent? A monitoring view, not a legal finding.",
    ),
    (
        "Sources and filings",
        "Trace a number to its filing",
        "KPI, inputs, validation, filing and SHA-256 fingerprint.",
    ),
    (
        "Metrics guide",
        "Understand a metric",
        "What each number measures, its formula and its limits.",
    ),
)
HOME_PRINCIPLES = (
    (
        "stacks",
        "Compared within a sector",
        "Companies are placed among others in their own sector, on intensities and shares only. Raw "
        "emissions are never ranked, because they grow with company size.",
    ),
    (
        "rule",
        "A data check is not a ranking",
        "A figure that fails a check is shown and flagged for verification. It is not placed, and it is "
        "not a finding that a company misreported.",
    ),
    (
        "query_stats",
        "Medians come from this sample",
        "The median, P25 and P75 are computed from the companies in this study sample, not from an "
        "external industry benchmark.",
    ),
)


def page_home(ctx: Ctx) -> None:
    with session_scope(ctx.engine) as s:
        counts = headline_counts(s)
        asof = data_as_of(s)
        years = kpi_years(s)
        latest = years[-1] if years else None
        matrix = kpi_matrix(s, latest, ctx.indicators) if latest else pd.DataFrame()
        flags = flag_register(s)
    people = people_of(ctx)
    sectors = people.sectors()
    failing = figures_failing_checks(matrix)
    moves = largest_movements(matrix)
    n_checks = len(failing)

    status = (
        f"{n_checks} figure{'s' if n_checks != 1 else ''} with a data check in {latest}"
        if latest
        else "No metrics computed yet"
    )
    render(
        '<div class="eis-hero"><div><div class="sub">Green Executive Information System</div>'
        "<h1>Green EIS</h1><p>Evidence-first sustainability intelligence from BRSR disclosures. "
        "Every figure traces back to the filing it came from.</p></div>"
        '<div class="eis-hero-meta">'
        f'<div><div class="k">Latest fiscal year loaded</div><div class="v">{esc(asof["latest_fy"] or "none")}</div></div>'
        f'<div><div class="k">Latest filing retrieved</div><div class="v">{esc(asof["retrieved_on"] or "date not recorded")}</div></div>'
        f'<div><div class="k">Companies</div><div class="v">{counts["companies"]}</div></div>'
        f'<div><div class="k">Sectors</div><div class="v">{len(sectors)}</div></div>'
        f'<div style="grid-column:1/-1"><div class="k">Data status</div><div class="v">{esc(status)}</div></div>'
        "</div></div>"
    )
    st.markdown(
        f"**What is being compared.** {counts['companies']} large listed companies in "
        f"{len(sectors)} sectors ({', '.join(sectors)}) on five environmental metrics: energy, "
        "emissions and water used per ₹ crore of revenue, the renewable share of energy, and the "
        "waste recovery rate. Companies are compared with others in the same sector, because a "
        "cement works and a software company are not like for like."
    )
    stat_strip(
        [
            ("Companies", str(counts["companies"]), "in the pilot sample"),
            ("Sectors", str(len(sectors)), ", ".join(sectors)),
            ("Environmental KPIs", str(len(ctx.indicators.kpis)), "intensities and shares"),
            ("Filings loaded", str(counts["filings"]), ", ".join(years) if years else "none"),
            (
                "Figures with a data check",
                str(n_checks),
                f"in {latest}; shown, not ranked" if latest else "no metrics yet",
            ),
        ]
    )

    left, right = st.columns([1.1, 1], gap="medium")
    with left:
        section("Needs attention", f"{latest}" if latest else "")
        _needs_attention(ctx, people, failing, flags, latest)
    with right:
        section("What changed", f"{years[-2]} to {latest}" if len(years) > 1 else "")
        _what_changed(people, moves, years)

    section("Can I trust the numbers?", "the chain of assurance behind every figure")
    checked = counts["values checked by a person"]
    render(
        chain_strip_html(
            [
                (
                    "description",
                    "Filings",
                    str(counts["filings"]),
                    "BRSR filings loaded, each with a SHA-256 fingerprint",
                ),
                (
                    "dataset",
                    "Standardised",
                    str(counts["indicator values"]),
                    "reported figures, converted to standard units",
                ),
                (
                    "rule",
                    "Validated",
                    str(n_checks),
                    f"KPI figures failing a data check in {latest or 'the latest year'}",
                ),
                (
                    "calculate",
                    "Computed",
                    str(counts["KPI values"]),
                    "KPI values, deterministic arithmetic",
                ),
                (
                    "verified",
                    "Verified by a person",
                    f"{checked} of {counts['indicator values']}",
                    "figures compared with the filing",
                ),
            ]
        )
    )
    link_button("Trace a number to its filing →", "Sources and filings", "home_trace", ctx.pages)

    section("How to read this system")
    render(
        '<div class="eis-grid cols-3">'
        + "".join(
            f'<div class="eis-card flat"><div class="eis-card-head"><span class="eis-label">{icon(glyph)} {esc(title)}</span></div>'
            f'<div class="eis-meta" style="font-size:13px;color:var(--text-2);line-height:1.5">{esc(text)}</div></div>'
            for glyph, title, text in HOME_PRINCIPLES
        )
        + "</div>"
    )
    colour_key()

    section("Where to next")
    cards = [c for c in HOME_CARDS if c[0] in ctx.pages]
    for start in range(0, len(cards), 4):
        for col, (view, title, text) in zip(
            st.columns(4, gap="small"), cards[start : start + 4], strict=False
        ):
            with col, st.container(border=True, key=f"homecard_{vocab.slug(view)}"):
                render(
                    f'<div class="eis-card-title">{icon(PAGE_ICONS.get(view, "arrow_forward"))} {esc(title)}</div>'
                    f'<div class="eis-meta" style="margin-top:3px;min-height:3.2em">{esc(text)}</div>'
                )
                st.button(
                    "Open →", key=f"home_{vocab.slug(view)}", on_click=open_page, args=(view,)
                )
    with st.expander("Read this first: what this system does not tell you"):
        for limit in LIMITS:
            st.markdown(f"- {limit}")


def _needs_attention(
    ctx: Ctx, people, failing: pd.DataFrame, flags: pd.DataFrame, latest: str | None
) -> None:
    n = len(failing)
    if n == 0:
        callout(
            "ok",
            "Nothing fails a data check",
            f"No figure fails an automatic check in {latest or 'the latest year'}.",
        )
    else:
        items = [
            {
                "code": people.short(r["code"]),
                "fy": latest,
                "who": people.label(r["code"]),
                "what": r["label"],
                "value": fmt_figure(r["value"], r["unit"]),
                "unit": r["unit"],
                "why": r["reason"][:1].upper() + r["reason"][1:] + ".",
            }
            for r in failing.head(5).to_dict("records")
        ]
        more = (
            f'<div class="eis-meta" style="padding:8px 14px 12px">and {n - 5} more in the register</div>'
            if n > 5
            else ""
        )
        render(
            '<div class="eis-card flat" style="padding:0;overflow:hidden">'
            '<div style="padding:14px 16px 6px"><span class="eis-label">Needs attention</span>'
            f'<div class="eis-bignum" style="margin-top:4px">{n} <span style="font-size:15px;font-weight:560;'
            f'letter-spacing:0">figure{"s" if n != 1 else ""} require review</span></div></div>'
            f"{exceptions_html(items)}{more}</div>"
        )
        callout("info", "A data check is not a verdict.", DATA_CHECK_NOTE)
    missing = int((flags["rule"] == "missing_indicator").sum()) if not flags.empty else 0
    if missing:
        callout(
            "info",
            "Missing data is shown, not filled in.",
            f"{missing} flags record a figure or a whole filing that is not available for a company-year "
            "(for example a year whose filing has not been loaded).",
        )
    link_button(
        "View the data quality register →", "Data quality register", "home_register", ctx.pages
    )


def _what_changed(people, moves: pd.DataFrame, years: list[str]) -> None:
    if len(years) < 2:
        empty_state(
            "One year loaded",
            "Movements need two fiscal years of the same company.",
            "trending_flat",
        )
        return
    if moves.empty:
        empty_state(
            "No large movements",
            f"No metric moved by 10% or more between {years[-2]} and {years[-1]}.",
            "trending_flat",
        )
        return
    items = [
        {
            "who": people.label(r["code"]),
            "what": r["label"],
            "change": float(r["change %"]),
            "movement": r["movement"],
            "prev": fmt_figure(r["previous year"], r["unit"]),
            "now": fmt_figure(r["value"], r["unit"]),
            "unit": r["unit"],
        }
        for r in moves.to_dict("records")
    ]
    render(
        f'<div class="eis-card flat" style="padding:0;overflow:hidden">{movements_html(items)}</div>'
    )
    st.caption(
        "Largest changes of 10% or more against the previous year loaded. Better or worse is the direction "
        "of the metric, not a judgement of the company. " + STUDY_SAMPLE_NOTE.split(". ")[0] + "."
    )


EVIDENCE_PAGES: dict[str, Callable[[Ctx], None]] = {
    "Home": page_home,
    "Sectors": page_sectors,
    "KPI scorecard": page_scorecard,
    "Companies": page_companies,
    "Compare companies": page_compare,
    "Query and chart": page_query,
    "Compliance check": page_compliance,
    "Data quality register": page_flags,
    "Sources and filings": page_filings,
    "Data verification": page_verification,
    "Metrics guide": page_metrics,
    "About": page_about,
}
