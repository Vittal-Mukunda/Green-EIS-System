"""The analysis pages: sectors, KPI scorecard, companies, comparison, and query and chart.

All figures come from `gauge.viewdata`; these pages arrange them. A position is a place among the
companies of one sector that pass the data checks: it is never called a rating, and a figure that
fails a data check is shown but never placed.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from components.alerts import STUDY_SAMPLE_NOTE, callout
from components.benchmark_card import benchmark_card_html
from components.charts import BAND_COLOURS, CONTEXT_LINE, FOCUS, show
from components.comparison_table import (
    Cell,
    CompareRow,
    MatrixColumn,
    MatrixGroup,
    MatrixRow,
    compare_html,
    scorecard_html,
)
from components.empty_state import empty_state
from components.evidence_card import Evidence, evidence_card_html
from components.icons import icon
from components.kpi_card import kpi_profile_card_html
from components.markup import esc, render
from components.status_badge import badge, position_chip, position_label
from eis_common import (
    CROSS_SECTOR_WARNING,
    STATUS_TEXT,
    Ctx,
    change_text,
    colour_key,
    header,
    jump_to_company,
    kpi_title,
    open_filing,
    open_page,
    open_verification,
    people_of,
    section,
    year_picker,
)

from gauge import vocab
from gauge.db.session import session_scope
from gauge.viewdata import (
    BAND_FLAT,
    DATA_CHECK,
    METRIC_NOTES,
    attention_list,
    choose_chart,
    company_brief_markdown,
    company_directory,
    company_reading,
    compare_table,
    comparison_sentences,
    compliance_checks,
    compliance_summary,
    describe_query,
    evidence_quality,
    explain_value,
    flag_counts,
    flag_register,
    fmt_number,
    gap_to_benchmark,
    indicator_lineage,
    kpi_matrix,
    kpi_over_time,
    kpi_years,
    metric_catalog,
    pretty_unit,
    query_data,
    reviewer_notes,
    sdg_relevance,
    sector_note,
    sector_overview,
    what_if,
)
from gauge.viewdata_ui import (
    filing_facts,
    fmt_figure,
    pct_vs_median,
    sector_summary,
    unit_reconciliation,
)


def _place(r: dict) -> str:
    """'2 of 5' for a ranked figure, '' otherwise."""
    if r["band"] in (DATA_CHECK, "n/a") or pd.isna(r["rank in sector"]):
        return ""
    return f"{int(r['rank in sector'])} of {int(r['companies compared'])}"


def _band_label(r: dict) -> str:
    """The table wording for a position: 'Better third (rank 2 of 5)', 'Data check', ..."""
    if r["band"] in (DATA_CHECK, "n/a", BAND_FLAT):
        return position_label(r["band"])
    return f"{position_label(r['band'])} (rank {_place(r)})"


# ---- Sectors --------------------------------------------------------------------------------------
def page_sectors(ctx: Ctx) -> None:
    with session_scope(ctx.engine) as s:
        years = kpi_years(s)
    people = people_of(ctx)
    header(
        "Sectors",
        "What each sector is, who is in it, and how its companies compare on one metric.",
        "Companies in the same sector on the metric you choose. Sectors are never compared with each "
        "other, because their figures are not like for like.",
        "Pick a sector and a metric. The bars are the sector's companies; the dashed line is the "
        "study-sample median and the shaded band is P25 to P75 of that sample.",
    )
    sectors = people.sectors()
    if not sectors or not years:
        empty_state(
            "No sectors or metrics loaded yet", "Run gauge ingest and gauge compute-kpis.", "stacks"
        )
        return
    focus = st.session_state.pop("sector_focus", None)
    if focus in sectors:
        st.session_state["sector_pick"] = focus
    if st.session_state.get("sector_pick") not in sectors:
        st.session_state.pop("sector_pick", None)
    kpis = {k.label: k for k in ctx.indicators.kpis}
    left, right, _ = st.columns([1, 1.4, 2])
    with left:
        fy = year_picker(ctx, years, "sector_fy")
    with right:
        spec = kpis[st.selectbox("Metric", list(kpis), key="sector_kpi")]
    sector = st.radio("Sector", sectors, horizontal=True, key="sector_pick")
    with session_scope(ctx.engine) as s:
        matrix = kpi_matrix(s, fy, ctx.indicators)
        frame = sector_overview(s, fy, spec.code, ctx.indicators)
        over_time = kpi_over_time(s, spec.code)
        attention = attention_list(s, fy, ctx.indicators, 10.0)
    summary = sector_summary(matrix)

    section("Study-sample benchmarks", f"{fy} · every sector, side by side but never compared")
    cards = []
    for name in sectors:
        part = summary[summary["sector"] == name]
        needing = attention[attention["sector"] == name]["code"].nunique()
        cards.append(
            benchmark_card_html(
                name, part, len(people.in_sector(name)), fy, int(needing), name == sector
            )
        )
    render('<div class="eis-grid cols-2">' + "".join(cards) + "</div>")
    callout("info", "Study sample, not industry.", STUDY_SAMPLE_NOTE, raw_body=False)

    note = sector_note(sector)
    members = people.in_sector(sector)
    section(f"{sector}: explore a metric")
    with st.container(border=True):
        st.markdown(f"**{sector}.** {note['what']}")
        st.markdown(note["footprint"])
        st.caption(note["compare"])
        who = [f"{people.label(c)} ({people.short(c)})" if people.real else c for c in members]
        st.markdown("**Companies in this sample:** " + ", ".join(who))
    notes = METRIC_NOTES[spec.code]
    st.info(f"**{kpi_title(spec.label, spec.unit)}.** {notes['means']} {notes['reading']}")
    frame = frame[frame["sector"] == sector]
    if frame.empty:
        empty_state(f"No {spec.label} values for {sector} in {fy}", "", "inbox")
        return
    st.markdown(
        f"**What is being compared:** the {len(frame)} {sector} companies loaded, on {spec.label} in {fy}."
    )
    stats = summary[(summary["sector"] == sector) & (summary["kpi"] == spec.code)]
    stat = stats.iloc[0] if not stats.empty else None
    tab_now, tab_time, tab_attention = st.tabs(["This year", "Over time", "Needs attention"])
    with tab_now:
        if stat is not None and not pd.isna(stat["median"]):
            unit = pretty_unit(spec.unit)
            render(
                '<div class="eis-grid cols-4">'
                + "".join(
                    f'<div class="eis-card flat"><div class="eis-kpi"><span class="eis-kpi-label">{esc(label)}</span>'
                    f'<span class="eis-kpi-value">{esc(text)}</span><span class="eis-kpi-unit">{esc(unit)}</span></div></div>'
                    for label, text in (
                        ("Study-sample median", fmt_figure(stat["median"], unit)),
                        ("P25 (lower quartile)", fmt_figure(stat["p25"], unit)),
                        ("P75 (upper quartile)", fmt_figure(stat["p75"], unit)),
                        (
                            "Companies compared",
                            f"{int(stat['compared'])} of {int(stat['companies'])}",
                        ),
                    )
                )
                + "</div>"
            )
        shown = people.rename(frame, short=True).sort_values(
            "value", ascending=spec.better == "higher"
        )
        fig = px.bar(
            shown,
            x="value",
            y="code",
            orientation="h",
            color="band",
            color_discrete_map=BAND_COLOURS,
            labels={"value": kpi_title(spec.label, spec.unit), "code": "", "band": "position"},
        )
        if stat is not None and not pd.isna(stat["p25"]):
            fig.add_vrect(
                x0=float(stat["p25"]),
                x1=float(stat["p75"]),
                fillcolor="#2e7d5b",
                opacity=0.08,
                line_width=0,
                annotation_text="P25 to P75",
                annotation_position="top left",
                annotation_font_size=10,
            )
        median = frame["sector median"].dropna()
        if not median.empty:
            fig.add_vline(
                x=float(median.iloc[0]),
                line_dash="dash",
                line_color="#2c3832",
                annotation_text="Study-sample median",
                annotation_position="top",
                annotation_font_size=10,
            )
        fig.update_layout(margin={"t": 36}, legend_title_text="Position")
        show(fig)
        colour_key()
        table = pd.DataFrame(
            {
                "Company": [people.label(c) for c in frame["code"]],
                f"Value ({pretty_unit(spec.unit)})": [fmt_number(v) for v in frame["value"]],
                "Rank in sector": [
                    ("not ranked" if b == DATA_CHECK else f"{r} of {n}")
                    for r, n, b in zip(
                        frame["rank in sector"],
                        frame["companies compared"],
                        frame["band"],
                        strict=True,
                    )
                ],
                "Position": [position_label(b) for b in frame["band"]],
                "Change vs previous year": [
                    change_text(c, m)
                    for c, m in zip(frame["change %"], frame["movement"], strict=True)
                ],
                "Against the study-sample median": frame["vs sector median"],
            }
        )
        st.dataframe(table, hide_index=True, width="stretch")
        clean = frame[frame["data check"] == ""]["value"]
        if len(clean) >= 2 and clean.min() > 0:
            st.caption(
                f"Across the {len(clean)} companies that pass the data checks, the lowest is "
                f"{fmt_number(clean.min())}, the median {fmt_number(clean.median())} and the highest "
                f"{fmt_number(clean.max())} {pretty_unit(spec.unit)}: the highest is "
                f"{clean.max() / clean.min():.1f} times the lowest."
            )
        st.download_button(
            "Export this table (CSV)",
            table.to_csv(index=False),
            f"{vocab.slug(sector)}_{spec.code}_{fy}.csv",
            "text/csv",
            icon=":material/download:",
        )
    with tab_time:
        series = people.rename(over_time[over_time["sector"] == sector], short=True)
        lines = px.line(
            series,
            x="fy",
            y="value",
            color="code",
            markers=True,
            labels={
                "fy": "Fiscal year",
                "value": kpi_title(spec.label, spec.unit),
                "code": "Company",
            },
        )
        show(lines)
        st.caption(
            "Every fiscal year loaded. A figure that fails a data-quality check is still plotted here; the Data quality register lists which."
        )
    with tab_attention:
        mine = attention[attention["sector"] == sector]
        if mine.empty:
            callout(
                "ok",
                "Nothing needs attention",
                "No data-check errors or large wrong-way moves in this sector for this year.",
            )
        else:
            st.caption(
                "Companies with data-quality errors first, then the largest wrong-way moves of 10% or more against the previous year."
            )
            st.dataframe(people.rename(mine), hide_index=True, width="stretch")


# ---- KPI scorecard ---------------------------------------------------------------------------------
def page_scorecard(ctx: Ctx) -> None:
    with session_scope(ctx.engine) as s:
        years = kpi_years(s)
    people = people_of(ctx)
    header(
        "KPI scorecard",
        "Every company against every metric in one picture.",
        "Each company against the other companies in its own sector, on all five metrics.",
        "Read across a row to see where a company sits on each metric, and down a column to see how a "
        "sector spreads. Hover over a cell for the figure, its unit and its rank.",
    )
    if not years:
        empty_state("No metrics yet", "Run gauge compute-kpis.", "grid_view")
        return
    left, right, _ = st.columns([1, 1.4, 2])
    with left:
        fy = year_picker(ctx, years, "scorecard_fy")
    with right:
        sector_filter = st.selectbox(
            "Sector", ["All sectors", *people.sectors()], key="scorecard_sector"
        )
    with session_scope(ctx.engine) as s:
        matrix = kpi_matrix(s, fy, ctx.indicators)
        counts = flag_counts(s, fy)
    if matrix.empty:
        empty_state(f"No metrics for {fy}", "", "grid_view")
        return
    specs = list(ctx.indicators.kpis)
    firms = (
        matrix[["sector", "code"]]
        .drop_duplicates()
        .sort_values(["sector", "code"])
        .to_dict("records")
    )
    if sector_filter != "All sectors":
        firms = [f for f in firms if f["sector"] == sector_filter]
    cells = {(r["code"], r["kpi"]): r for r in matrix.to_dict("records")}

    def cell_of(code: str, spec) -> Cell:
        r = cells.get((code, spec.code))
        if r is None:
            return Cell(empty=True)
        rank = (
            "not ranked: data check"
            if r["band"] == DATA_CHECK
            else (_place(r) or "too few to place")
        )
        tip = (
            f"{people.label(code)} · {spec.label}: {fmt_figure(r['value'], pretty_unit(spec.unit))} "
            f"{pretty_unit(spec.unit)} · rank in sector {rank} · position {position_label(r['band'])} · "
            f"vs previous year {change_text(r['change %'], r['movement'])}"
        )
        return Cell(fmt_figure(r["value"], pretty_unit(spec.unit)), r["band"], _place(r), tip)

    groups: list[MatrixGroup] = []
    for sector in sorted({f["sector"] for f in firms}):
        rows = []
        for f in (x for x in firms if x["sector"] == sector):
            row_cells = [cell_of(f["code"], spec) for spec in specs]
            n_checks = sum(c.band == DATA_CHECK for c in row_cells)
            extra = (
                badge(f"{n_checks} data check", "warn", "rule")
                if n_checks
                else '<span class="eis-na">none</span>'
            )
            rows.append(
                MatrixRow(
                    people.label(f["code"]),
                    people.short(f["code"]) if people.real else "",
                    row_cells,
                    extra,
                )
            )
        compared = int(matrix[matrix["sector"] == sector]["companies compared"].max())
        groups.append(
            MatrixGroup(
                f"{sector} · {len(rows)} companies · up to {compared} compared per metric", rows
            )
        )
    columns = [MatrixColumn(k.label, pretty_unit(k.unit), f"{k.better} is better") for k in specs]
    render(scorecard_html(groups, columns, extra_header="Data checks"))
    colour_key()

    def cell_text(code: str, spec) -> str:
        r = cells.get((code, spec.code))
        if r is None:
            return "-"
        place = (
            "data check"
            if r["band"] == DATA_CHECK
            else f"{r['rank in sector']}/{r['companies compared']}"
        )
        return f"{fmt_number(r['value'])}: {place}"

    table = pd.DataFrame(
        [
            {
                "Sector": f["sector"],
                "Company": people.label(f["code"]),
                **{kpi_title(k.label, k.unit): cell_text(f["code"], k) for k in specs},
                "Error flags": counts.get(f["code"], {}).get("errors", 0),
            }
            for f in firms
        ]
    )
    with st.expander("The same scorecard as a table (value: rank in sector / companies compared)"):
        st.dataframe(table, hide_index=True, width="stretch")
    st.download_button(
        "Export the scorecard (CSV)",
        table.to_csv(index=False),
        f"kpi_scorecard_{fy}.csv",
        "text/csv",
        icon=":material/download:",
    )
    jump_to_company(ctx, people, [f["code"] for f in firms], "scorecard")


# ---- Companies -------------------------------------------------------------------------------------
def page_companies(ctx: Ctx) -> None:
    with session_scope(ctx.engine) as s:
        directory = company_directory(s)
        years = kpi_years(s)
    people = people_of(ctx)
    header(
        "Companies",
        "A profile of one company: who it is, what it reported, what each number means, how it "
        "compares and what its filing discloses.",
        "The selected company against the other companies in its own sector, and against its own "
        "previous year.",
        "Start with the KPI profile, then open the explanation under any metric for what the "
        "number means in plain words. The evidence section shows whether the numbers can be checked.",
    )
    if directory.empty:
        empty_state("No companies yet", "Run gauge ingest.", "apartment")
        return
    focus = st.session_state.pop("company_focus", None)
    if focus in people.rows:
        st.session_state["company_pick"] = focus
    if st.session_state.get("company_pick") not in people.rows:
        st.session_state.pop("company_pick", None)
    code = st.selectbox("Company", people.codes, format_func=people.label, key="company_pick")
    tab_profile, tab_all = st.tabs(["Profile", "All companies"])
    with tab_all:
        shown = directory.assign(company=[people.label(c) for c in directory["code"]])
        st.dataframe(
            shown[["company", "symbol", "sector", "years loaded", "boundary", "assurance"]],
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "Boundary and assurance are what the latest filing loaded states. 'Not stated' means the "
            "data loaded does not say, not that the company has none."
        )
        jump_to_company(ctx, people, people.codes, "all_companies")
    with tab_profile:
        if not years:
            empty_state("No metrics yet", "Run gauge compute-kpis.", "apartment")
            return
        _company_profile(ctx, people, code, years)


def _band_counts(records: list[dict]) -> str:
    """Chips such as '2 Better third  1 Middle third  1 Data check'."""
    order = ("better third", "middle third", "weaker third", BAND_FLAT, DATA_CHECK, "n/a")
    chips = []
    for band in order:
        n = sum(r["band"] == band for r in records)
        if n:
            chips.append(position_chip(band, f"× {n}"))
    return "".join(chips)


def _company_profile(ctx: Ctx, people, code: str, years: list[str]) -> None:
    row = people.rows[code]
    note = sector_note(row["sector"])
    fy_col, _ = st.columns([1, 3])
    with fy_col:
        fy = year_picker(ctx, years, "company_fy")
    indicators = ctx.indicators
    with session_scope(ctx.engine) as s:
        matrix = kpi_matrix(s, fy, indicators)
        reading = company_reading(s, code, fy, indicators)
        quality = evidence_quality(s, code, fy)
    mine = matrix[matrix["code"] == code]
    records = mine.to_dict("records")
    n_checks = sum(r["band"] == DATA_CHECK for r in records)
    quality_chip = (
        badge(f"Data quality: {n_checks} data check", "warn", "rule")
        if n_checks
        else badge("Data quality: no data checks", "ok", "check_circle")
        if records
        else badge("Data quality: no metrics", "", "remove_circle")
    )
    render(
        f'<div style="margin:6px 0 2px"><h2 style="font-size:20px;font-weight:650;letter-spacing:-0.015em;margin:0">{esc(people.label(code))}</h2>'
        f'<div class="eis-meta" style="margin-top:2px">{esc(row["sector"])} · {esc(fy)}</div>'
        f'<div class="eis-kpi-chips" style="margin-top:8px">{badge("Sector: " + row["sector"], "accent", "stacks")}'
        f"{_band_counts(records) if records else badge('Position: not placed', '', 'remove_circle')}"
        f"{quality_chip}{badge('Latest year: ' + row['latest year'], '', 'event')}"
        f"{badge('Symbol: ' + row['symbol'])}{badge('Boundary: ' + row['boundary'])}{badge('Assurance: ' + row['assurance'])}</div></div>"
    )
    st.markdown(f"**What kind of company.** {note['what']} {note['footprint']}")
    st.caption(f"Years loaded: {row['years loaded']}. {note['compare']}")

    section("Environmental KPI profile", fy)
    if mine.empty:
        empty_state(f"No metrics for {row['sector']} companies in {fy}", "", "inbox")
    else:
        st.markdown(
            f"**What is being compared:** {people.label(code)} against the other {row['sector']} "
            f"companies loaded, and against its previous year. Position is among the companies compared."
        )
        cards = []
        for r in records:
            unit = r["unit"]
            checked = r["band"] == DATA_CHECK
            gap = pct_vs_median(r["value"], r["sector median"])
            if checked:
                vs = "Not placed: this figure fails a data check, so it is not compared with the median."
            elif pd.isna(gap):
                vs = "No study-sample median: too few companies in the sector pass the checks."
            else:
                vs = f"<b>{gap:+.0f}%</b> vs study-sample median ({esc(fmt_figure(r['sector median'], unit))} {esc(unit)})"
            cards.append(
                kpi_profile_card_html(
                    r["label"],
                    fmt_figure(r["value"], unit),
                    unit,
                    position_chip(r["band"], _place(r)),
                    vs,
                    f"{r['better']} is better",
                    esc(change_text(r["change %"], r["movement"])) + " vs previous year"
                    if not pd.isna(r["change %"])
                    else "no previous-year figure",
                    "tone-warn" if checked else "",
                )
            )
        render('<div class="eis-grid cols-5">' + "".join(cards) + "</div>")
        colour_key()
        table = pd.DataFrame(
            {
                "Metric": [r["label"] for r in records],
                "Value": [fmt_number(r["value"]) for r in records],
                "Unit": [pretty_unit(r["unit"]) for r in records],
                "Better when": [r["better"] for r in records],
                "Position in sector": [_band_label(r) for r in records],
                "Study-sample median": [fmt_number(r["sector median"]) for r in records],
                "Change vs previous year": [
                    change_text(r["change %"], r["movement"]) for r in records
                ],
            }
        )
        with st.expander("The metrics as a table"):
            st.dataframe(table, hide_index=True, width="stretch")
        st.markdown("**What do these numbers mean?**")
        for r in records:
            notes = METRIC_NOTES.get(r["kpi"], {})
            title = f"{r['label']}: {fmt_number(r['value'])} {pretty_unit(r['unit'])}"
            with st.expander(title, expanded=False):
                st.markdown(explain_value(r["kpi"], r["value"], r["sector median"]))
                st.markdown(f"**What it measures.** {notes.get('means', '')}")
                st.markdown(f"**How it is computed.** {notes.get('how', '')}")
                st.markdown(f"**How to read it.** {notes.get('reading', '')}")
                st.caption(f"Watch out: {notes.get('caution', '')}")
                if r["band"] == DATA_CHECK:
                    st.warning(
                        f"This figure fails a data-quality check ({r['data check']}), so it is not ranked."
                    )
    if reading:
        section("What the numbers say", fy)
        render(
            '<div class="eis-card flat"><ul style="margin:0;padding-left:18px">'
            + "".join(
                f'<li style="margin:4px 0;font-size:13.5px">{esc(line)}</li>' for line in reading
            )
            + "</ul></div>"
        )
        st.caption(
            "Positions describe this sample of companies on intensities. They are not a rating of environmental performance."
        )
        with session_scope(ctx.engine) as s:
            brief = company_brief_markdown(s, code, fy, indicators, people.label(code))
        st.download_button(
            "Download a one-page briefing (Markdown)",
            brief,
            file_name=f"{code}_{fy}_briefing.md",
            mime="text/markdown",
            icon=":material/download:",
        )

    _company_evidence(ctx, people, code, fy, quality)
    _company_trend(ctx, people, code)
    _company_whatif(ctx, people, code, fy)
    _company_checks(ctx, code, fy)
    with session_scope(ctx.engine) as s:
        lineage = indicator_lineage(s, code, fy, indicators)
        notes = reviewer_notes(s, code, indicators)
        sdg = sdg_relevance(s, indicators)
        flags = flag_register(s)
    section(f"Figures as reported, {fy}", "the raw totals the metrics are computed from")
    st.caption(
        "The raw totals the metrics are computed from. They grow with company size, so do not rank companies on them."
    )
    if lineage.empty:
        empty_state(f"No filing loaded for {fy}", "", "description")
    else:
        units = {i.label: pretty_unit(i.unit) for i in indicators.indicators}
        shown = lineage.assign(unit=lineage["indicator"].map(units))[
            ["indicator", "value", "unit", "as filed", "as-filed unit", "review"]
        ]
        st.dataframe(
            shown.rename(columns={"value": "value (standardised)"}),
            hide_index=True,
            width="stretch",
        )
    mine_flags = flags[flags["code"] == code].drop(columns=["code", "sector"])
    section(f"Data-quality flags ({len(mine_flags)})")
    if mine_flags.empty:
        st.caption("None.")
    else:
        st.dataframe(mine_flags, hide_index=True, width="stretch")
    if not notes.empty:
        section("Reviewer notes")
        st.dataframe(notes, hide_index=True, width="stretch")
    section("Sustainable Development Goals these metrics relate to")
    st.dataframe(sdg, hide_index=True, width="stretch")
    st.caption(vocab.SDG_CAPTION)


def _company_evidence(ctx: Ctx, people, code: str, fy: str, quality: dict) -> None:
    """The evidence-quality card: can this company's numbers be checked, and have they been?"""
    with session_scope(ctx.engine) as s:
        facts = filing_facts(s, code, fy)
        lineage = indicator_lineage(s, code, fy, ctx.indicators)
        checks = {c["key"]: c for c in compliance_checks(s, code, fy, ctx.indicators)}
    items: list[Evidence] = []
    if facts is None:
        items.append(
            Evidence("fail", "Source not available", f"No filing is loaded for {esc(fy)}.")
        )
    else:
        sha = facts["sha256"]
        short = f"{sha[:12]}…{sha[-6:]}" if sha else "no fingerprint recorded"
        items.append(
            Evidence(
                "ok" if facts["source_file"] and sha else "warn",
                "Source identified" if facts["source_file"] and sha else "Source incomplete",
                f"{esc(facts['source_file'] or 'file not recorded')}<br>SHA-256 <span class='eis-mono'>{esc(short)}</span> · "
                f"retrieved {esc(facts['retrieved_on'] or 'date not recorded')}",
            )
        )
    units = unit_reconciliation(lineage)
    if not units["values"]:
        items.append(
            Evidence("na", "Units: nothing to reconcile", "No figures are stored for this year.")
        )
    else:
        overrides = quality.get("warnings", 0)
        items.append(
            Evidence(
                "ok",
                "Units reconciled",
                f"All {units['values']} figures are held in the system's standard units; "
                f"{units['converted']} were converted from the unit printed in the filing"
                f"{' (' + str(overrides) + ' unit-label warnings are on record)' if overrides else ''}.",
            )
        )
    consistency = checks.get("consistency")
    if consistency is None:
        items.append(Evidence("na", "Validation: not assessed", "There is no filing to validate."))
    else:
        state = {"pass": "ok", "attention": "warn", "fail": "warn"}.get(consistency["status"], "na")
        items.append(
            Evidence(
                state,
                "Validation passed" if state == "ok" else "Validation: review needed",
                esc(consistency["found"])
                + ("" if state == "ok" else " Figures that fail a check are shown, not ranked."),
            )
        )
    done, total = quality["checked"], quality["values"]
    if not total:
        items.append(Evidence("na", "Human verification: none", "No stored values to check."))
    elif done == total:
        items.append(
            Evidence(
                "ok",
                "Human verification complete",
                f"All {total} values were compared with the filing by a person.",
            )
        )
    elif done:
        items.append(
            Evidence(
                "warn",
                "Partly verified by a person",
                f"{done} of {total} values have been compared with the filing.",
            )
        )
    else:
        items.append(
            Evidence(
                "na",
                "Not yet verified by a person",
                f"0 of {total} stored values have been compared with the filing. That is a gap in the evidence, not a finding.",
            )
        )
    section("Evidence quality", f"{people.label(code)} · {fy}")
    render(
        evidence_card_html(
            "Can these numbers be checked?",
            items,
            "Source, units, validation and human review are shown separately: a clean validation does not replace checking a figure against its filing.",
        )
    )
    a, b, _ = st.columns([1.2, 1.2, 3])
    if "Sources and filings" in ctx.pages:
        a.button(
            "Trace to source and filing",
            key="link_company_to_source",
            on_click=open_filing,
            args=(code, fy),
            icon=":material/folder_open:",
        )
    if "Data verification" in ctx.pages:
        b.button(
            "Verify a figure",
            key="link_company_to_verify",
            on_click=open_verification,
            args=(code, fy, None),
            icon=":material/verified:",
        )


def _company_trend(ctx: Ctx, people, code: str) -> None:
    kpis = {k.label: k for k in ctx.indicators.kpis}
    section("Over time, against the sector")
    label = st.selectbox("Metric", list(kpis), key="company_trend_kpi")
    spec = kpis[label]
    with session_scope(ctx.engine) as s:
        series = kpi_over_time(s, spec.code)
    sector = people.sector(code)
    peers = series[series["sector"] == sector]
    if peers.empty:
        empty_state("No values for this metric yet", "", "show_chart")
        return
    fig = go.Figure()
    for other, part in peers.groupby("code"):
        if other == code:
            continue
        fig.add_scatter(
            x=part["fy"],
            y=part["value"],
            mode="lines+markers",
            name=people.short(other),
            line={"color": CONTEXT_LINE, "width": 1.5},
            marker={"size": 5},
        )
    mine = peers[peers["code"] == code]
    fig.add_scatter(
        x=mine["fy"],
        y=mine["value"],
        mode="lines+markers",
        name=people.short(code),
        line={"color": FOCUS, "width": 3.5},
        marker={"size": 9},
    )
    fig.update_layout(
        yaxis_title=kpi_title(spec.label, spec.unit),
        xaxis_title="Fiscal year",
        legend_title="Company",
        margin={"t": 20},
    )
    show(fig)
    st.caption(
        f"{people.label(code)} in dark green, the other {sector} companies in grey. Years are the filings loaded."
    )


def _company_whatif(ctx: Ctx, people, code: str, fy: str) -> None:
    with session_scope(ctx.engine) as s:
        gap = gap_to_benchmark(s, code, fy, ctx.indicators)
    if gap.empty:
        return
    section(f"Distance from the study-sample median, {fy}")
    st.caption(
        "How far each metric is from the middle of its sector sample, and what change would close the gap."
    )
    shown = gap.assign(unit=gap["unit"].map(pretty_unit)).rename(
        columns={"sector median": "study-sample median"}
    )
    st.dataframe(shown, hide_index=True, width="stretch")
    section("What-if analysis", "arithmetic, not a forecast")
    pick = {k.label: k.code for k in ctx.indicators.kpis}
    left, right = st.columns(2)
    label = left.selectbox("Metric", list(pick), key="whatif_kpi")
    change = right.slider("Change in the metric (%)", -50, 50, 0, step=5, key="whatif_change")
    with session_scope(ctx.engine) as s:
        result = what_if(s, code, fy, pick[label], float(change), ctx.indicators)
    if result is None:
        st.info(
            "No ranked figure for this metric: it is missing, or it fails a data-quality check."
        )
    else:
        moved = f"{fmt_number(result['value_now'])} to {fmt_number(result['value_after'])} {pretty_unit(result['unit'])}"
        sector = people.sector(code)
        if result["rank_after"] == result["rank_now"]:
            place = f"its rank in {sector} would stay {result['rank_now']} of {result['n']} ({result['band_now']})"
        else:
            place = (
                f"its rank in {sector} would move from {result['rank_now']} to {result['rank_after']} "
                f"of {result['n']} ({result['band_now']} to {result['band_after']})"
            )
        now_chip = position_chip(result["band_now"], f"rank {result['rank_now']} of {result['n']}")
        after_chip = position_chip(
            result["band_after"], f"rank {result['rank_after']} of {result['n']}"
        )
        render(
            '<div class="eis-card flat" style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">'
            f'<div><div class="eis-label">Current position</div><div style="margin-top:5px">{now_chip}</div></div>'
            f"{icon('arrow_forward', 'lg')}"
            f'<div><div class="eis-label">Hypothetical position</div><div style="margin-top:5px">{after_chip}</div></div>'
            "</div>"
        )
        st.markdown(f"{result['kpi']} would go from {moved}; {place}.")
    st.caption(
        "Arithmetic on today's figures with every other company held fixed. It is not a forecast and not a target."
    )


def _company_checks(ctx: Ctx, code: str, fy: str) -> None:
    with session_scope(ctx.engine) as s:
        checks = compliance_checks(s, code, fy, ctx.indicators)
    summary = compliance_summary(checks)
    section(f"What the filing discloses, {fy}", "monitoring view, not a legal finding")
    st.markdown(
        f"{summary['passed']} of {summary['of']} disclosure checks passed, {summary['attention']} need "
        f"attention, {summary['failed']} failed."
    )
    table = pd.DataFrame(
        {
            "Check": [c["check"] for c in checks],
            "Result": [STATUS_TEXT[c["status"]] for c in checks],
            "What was found": [c["found"] for c in checks],
        }
    )
    st.dataframe(table, hide_index=True, width="stretch")
    if "Compliance check" in ctx.pages:
        st.button(
            "Open the full compliance check",
            key="company_to_compliance",
            on_click=open_page,
            args=("Compliance check",),
        )


# ---- Compare companies --------------------------------------------------------------------------------
def page_compare(ctx: Ctx) -> None:
    with session_scope(ctx.engine) as s:
        years = kpi_years(s)
    people = people_of(ctx)
    header(
        "Compare companies",
        "The companies you choose, side by side on every metric, with who is best and by how much.",
        "Exactly the companies you pick, for one fiscal year. Pick companies from the same sector for a "
        "like-for-like comparison.",
        "Read across a row to compare companies on one metric; the Best column names the company with "
        "the best figure that passes the data checks.",
    )
    if not years or not people.codes:
        empty_state("No metrics loaded yet", "", "compare_arrows")
        return
    first = people.sectors()[0]
    left, right = st.columns([3, 1])
    with left:
        codes = st.multiselect(
            "Companies to compare (2 to 6)",
            people.codes,
            default=people.in_sector(first)[:2],
            format_func=people.label,
            max_selections=6,
            key="compare_codes",
        )
    with right:
        fy = year_picker(ctx, years, "compare_fy")
    if len(codes) < 2:
        st.info("Pick at least two companies.")
        return
    if len({people.sector(c) for c in codes}) > 1:
        st.warning(CROSS_SECTOR_WARNING)
    with session_scope(ctx.engine) as s:
        table = compare_table(s, codes, fy, ctx.indicators)
        matrix = kpi_matrix(s, fy, ctx.indicators)
    if table.empty:
        empty_state(f"None of these companies has metrics for {fy}", "", "inbox")
        return
    names = {c: people.label(c) for c in codes}
    st.markdown(f"**Comparing** {', '.join(names.values())} on {len(table)} metrics for {fy}.")
    by_label = {k.label: k for k in ctx.indicators.kpis}
    rows = []
    for r in table.to_dict("records"):
        spec = by_label.get(r["metric"])
        cells = []
        for c in codes:
            m = matrix[(matrix["code"] == c) & (matrix["kpi"] == (spec.code if spec else ""))]
            if pd.isna(r[c]):
                cells.append(Cell(empty=True))
                continue
            band = (
                m.iloc[0]["band"] if not m.empty else ("data check" if r[f"{c} check"] else "n/a")
            )
            place = _place(m.iloc[0].to_dict()) if not m.empty else ""
            cells.append(
                Cell(fmt_figure(r[c], r["unit"]), band, place, f"{names[c]} · {r['metric']}")
            )
        rows.append(
            CompareRow(
                r["metric"],
                r["unit"],
                f"{r['better']} is better",
                cells,
                names[r["best"]] if r["best"] else "",
            )
        )
    render(compare_html([(names[c], people.sector(c)) for c in codes], rows))
    colour_key()
    wide = pd.DataFrame(
        {
            "Metric": table["metric"],
            "Unit": table["unit"],
            "Better when": list(table["better"]),
        }
    )
    for c in codes:
        wide[people.short(c)] = [
            ("n/a" if pd.isna(v) else fmt_number(v) + (" †" if chk else ""))
            for v, chk in zip(table[c], table[f"{c} check"], strict=True)
        ]
    wide["Best"] = [names[b] if b else "none" for b in table["best"]]
    with st.expander("Sortable table and export"):
        st.dataframe(wide, hide_index=True, width="stretch")
        if any(table[f"{c} check"].astype(bool).any() for c in codes):
            st.caption("† This figure fails a data-quality check, so it is shown but not ranked.")
        st.download_button(
            "Export the comparison (CSV)",
            wide.to_csv(index=False),
            f"comparison_{fy}.csv",
            "text/csv",
            icon=":material/download:",
        )
    section("In words")
    for line in comparison_sentences(table, codes, names):
        st.markdown(f"- {line}")
    section("As a chart")
    long = table.melt(
        id_vars=["metric", "unit"], value_vars=codes, var_name="code", value_name="value"
    )
    long["metric_label"] = long["metric"] + " (" + long["unit"] + ")"
    long["company"] = long["code"].map(people.short)
    fig = px.bar(
        long,
        x="company",
        y="value",
        color="company",
        facet_col="metric_label",
        facet_col_wrap=3,
        labels={"company": "", "value": ""},
    )
    fig.update_yaxes(matches=None, showticklabels=True)
    fig.update_xaxes(matches=None, showticklabels=True)
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    fig.update_layout(showlegend=False, height=520)
    show(fig)
    st.caption("Each panel has its own scale because the metrics have different units.")
    section("The same companies over time")
    kpis = {k.label: k for k in ctx.indicators.kpis}
    spec = kpis[st.selectbox("Metric", list(kpis), key="compare_trend")]
    with session_scope(ctx.engine) as s:
        series = kpi_over_time(s, spec.code)
    series = people.rename(series[series["code"].isin(codes)], short=True)
    if series.empty:
        empty_state("No values for these companies on this metric", "", "show_chart")
    else:
        show(
            px.line(
                series,
                x="fy",
                y="value",
                color="code",
                markers=True,
                labels={
                    "fy": "Fiscal year",
                    "value": kpi_title(spec.label, spec.unit),
                    "code": "Company",
                },
            )
        )


# ---- Query and chart -----------------------------------------------------------------------------------
CHART_NAMES = {
    "bar": "Bar chart",
    "line": "Line chart",
    "scatter": "Scatter plot",
    "bar_panels": "Bar charts, one panel per metric",
    "line_panels": "Line charts, one panel per metric",
    "table": "Table",
}


def _step(n: int, text: str) -> None:
    render(f'<div class="eis-label" style="margin:10px 0 4px">Step {n} · {esc(text)}</div>')


def page_query(ctx: Ctx) -> None:
    with session_scope(ctx.engine) as s:
        years = kpi_years(s)
    people = people_of(ctx)
    header(
        "Query and chart",
        "Ask for exactly the data you want. Choose the type of data, the metrics, the companies and the "
        "years, and a chart is drawn automatically from the shape of your question.",
        "Whatever you choose. The page restates your question in words before showing the answer.",
        "Work down the five steps. The chart type is chosen for you and the reason is shown; you can "
        "override it.",
    )
    if not years or not people.codes:
        empty_state("No metrics loaded yet", "", "query_stats")
        return
    catalog = metric_catalog(ctx.indicators)
    section("What do you want to explore?")
    with st.container(border=True, key="query-panel"):
        _step(1, "Type of data")
        kind_label = st.radio(
            "Type of data",
            [
                "Derived metrics: per ₹ crore of revenue, or percentages. Comparable between companies of different size.",
                "Reported figures: the raw totals as filed. They grow with company size.",
            ],
            label_visibility="collapsed",
            key="query_kind",
        )
        derived = kind_label.startswith("Derived")
        options = {
            kpi_title(m["label"], m["unit"]): m["code"]
            for m in catalog
            if m["kind"] == ("derived" if derived else "reported")
        }
        _step(2, "Measure")
        metric_labels = st.multiselect(
            "Metrics",
            list(options),
            default=list(options)[:1],
            label_visibility="collapsed",
            key=f"query_metrics_{'d' if derived else 'r'}",
        )
        _step(3, "Companies")
        left, right = st.columns(2)
        sectors = left.multiselect(
            "Whole sectors", people.sectors(), default=people.sectors()[:1], key="query_sectors"
        )
        singles = right.multiselect(
            "Individual companies (added to the sectors)",
            people.codes,
            format_func=people.label,
            key="query_companies",
        )
        codes = list(dict.fromkeys([c for s in sectors for c in people.in_sector(s)] + singles))
        a, b = st.columns([2, 1])
        with a:
            _step(4, "Years")
            default_year = (
                ctx.cfg.study.analysis_fy if ctx.cfg.study.analysis_fy in years else years[-1]
            )
            chosen_years = st.multiselect(
                "Years",
                years,
                default=[default_year],
                label_visibility="collapsed",
                key="query_years",
            )
        with b:
            _step(5, "Chart")
            chart_choice = st.selectbox(
                "Chart",
                ["Automatic (recommended)", "Bar", "Line", "Scatter", "Table only"],
                label_visibility="collapsed",
                key="query_chart",
            )
    if not (metric_labels and codes and chosen_years):
        st.info("Choose at least one metric, one company (or sector) and one year.")
        return
    metric_codes = [options[m] for m in metric_labels]
    with session_scope(ctx.engine) as s:
        data = query_data(s, metric_codes, codes, chosen_years, ctx.indicators)
    section("Result")
    names = {c: people.label(c) for c in codes}
    shown = ", ".join(names[c] for c in codes[:6]) + (
        f" and {len(codes) - 6} more" if len(codes) > 6 else ""
    )
    st.markdown(
        f"**Your question.** {', '.join(metric_labels)} for {len(codes)} "
        f"{'company' if len(codes) == 1 else 'companies'} ({shown}) in {', '.join(chosen_years)}."
    )
    if data.empty:
        empty_state(
            "No values match this question",
            "The companies may not have filings loaded for these years.",
            "search_off",
        )
        return
    data["company"] = data["code"].map(people.short)
    data["metric_label"] = data["metric"] + " (" + data["unit"] + ")"
    n_metrics, n_companies, n_years = (
        data["metric_code"].nunique(),
        data["code"].nunique(),
        data["fy"].nunique(),
    )
    kind, reason = choose_chart(n_metrics, n_companies, n_years)
    override = {"Bar": "bar", "Line": "line", "Scatter": "scatter", "Table only": "table"}.get(
        chart_choice
    )
    if override:
        kind, reason = _apply_override(override, kind, n_metrics, n_years)
    with st.container(key="chart-reco"):
        render(
            f'<div class="eis-label">Recommended visualisation</div>'
            f'<div style="margin:6px 0 4px">{badge(CHART_NAMES.get(kind, kind), "accent", "bar_chart")}</div>'
        )
        st.caption(f"Chart chosen: {reason}")
    if derived and len({people.sector(c) for c in codes}) > 1:
        st.warning(CROSS_SECTOR_WARNING)
    if not derived:
        st.warning(
            "Reported figures are raw totals. A bigger company will look larger on almost every one, so do not read them as better or worse. Use derived metrics to compare."
        )
    _draw_query_chart(data, kind, people)
    section("What this shows")
    directions = {m["label"]: m["better"] for m in catalog}
    for line in describe_query(data, names, directions):
        st.markdown(f"- {line}")
    flagged = data[data["data check"] != ""]
    if not flagged.empty:
        st.warning(
            f"{len(flagged)} value(s) fail a data-quality check and should be used with care: "
            + "; ".join(
                f"{names[r['code']]}, {r['metric']}, {r['fy']} ({r['data check']})"
                for r in flagged.to_dict("records")
            )
        )
    section("The numbers")
    wide = data.pivot_table(
        index="company", columns=["metric_label", "fy"], values="value", sort=False
    )
    wide.columns = [f"{m}, {fy}" for m, fy in wide.columns]
    st.dataframe(
        wide.reset_index().rename(columns={"company": "Company"}), hide_index=True, width="stretch"
    )
    export = data.assign(company=data["code"].map(people.label))[
        ["company", "sector", "fy", "metric", "unit", "value", "data check"]
    ]
    st.download_button(
        "Export these numbers (CSV)",
        export.to_csv(index=False),
        "query_result.csv",
        "text/csv",
        icon=":material/download:",
    )


def _apply_override(override: str, auto: str, n_metrics: int, n_years: int) -> tuple[str, str]:
    """Honour a chosen chart type where it makes sense, and say so when it does not."""
    if override == "table":
        return "table", "you chose a table."
    if override == "line":
        if n_years < 2:
            return (
                "bar" if n_metrics == 1 else "bar_panels",
                "a line needs more than one year, so a bar chart is shown instead.",
            )
        return ("line" if n_metrics == 1 else "line_panels"), "you chose a line chart."
    if override == "scatter":
        if n_metrics != 2 or n_years != 1:
            return (
                auto,
                "a scatter plot needs exactly two metrics and one year, so the automatic choice is shown instead.",
            )
        return "scatter", "you chose a scatter plot."
    return ("bar" if n_metrics == 1 else "bar_panels"), "you chose a bar chart."


def _draw_query_chart(data: pd.DataFrame, kind: str, people) -> None:
    if kind == "table":
        return
    multi_year = data["fy"].nunique() > 1
    if kind == "bar":
        metric = data["metric_label"].iloc[0]
        ordered = data.sort_values("value")
        horizontal = data["company"].nunique() > 8
        fig = px.bar(
            ordered,
            x="value" if horizontal else "company",
            y="company" if horizontal else "value",
            color="fy" if multi_year else "sector",
            barmode="group",
            orientation="h" if horizontal else "v",
            labels={"value": metric, "company": "", "fy": "Fiscal year", "sector": "Sector"},
            hover_data={"metric_label": False},
        )
    elif kind == "line":
        metric = data["metric_label"].iloc[0]
        fig = px.line(
            data,
            x="fy",
            y="value",
            color="company",
            markers=True,
            labels={"fy": "Fiscal year", "value": metric, "company": "Company"},
        )
    elif kind == "scatter":
        wide = data.pivot_table(
            index=["company", "sector"], columns="metric_label", values="value"
        ).reset_index()
        x_label, y_label = [c for c in wide.columns if c not in ("company", "sector")]
        fig = px.scatter(
            wide, x=x_label, y=y_label, color="sector", text="company", hover_name="company"
        )
        fig.update_traces(textposition="top center", marker={"size": 11})
    elif kind == "bar_panels":
        fig = px.bar(
            data,
            x="company",
            y="value",
            color="fy" if multi_year else "company",
            barmode="group",
            facet_col="metric_label",
            facet_col_wrap=3,
            labels={"company": "", "value": "", "fy": "Fiscal year"},
        )
        fig.update_layout(showlegend=multi_year)
    else:  # line_panels
        fig = px.line(
            data,
            x="fy",
            y="value",
            color="company",
            markers=True,
            facet_col="metric_label",
            facet_col_wrap=3,
            labels={"fy": "", "value": "", "company": "Company"},
        )
    if kind.endswith("_panels"):
        fig.update_yaxes(matches=None, showticklabels=True)
        fig.update_xaxes(matches=None, showticklabels=True)
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    show(fig)
