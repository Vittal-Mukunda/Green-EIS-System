"""The Overall Findings page: the whole project on one page, traceable to its evidence.

Everything here is generated from the gap registry, the result files and `findings.summary`, the same
sources the analysis pages use, so the numbers agree with them by construction. The page states what was
demonstrated, what is tentative and what is unresolved, and does not draw links between gaps that the
data do not support.
"""

from __future__ import annotations

from collections import Counter

import findings
import gap_data
import sections
import streamlit as st
import vocab
from components.alerts import ESTIMATE_NOTE, callout
from components.citations import origin_cell_html, page_link_html
from components.data_table import Column, Html, table_html
from components.kpi_card import stat_strip
from components.markup import render, section
from components.navigation import link_button
from components.page_header import page_header
from components.plain import pct
from components.research import status_badge

from greeneis import gaps
from greeneis.national import load_national


def _link(g: gaps.Gap) -> Html:
    return Html(page_link_html(f"Gap {g.number}", vocab.slug(g.nav_label)))


def _origin(g: gaps.Gap) -> Html:
    return Html(origin_cell_html(g))


def overall_findings() -> None:
    page_header(
        "Overall Findings",
        "What was investigated, what was found, what remains unresolved, and where each conclusion comes "
        "from. Every figure is read from the same result files as the analysis pages.",
        read="Statuses are deliberately modest: they follow the strength of the evidence, not whether a "
        "feature was built.",
        page="Overall Findings",
    )
    head = gap_data.result(gap_data.MAIN_FILE)
    ev = gap_data.evidence()
    textile = gap_data.result(gap_data.TEXTILE_FILE)
    nat = load_national()
    cstep, ceew = nat["cstep_informal_total"], nat["ceew_informal_total"]
    off, total = findings.cstep_agreement()
    summaries = {g.number: findings.summary(g.number) for g in gaps.GAPS}
    counts = Counter(g.status for g in gaps.GAPS)

    # ---- A. executive summary ----------------------------------------------------------------
    section("A. Executive summary")
    st.markdown(
        f"**Problem.** Estimates of emissions from India's informal manufacturing sector are built "
        f"top-down and disagree ({cstep.low:g} against {ceew.low:g} {cstep.unit}, {cstep.year}); both "
        "authors ask for firm-level fuel data that does not exist. **Purpose of GreenEIS.** A system through "
        "which a small unit records its own energy data and sees emissions, a trust label on every number, "
        "hotspots, a cost link and what-if scenarios. **Data.** "
        + (
            f"{head.factories:,} small factories from the ASI 2023-24 returns ({head.records:,} fuel "
            f"records, {head.states} states), the published national estimates, CSTEP's petroleum tables "
            "and the project's factor library."
            if head
            else "the real results file is not available."
        )
    )
    if head:
        st.markdown(
            "**Main findings.**\n"
            f"- {summaries[2].key_finding}\n"
            f"- {summaries[1].key_finding}\n"
            f"- {summaries[3].key_finding}\n"
            f"- {summaries[4].key_finding}"
        )
    st.markdown(
        "**Most important limitations.** The ASI returns are reported, not metered, and cover registered "
        "factories, not informal units; the data are one year; only electricity, coal and gas carry a "
        "quantity; the trust values are uncalibrated design choices; and gaps 5 to 7 have no data that "
        "could test them."
    )
    callout("warn", "Standing note.", ESTIMATE_NOTE)

    # ---- B. coverage ---------------------------------------------------------------------------
    section("B. Research coverage")
    stat_strip(
        [
            ("Research gaps", f"{len(gaps.GAPS)}", "each with its own analysis page"),
            (
                "Partially addressed",
                f"{counts.get('partial', 0)}",
                ", ".join(g.id for g in gaps.GAPS if g.status == "partial") or "none",
            ),
            (
                "Insufficient data",
                f"{counts.get('insufficient', 0)}",
                ", ".join(g.id for g in gaps.GAPS if g.status == "insufficient") or "none",
            ),
            (
                "Addressed with evidence",
                f"{counts.get('addressed', 0)}",
                "none yet"
                if not counts.get("addressed")
                else ", ".join(g.id for g in gaps.GAPS if g.status == "addressed"),
            ),
        ]
    )
    stat_strip(
        [
            (
                "Factories analysed",
                f"{head.factories:,}" if head else "n/a",
                "ASI 2023-24, small, open",
            ),
            ("Fuel records", f"{head.records:,}" if head else "n/a", "electricity, coal, gas"),
            ("Companies", "0", "no company reports are used"),
            (
                "Reporting periods",
                "1 survey year",
                "plus published estimates for 2005-06 to 2015-16",
            ),
            (
                "Analyses with data",
                f"{sum(s.available for s in summaries.values())} of {len(gaps.GAPS)}",
                "result file or library present",
            ),
        ]
    )

    # ---- C. matrix -----------------------------------------------------------------------------
    section("C. Consolidated findings matrix", "One row per research gap")
    render(
        table_html(
            [
                Column("Gap"),
                Column("Research gap"),
                Column("Originating paper"),
                Column("Research question"),
                Column("Data and method"),
                Column("Key finding"),
                Column("Supporting evidence"),
                Column("Status"),
                Column("Limitation"),
                Column("View analysis"),
            ],
            [
                [
                    g.id,
                    g.short,
                    _origin(g),
                    findings.QUESTION_SHORT[g.number],
                    findings.DATA_SHORT[g.number],
                    summaries[g.number].short,
                    summaries[g.number].supporting,
                    Html(status_badge(g.status, g.status_text)),
                    summaries[g.number].limitation or g.limits[0],
                    _link(g),
                ]
                for g in gaps.GAPS
            ],
            compact=True,
        )
    )
    st.caption(
        "The matrix is a summary. The full sentence for each gap, with its numbers, is below and on the "
        "gap's own page."
    )
    cols = st.columns(len(gaps.GAPS))
    for col, g in zip(cols, gaps.GAPS, strict=True):
        with col:
            link_button(f"Gap {g.number} →", g.nav_label, f"find_{g.slug}", list(vocab.PAGES))
    for g in gaps.GAPS:
        with st.expander(f"Gap {g.number}: {g.title}"):
            s = summaries[g.number]
            st.markdown(f"**Key finding.** {s.key_finding}")
            st.markdown(f"**Data and method.** {s.data_and_method}")
            st.markdown(f"**Status.** {g.status_text}. {g.status_reason}")

    # ---- D. key quantitative findings ------------------------------------------------------------
    section("D. Key quantitative findings", "Each with its unit, denominator and period")
    if head and ev:
        rows = [
            [
                "Small factories analysed",
                f"{head.factories:,}",
                "factories",
                "ASI 2023-24",
                "open, at most 50 persons",
            ],
            [
                "Bill-based estimate, median error",
                pct(head.estimated_median),
                "of reported quantity",
                "ASI 2023-24",
                f"{head.records:,} records; mostly electricity",
            ],
            [
                "Sector-average guess, median error",
                pct(head.default_median),
                "of reported quantity",
                "ASI 2023-24",
                f"{head.records:,} records",
            ],
            [
                "Default error, 90th percentile",
                pct(head.default_q90),
                f"against an assumed {pct(head.placeholder_default)}",
                "ASI 2023-24",
                "records",
            ],
            [
                "Nominal 90% interval coverage",
                pct(head.coverage),
                "of factories",
                "ASI 2023-24",
                "pooled over four profiles",
            ],
            [
                "Top hotspot kept (bills only)",
                pct(head.top1_kept),
                "of factories",
                "ASI 2023-24",
                f"{head.rows_by_test['H4']:,} with more than one fuel",
            ],
            [
                "Small factories with spend but no quantity",
                f"{ev['coverage']['spend_without_quantity_any_line']:,}",
                "factories",
                "ASI 2023-24",
                f"of {ev['coverage']['small_factories']:,} small factories",
            ],
            [
                "CSTEP Table 8 cells that disagree",
                f"{off}",
                "cells",
                "2008-09 to 2015-16",
                f"of {total} recomputed",
            ],
        ]
        render(
            table_html(
                [
                    Column("Metric"),
                    Column("Value", numeric=True),
                    Column("Unit or denominator"),
                    Column("Period"),
                    Column("Basis"),
                ],
                rows,
            )
        )
        sections.trust_proxy_error(head)
    else:
        callout("warn", "Result files not available.", "The quantitative findings cannot be shown.")

    # ---- E. cross-gap insights -------------------------------------------------------------------
    section("E. Cross-gap insights", "Only connections the data support")
    notes = []
    if head and ev:
        weakest = max(head.fuels, key=lambda f: f.estimated_median)
        cl = ev["cost_link"]
        polluter = max(cl, key=lambda r: r["co2e_share"] - r["spend_share"])
        if weakest.item == polluter["item"]:
            notes.append(
                f"**Gaps 1, 2 and 4 point to the same fuel.** {weakest.name} is the fuel whose bill-based "
                f"estimate is least accurate (median error {pct(weakest.estimated_median)}, Gap 2) and also "
                f"the fuel that is a bigger share of emissions ({pct(polluter['co2e_share'], 1)}) than of "
                f"spend ({pct(polluter['spend_share'], 1)}, Gap 4). The fuel whose figure is hardest to "
                "work out from a bill is the one a bill-only view underrates."
            )
    notes.append(
        "**Gaps 1, 2 and 3 share one limit.** All three rest on the same three fuel lines of one survey "
        "year, so a factory has at most three sources and liquid fuels are absent. Their results are "
        "not independent confirmations of each other."
    )
    notes.append(
        "**Gaps 5, 6 and 7 are not connected to the others by data.** They have no result file, and no "
        "link between them and gaps 1 to 4 is drawn."
    )
    st.markdown("\n\n".join(notes))

    # ---- F. contributions and unresolved ---------------------------------------------------------
    section("F. Contributions and unresolved questions")
    if head:
        st.markdown("**Demonstrated by the data** (ASI 2023-24; see each page for the caveats)")
        st.markdown(
            f"- A fuel quantity worked out from a bill and a typical state price is far closer to the "
            f"reported quantity than a sector-average guess ({pct(head.estimated_median)} against "
            f"{pct(head.default_median)} median error; the ordering held in every declared variation).\n"
            f"- The placeholder uncertainty ranges are wrong, in different directions for different fuels.\n"
            f"- CSTEP's petroleum table disagrees with its own factors in {off} of {total} cells."
        )
    st.markdown("**Methodological and system contributions**")
    st.markdown(
        "- A calculation engine that reproduces the reference document's hand-worked example and CSTEP's "
        "published arithmetic, with every factor stored with value, unit, source and year.\n"
        "- A pre-specified study harness: hypotheses, thresholds and the sensitivity runs were fixed "
        "before the real data were run, and no threshold has been changed since.\n"
        "- One registry for the research gaps and one for the references, so pages cannot disagree."
    )
    st.markdown("**Tentative or limited**")
    tentative = [
        f"The priority rule (fix the largest source first) rests on {head.h5_rows} factories and its interval nearly touches zero."
        if head
        else "",
        "The trust index's link to error is largely structural: most factories have one fuel.",
        f"The textile cut is exploratory: H4 is '{textile.verdicts['H4']}' and H5 '{textile.verdicts['H5']}'."
        if textile
        else "",
    ]
    st.markdown("\n".join(f"- {t}" for t in tentative if t))
    st.markdown("**Unresolved**")
    st.markdown(
        "\n".join(
            f"- **Gap {g.number} ({g.status_text.lower()}).** {g.missing}"
            for g in gaps.GAPS
            if g.status in ("insufficient", "unresolved")
        )
    )
    st.markdown("**Future work that needs more data or methods**")
    st.markdown(
        "- Real unit-level audits (docs/DATA_TO_COLLECT.md), above all for textile wet processing.\n"
        "- A held-out ASI year and per-fuel calibration of the ranges.\n"
        "- Liquid-fuel quantities, which the ASI return does not hold.\n"
        "- A usability check and a buyer and lender review (protocol written, not run)."
    )

    # ---- G. traceability -------------------------------------------------------------------------
    section("G. Evidence traceability", "Gap, paper, data, method, result, page")
    render(
        table_html(
            [
                Column("Gap"),
                Column("Originating paper"),
                Column("Data source and variables"),
                Column("Method"),
                Column("Results in"),
                Column("Page"),
            ],
            [[g.id, _origin(g), *findings.TRACE[g.number][:3], _link(g)] for g in gaps.GAPS],
        )
    )
    st.caption(
        "Where the originating paper is 'none verified', the gap is the project's own reading; see "
        "References for how far each source was checked."
    )
    st.markdown("**Underlying results**")
    for name, label in (
        (gap_data.MAIN_FILE, "Main run (JSON)"),
        (gap_data.TEXTILE_FILE, "Textile cut, exploratory (JSON)"),
        (gap_data.EVIDENCE_FILE, "ASI facts for gaps 1, 3 and 4 (JSON)"),
    ):
        path = gap_data.source_file(name)
        if path is not None:
            st.download_button(
                label,
                path.read_bytes(),
                file_name=name,
                mime="application/json",
                key=f"dl_find_{name}",
            )
    link_button(
        "All sources and how far each was checked", "References", "find_refs", list(vocab.PAGES)
    )
