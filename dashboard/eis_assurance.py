"""The assurance pages: compliance check, data quality register, sources and filings, data verification.

These are where the chain behind a number is visible: filing, source figures, validation, and the
human check. The system finding and the human decision are always shown apart, and a data check is
always a figure to verify, never a finding about the company.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from components.alerts import DATA_CHECK_NOTE, callout, toast
from components.data_quality_table import (
    compliance_matrix_html,
    register_table_html,
    rule_summary_html,
)
from components.empty_state import empty_state
from components.evidence_card import Check, check_groups_html
from components.filters import paginate
from components.kpi_card import stat_strip
from components.markup import esc, render
from components.provenance import chain_html, trace_steps
from components.status_badge import badge, status_mark
from eis_common import (
    STATUS_TEXT,
    Ctx,
    header,
    open_company,
    open_filing,
    open_verification,
    people_of,
    section,
    year_picker,
)

from gauge.db.session import session_scope
from gauge.viewdata import (
    CHECK_ORDER,
    CHECK_TITLES,
    CHECK_WHY,
    GLIDE_PATH,
    RULE_NOTES,
    VerificationError,
    compliance_checks,
    compliance_matrix,
    compliance_summary,
    filings_register,
    headline_counts,
    indicator_lineage,
    kpi_years,
    pretty_unit,
    record_verification,
    report_attributes,
)
from gauge.viewdata_ui import register_rows, source_trace

# ---- Compliance check ------------------------------------------------------------------------------
# What a pass reads as in each column of the matrix. Every other result has the same word across columns.
PASS_WORDS = {
    "Own filing": "Loaded",
    "Core figures": "Disclosed",
    "Boundary": "Stated",
    "Assurance": "Statement present",
    "Consistency": "Consistent",
}
OTHER_WORDS = {"attention": "Review required", "fail": "Check failed", "info": "Info", "n/a": "n/a"}
CHECK_GROUPS = (
    ("Filing and years", ("filing", "years")),
    ("BRSR core disclosure", ("core",)),
    ("Boundary", ("boundary",)),
    ("Assurance", ("assurance",)),
    ("Internal consistency", ("consistency", "units")),
    ("Human review", ("checked",)),
)


def _word(column: str, status: str) -> str:
    return PASS_WORDS.get(column, "Pass") if status == "pass" else OTHER_WORDS.get(status, status)


def page_compliance(ctx: Ctx) -> None:
    with session_scope(ctx.engine) as s:
        years = kpi_years(s)
    people = people_of(ctx)
    header(
        "Compliance check",
        "For each company and year: does the filing disclose what it should, and are its figures "
        "internally consistent?",
        "Every company against the same checklist, for the fiscal year you choose.",
        "A tick means the check passed, a triangle that it needs attention, a cross that it failed. "
        "Open a company for what was found and why each check matters.",
    )
    st.warning(
        "**Monitoring view, not a legal finding.** This is a disclosure and consistency check. It is "
        "not a legal finding of compliance with SEBI's rules, and a failed check marks a figure to look "
        "at, not a proven breach."
    )
    with st.expander("What is checked, and what SEBI requires"):
        st.dataframe(
            pd.DataFrame(
                {
                    "Check": [CHECK_TITLES[k] for k in CHECK_ORDER],
                    "Why it matters": [CHECK_WHY[k] for k in CHECK_ORDER],
                }
            ),
            hide_index=True,
            width="stretch",
        )
        st.markdown(
            "**SEBI's glide path for reasonable assurance of BRSR Core** (circular of 12 July 2023, "
            "section 3.4.2). Applicability is by market-capitalisation rank:"
        )
        st.dataframe(
            pd.DataFrame(GLIDE_PATH, columns=["Financial year", "Listed entities required"]),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "This system does not compute each company's market-capitalisation rank, so it reports what the data states and does not decide whether assurance was required of a given company."
        )
    if not years:
        empty_state("No filings loaded yet", "Run gauge ingest.", "fact_check")
        return
    all_years = sorted(set(years))
    fy = year_picker(ctx, all_years, "compliance_fy")
    tab_all, tab_one = st.tabs(["All companies", "One company"])
    with tab_all:
        with session_scope(ctx.engine) as s:
            matrix = compliance_matrix(s, fy, ctx.indicators)
        columns = list(PASS_WORDS)
        html_rows = [
            {
                "name": people.label(r["code"]),
                "sector": r["sector"],
                "cells": [status_mark(r[c], _word(c, r[c])) for c in columns],
                "passed": r["passed"],
                "of": r["of"],
            }
            for r in matrix.to_dict("records")
        ]
        shown = people.rename(matrix, "code")
        for col in columns:
            shown[col] = shown[col].map(STATUS_TEXT)
        shown["Checks passed"] = [
            f"{p} of {o}" for p, o in zip(matrix["passed"], matrix["of"], strict=True)
        ]
        shown = shown.rename(columns={"code": "Company", "sector": "Sector"}).drop(
            columns=["passed", "of"]
        )
        st.markdown(
            f"**What is being compared:** all {len(shown)} companies against the same five checks for {fy}."
        )
        render(compliance_matrix_html(html_rows, columns))
        st.caption(
            "Each result is an icon and a word. 'Review required' marks something to look at; it is not a finding that a company breached a rule."
        )
        with st.expander("Sortable table and export"):
            st.dataframe(shown, hide_index=True, width="stretch")
            st.download_button(
                "Export the compliance matrix (CSV)",
                shown.to_csv(index=False),
                f"compliance_{fy}.csv",
                "text/csv",
                icon=":material/download:",
            )
        if (matrix["Own filing"] == "attention").any():
            st.caption(
                "'Attention' on the filing and the assurance check usually means the year was read from a later filing's prior-year column, which does not carry the assurance statement. Load the filing as submitted for that year to settle it."
            )
    with tab_one:
        code = st.selectbox(
            "Company", people.codes, format_func=people.label, key="compliance_company"
        )
        with session_scope(ctx.engine) as s:
            checks = compliance_checks(s, code, fy, ctx.indicators)
        summary = compliance_summary(checks)
        cols = st.columns(3)
        cols[0].metric("Passed", f"{summary['passed']} of {summary['of']}")
        cols[1].metric("Need attention", summary["attention"])
        cols[2].metric("Failed", summary["failed"])
        st.markdown(f"**What is being checked:** {people.label(code)}'s filing for {fy}.")
        by_key = {c["key"]: c for c in checks}
        groups = []
        for title, keys in CHECK_GROUPS:
            present = [by_key[k] for k in keys if k in by_key]
            if present:
                groups.append(
                    (
                        title,
                        [
                            Check(c["status"], c["check"], c["found"], c["why it matters"])
                            for c in present
                        ],
                    )
                )
        render(check_groups_html(groups))
        if "Companies" in ctx.pages:
            st.button(
                "Open this company's profile",
                key="compliance_to_company",
                on_click=open_company,
                args=(code,),
            )


# ---- Data quality register -------------------------------------------------------------------------
STATUS_ORDER = {
    "Needs verification": 0,
    "Reviewed: error recorded": 1,
    "Reviewed: matches filing": 2,
    "Review": 3,
    "Noted, no action needed": 4,
    "Data unavailable": 5,
}


def page_flags(ctx: Ctx) -> None:
    people = people_of(ctx)
    with session_scope(ctx.engine) as s:
        rows = register_rows(s, ctx.indicators)
    header(
        "Data quality register",
        "Every figure that failed an automatic check, across all companies.",
        "Nothing is compared. Each row is one figure that broke a rule.",
        "Filter by severity, rule or sector. A flag marks a figure to look at; it is not a finding that a "
        "company misreported, because the cause may be rounding, a different reporting boundary, or this "
        "system's own unit handling.",
    )
    if rows.empty:
        callout("ok", "No data-quality flags", "Every figure passed every automatic check.")
        return
    needs = int((rows["status"] == "Needs verification").sum())
    unavailable = int((rows["status"] == "Data unavailable").sum())
    reviewed = int(rows["status"].str.startswith("Reviewed").sum())
    stat_strip(
        [
            ("Flags in the register", str(len(rows)), "across all companies and years"),
            ("Need verification", str(needs), "errors on figures no person has checked"),
            ("Reviewed by a person", str(reviewed), "with a recorded result"),
            ("Data unavailable", str(unavailable), "nothing loaded to verify"),
        ]
    )
    callout("info", "A flag is a figure to verify.", DATA_CHECK_NOTE)
    summary = pd.crosstab(rows["rule"], rows["severity"]).reset_index()
    for sev in ("error", "warning"):
        if sev not in summary:
            summary[sev] = 0
    section("Flags by rule")
    render(
        rule_summary_html(
            [
                {
                    "rule": r["rule"],
                    "what": RULE_NOTES.get(r["rule"], ""),
                    "error": r["error"],
                    "warning": r["warning"],
                }
                for r in summary.to_dict("records")
            ]
        )
    )
    section("Register")
    a, b, c, d = st.columns(4)
    severities = sorted(rows["severity"].unique())
    chosen_severity = a.multiselect("Severity", severities, default=severities)
    chosen_rules = b.multiselect("Rule", sorted(rows["rule"].unique()))
    chosen_sectors = c.multiselect("Sector", sorted(rows["sector"].unique()))
    chosen_status = d.multiselect(
        "Status", sorted(rows["status"].unique(), key=lambda x: STATUS_ORDER.get(x, 9))
    )
    text = st.text_input("Search company, metric or issue", key="register_search").strip().lower()
    shown = rows[rows["severity"].isin(chosen_severity)]
    if chosen_rules:
        shown = shown[shown["rule"].isin(chosen_rules)]
    if chosen_sectors:
        shown = shown[shown["sector"].isin(chosen_sectors)]
    if chosen_status:
        shown = shown[shown["status"].isin(chosen_status)]
    if text:
        haystack = (
            shown["code"].map(people.label)
            + " "
            + shown["metric"].fillna("")
            + " "
            + shown["issue"]
            + " "
            + shown["rule"]
        ).str.lower()
        shown = shown[haystack.str.contains(text, regex=False)]
    shown = (
        shown.assign(_order=shown["status"].map(lambda x: STATUS_ORDER.get(x, 9)))
        .sort_values(["_order", "sector", "code", "fy"], kind="stable")
        .drop(columns="_order")
    )
    st.caption(f"{len(shown)} of {len(rows)} flags")
    if shown.empty:
        empty_state("No flags match these filters", "Clear a filter to see more.", "filter_alt_off")
        return
    page_rows = paginate(shown.reset_index(drop=True), 12, "register")
    render(register_table_html(page_rows, people.label))
    _exception_panel(ctx, people, page_rows)
    table = people.rename(shown).rename(columns={"code": "company"})[
        [
            "company",
            "sector",
            "fy",
            "metric",
            "reported",
            "issue",
            "rule",
            "severity",
            "status",
            "reviewer",
            "verified_on",
        ]
    ]
    with st.expander("Sortable table and export"):
        st.dataframe(table, hide_index=True, width="stretch")
        st.download_button(
            "Export the register (CSV)",
            table.to_csv(index=False),
            "data_quality_register.csv",
            "text/csv",
            icon=":material/download:",
        )


def _exception_panel(ctx: Ctx, people, page_rows: pd.DataFrame) -> None:
    """One exception in full, with the two actions: open its source, verify it."""
    section("Selected exception")
    labels = {
        f"{people.label(r['code'])} · {r['fy']} · {r['metric']} · {r['status']} ({i})": r
        for i, r in enumerate(page_rows.to_dict("records"))
    }
    r = labels[st.selectbox("Open an exception from this page", list(labels), key="register_pick")]
    tone = {"warn": "warn", "ok": "ok", "danger": "danger", "info": "info"}.get(r["tone"], "")
    reviewer = esc(r["reviewer"]) if r["reviewer"] else "not yet reviewed"
    render(
        '<div class="eis-card"><div class="eis-split" style="grid-template-columns:minmax(0,1fr) minmax(0,1.6fr)">'
        f'<div><div class="eis-label">Reported value</div><div class="eis-bignum">{esc(r["reported"])}</div>'
        f'<div class="eis-meta" style="margin-top:4px">{esc(r["metric"])}</div></div>'
        '<dl class="eis-finding">'
        f"<dt>Company</dt><dd>{esc(people.label(r['code']))} · {esc(r['sector'])}</dd>"
        f"<dt>Fiscal year</dt><dd>{esc(r['fy'])}</dd>"
        f'<dt>Reason</dt><dd>{esc(r["issue"])} <span class="eis-mono">({esc(r["rule"])})</span></dd>'
        f"<dt>Status</dt><dd>{badge(r['status'], tone)}</dd>"
        f"<dt>Reviewer</dt><dd>{reviewer}{' on ' + esc(r['verified_on']) if r['verified_on'] else ''}</dd>"
        "</dl></div></div>"
    )
    a, b, _ = st.columns([1, 1, 4])
    usable = r["fy"] != "all years"
    if "Sources and filings" in ctx.pages and usable:
        a.button(
            "Open source",
            key="register_source",
            on_click=open_filing,
            args=(r["code"], r["fy"]),
            icon=":material/folder_open:",
        )
    if "Data verification" in ctx.pages and usable and pd.notna(r["item_id"]):
        b.button(
            "Verify",
            key="register_verify",
            type="primary",
            on_click=open_verification,
            args=(r["code"], r["fy"], r["indicator_code"]),
            icon=":material/verified:",
        )


# ---- Sources and filings -----------------------------------------------------------------------------
def pick_filing(ctx: Ctx, people, fys_by_code: dict[str, list[str]], key: str):
    """Company and fiscal-year pickers shared by the sources and verification pages."""
    codes = [c for c in people.codes if fys_by_code.get(c)]
    left, right = st.columns(2)
    code = left.selectbox("Company", codes, format_func=people.label, key=f"{key}_company")
    years = fys_by_code[code]
    start = (
        years.index(ctx.cfg.study.analysis_fy)
        if ctx.cfg.study.analysis_fy in years
        else len(years) - 1
    )
    fy = right.selectbox("Fiscal year", years, index=start, key=f"{key}_fy")
    return code, fy


def _apply_focus(state_key: str, prefix: str, fys_by_code: dict[str, list[str]]):
    """A page opened from elsewhere (a register row, a company profile) arrives with a company and year
    chosen: set them before the pickers are drawn."""
    focus = st.session_state.pop(state_key, None)
    if focus and focus[0] in fys_by_code and focus[1] in fys_by_code[focus[0]]:
        st.session_state[f"{prefix}_company"] = focus[0]
        st.session_state[f"{prefix}_fy"] = focus[1]
    return focus


def page_filings(ctx: Ctx) -> None:
    people = people_of(ctx)
    with session_scope(ctx.engine) as s:
        register = filings_register(s)
    header(
        "Sources and filings",
        "Where every number came from: the file, its SHA-256 fingerprint, the date it was retrieved, and "
        "for each value what the filing stated.",
        "Nothing is compared. This page is the audit trail from a number back to its filing.",
        "`values` is how many figures were taken from a filing and `checked` how many a person has "
        "compared with it. A fingerprint changes if the file changes.",
    )
    if register.empty:
        empty_state("No filings loaded yet", "Run gauge ingest.", "folder_open")
        return
    fys = register.groupby("code")["fy"].apply(list).to_dict()
    _apply_focus("filing_focus", "sources", fys)
    section("Trace a KPI to its source", "from the computed number back to the filing file")
    code, fy = pick_filing(ctx, people, fys, "sources")
    kpis = {k.label: k for k in ctx.indicators.kpis}
    kpi_label = st.selectbox("KPI", list(kpis), key="sources_kpi")
    spec = kpis[kpi_label]
    with session_scope(ctx.engine) as s:
        trace = source_trace(s, code, fy, spec.code, ctx.indicators)
        lineage = indicator_lineage(s, code, fy, ctx.indicators)
    labels = {i.code: i.label for i in ctx.indicators.indicators}
    chain, side = st.columns([1.35, 1], gap="large")
    with chain:
        render(chain_html(trace_steps(trace, people.label(code), fy, labels)))
    with side:
        render('<div class="eis-label" style="margin-bottom:6px">SHA-256 fingerprint (copy)</div>')
        report = trace["report"]
        if report and report["sha256"]:
            st.code(report["sha256"], language=None)
            st.caption(
                "A fingerprint of the filing file as downloaded. If the file changes by even one byte, so does this value."
            )
        else:
            callout("warn", "No fingerprint recorded", "No SHA-256 is stored for this filing.")
        render('<div class="eis-label" style="margin:14px 0 6px">What the filing stated</div>')
        units = {i.label: pretty_unit(i.unit) for i in ctx.indicators.indicators}
        shown = lineage.assign(unit=lineage["indicator"].map(units))
        st.dataframe(
            shown.drop(columns=["item_id"])[
                [
                    "indicator",
                    "value",
                    "unit",
                    "as filed",
                    "as-filed unit",
                    "source element",
                    "review",
                ]
            ],
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "`value` is what the metrics use, after unit conversion. `as filed` is what the filing states, and `source element` is where in the filing it was read."
        )
        if "Data verification" in ctx.pages:
            st.button(
                "Verify a figure from this filing",
                key="sources_to_verify",
                on_click=open_verification,
                args=(code, fy, None),
                icon=":material/verified:",
            )
    section("Filings register", f"{len(register)} filings")
    shown = people.rename(register).rename(columns={"code": "company"})
    st.dataframe(shown, hide_index=True, width="stretch")
    st.download_button(
        "Export the register (CSV)",
        shown.to_csv(index=False),
        "filings_register.csv",
        "text/csv",
        icon=":material/download:",
    )


# ---- Data verification -------------------------------------------------------------------------------
def page_verification(ctx: Ctx) -> None:
    people = people_of(ctx)
    header(
        "Data verification",
        "Compare a stored value with its filing and record your decision. It is stored with your name and "
        "the date.",
        "A stored value against the figure in the filing it came from.",
        "Choose a company and year, pick a value, and say whether it matches. A note is required when it "
        "does not.",
    )
    saved = st.session_state.pop("verification_saved", None)
    if saved:
        st.success(saved)
        toast(saved)
    reviewer = st.text_input("Your name (so the decision can be traced)", key="reviewer").strip()
    if not reviewer:
        st.info("Enter your name to start.")
        return
    with session_scope(ctx.engine) as s:
        register = filings_register(s)
        counts = headline_counts(s)
    if register.empty:
        empty_state("No filings loaded yet", "Run gauge ingest.", "verified")
        return
    st.metric(
        "Values checked by a person",
        f"{counts['values checked by a person']} of {counts['indicator values']}",
    )
    fys = register.groupby("code")["fy"].apply(list).to_dict()
    focus = _apply_focus("verify_focus", "verify", fys)
    code, fy = pick_filing(ctx, people, fys, "verify")
    units = {i.label: pretty_unit(i.unit) for i in ctx.indicators.indicators}
    code_of = {i.label: i.code for i in ctx.indicators.indicators}
    with session_scope(ctx.engine) as s:
        attrs = report_attributes(s, code, fy)
        lineage = indicator_lineage(s, code, fy, ctx.indicators)
        flagged = register_rows(s, ctx.indicators)
        st.caption(f"Filing: {attrs.get('source_file') or 'not recorded'}")
        shown = lineage.assign(unit=lineage["indicator"].map(units))
        st.dataframe(
            shown.drop(columns=["item_id"])[
                ["indicator", "value", "unit", "as filed", "as-filed unit", "review"]
            ],
            hide_index=True,
            width="stretch",
        )
        options = {
            f"{r.indicator}: {r.value:,.2f} {units.get(r.indicator, '')}": int(r.item_id)
            for r in lineage.itertuples()
        }
        labels = list(options)
        start = 0
        if focus and focus[2] and focus[0] == code and focus[1] == fy:
            wanted = next((k for k in labels if code_of.get(k.split(":")[0]) == focus[2]), None)
            start = labels.index(wanted) if wanted else 0
        picked = st.selectbox("Value to check", labels, index=start)
        item = lineage[lineage["item_id"] == options[picked]].iloc[0]
        mine = flagged[
            (flagged["code"] == code)
            & (flagged["fy"] == fy)
            & (flagged["indicator_code"] == code_of.get(item["indicator"]))
            & (flagged["rule"] != "missing_indicator")
        ]
        left, right = st.columns(2, gap="large")
        with left:
            _system_finding(item, units, mine, attrs)
        with right, st.container(border=True, key="reviewer-decision"):
            render(
                '<div class="eis-panel-title">Reviewer decision <span class="eis-badge accent">human</span></div>'
            )
            result = st.radio(
                "Does the stored value match the filing?",
                ["ok", "error"],
                format_func=lambda r: "Yes, it matches" if r == "ok" else "No, it is wrong",
                horizontal=True,
                key="verification_result",
            )
            reason = st.text_input(
                "Note (required when the value is wrong)", key="verification_note"
            )
            if st.button("Record decision", key="record_verification", type="primary"):
                try:
                    record_verification(
                        s,
                        item_id=options[picked],
                        reviewer=reviewer,
                        result=result,
                        note=reason or None,
                    )
                    # Commit before st.rerun(): its control-flow exception would skip session_scope's commit.
                    s.commit()
                    st.session_state["verification_saved"] = f"Recorded: {picked} is {result}."
                    st.rerun()
                except VerificationError as exc:
                    st.error(str(exc))


def _system_finding(item, units: dict, mine: pd.DataFrame, attrs: dict) -> None:
    """What the system found, before any human decision."""
    flagged = not mine.empty and (mine["severity"] == "error").any()
    if flagged:
        verdict = badge("FLAGGED", "warn", "flag")
        why = "".join(
            f'<div style="margin-top:4px">{esc(r["issue"])} <span class="eis-mono">({esc(r["rule"])})</span></div>'
            for r in mine.to_dict("records")
        )
    elif not mine.empty:
        verdict = badge("NOTED", "info", "info")
        why = "".join(
            f'<div style="margin-top:4px">{esc(r["issue"])}</div>' for r in mine.to_dict("records")
        )
    else:
        verdict = badge("NO FLAG", "ok", "check_circle")
        why = '<div style="margin-top:4px">No automatic check touches this figure.</div>'
    filed = (
        "same as stored"
        if pd.isna(item["as filed"])
        else f"{item['as filed']:,.2f} {item['as-filed unit'] or ''}".strip()
    )
    big = f"{item['value']:,.2f}"
    render(
        '<div class="eis-card"><div class="eis-panel-title">System finding <span class="eis-badge">automatic</span></div>'
        f'<div class="eis-bignum">{esc(big)} <span style="font-size:14px;font-weight:500;color:var(--muted)">{esc(units.get(item["indicator"], ""))}</span></div>'
        f'<div class="eis-meta" style="margin:2px 0 10px">{esc(item["indicator"])}</div>'
        '<dl class="eis-finding">'
        f"<dt>System check</dt><dd>{verdict}{why}</dd>"
        f"<dt>As filed</dt><dd>{esc(filed)}</dd>"
        f'<dt>Source element</dt><dd class="eis-mono">{esc(item["source element"] or "not recorded")}</dd>'
        f"<dt>Source</dt><dd>{esc(attrs.get('source_file') or 'not recorded')}</dd>"
        f"<dt>Review so far</dt><dd>{esc(item['review'])}</dd>"
        "</dl></div>"
    )
