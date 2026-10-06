"""The interpretation layer: positions, movements, readings, scenarios, trust and knowledge.

All expectations are worked out by hand from the dataset in `fixture_world` and written as literals.
"""

from __future__ import annotations

import math
import re
import sys
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from fixture_alpha import ALPHA, FY, PRIOR
from gauge import vocab
from gauge.db.session import session_scope
from gauge.viewdata import (
    BAND_FLAT,
    BANDS,
    CAPABILITIES,
    DATA_CHECK,
    GLOSSARY,
    LIMITS,
    NO_BAND,
    attention_list,
    band_for,
    company_brief_markdown,
    company_reading,
    data_as_of,
    evidence_quality,
    evidence_sentence,
    flag_counts,
    fmt_number,
    gap_to_benchmark,
    indicator_guide,
    kpi_matrix,
    kpi_over_time,
    rank_after_change,
    reviewer_notes,
    sector_overview,
    what_if,
)


# ---- bands and ranks -----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("rank", "n", "band"),
    [
        (1, 5, BANDS[0]),
        (2, 5, BANDS[0]),
        (3, 5, BANDS[1]),
        (4, 5, BANDS[2]),
        (5, 5, BANDS[2]),
        (1, 3, BANDS[0]),
        (2, 3, BANDS[1]),
        (3, 3, BANDS[2]),
        (1, 4, BANDS[0]),
        (2, 4, BANDS[0]),
        (3, 4, BANDS[2]),
        (4, 4, BANDS[2]),
        (1, 2, NO_BAND),
        (1, 1, NO_BAND),
    ],
)
def test_thirds_are_by_rank_rounded_up(rank, n, band):
    assert band_for(rank, n) == band


def test_rank_after_change_lets_ties_share_the_better_rank():
    values = {"a": 10.0, "b": 20.0, "c": 30.0, "d": 40.0, "e": 50.0}
    # e falls to 20: only a (10) is strictly better, and it ties b, so rank 2 of 5
    assert rank_after_change(values, "e", 20.0, "lower") == (2, 5, BANDS[0])
    # for a higher-is-better KPI, 30 and 40 beat 20: rank 3 of 5, the middle
    assert rank_after_change(values, "e", 20.0, "higher") == (3, 5, BANDS[1])


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1234.6, "1,235"),
        (123.4, "123"),
        (12.34, "12.3"),
        (1.234, "1.23"),
        (0.1234, "0.123"),
        (0.001234, "0.0012"),
        (0, "0"),
        (-5200.4, "-5,200"),
        (float("nan"), "n/a"),
        (1.09e6, "1,090,000"),
    ],
)
def test_numbers_are_never_shown_in_scientific_notation(value, text):
    assert fmt_number(value) == text


# ---- overview: positions, movement, flagged figures ----------------------------------------
def test_emissions_positions_movements_and_medians(fixture_world):
    ind = fixture_world.ind
    with session_scope(fixture_world.engine) as s:
        frame = sector_overview(s, FY, "emissions_intensity", ind)
    alpha = frame[frame["sector"] == "Test Alpha"]
    assert list(alpha["code"]) == ALPHA
    assert list(alpha["rank in sector"]) == [1, 2, 3, 4, 5]
    assert set(alpha["companies compared"]) == {5}
    assert list(alpha["band"]) == [BANDS[0], BANDS[0], BANDS[1], BANDS[2], BANDS[2]]
    assert list(alpha["movement"]) == [
        "about the same",
        "better",
        "worse",
        "about the same",
        "worse",
    ]
    assert list(alpha["change %"]) == pytest.approx(
        [0.0, -20.0, 100 * 3 / 27, -100 * 0.2 / 40.2, 25.0]
    )
    assert set(alpha["sector median"]) == {30.0}
    assert list(alpha["vs sector median"]) == ["better", "better", "at median", "worse", "worse"]
    beta = frame[frame["sector"] == "Test Beta"]
    assert list(beta["band"]) == [NO_BAND, NO_BAND]  # two companies cannot be placed in thirds
    assert beta["sector median"].isna().all()


def test_an_impossible_figure_is_shown_but_not_ranked_or_counted(fixture_world):
    with session_scope(fixture_world.engine) as s:
        frame = sector_overview(s, FY, "waste_recovery_rate", fixture_world.ind).set_index("code")
    # XAA-05 recovered 103%: shown, not ranked, and left out of the median
    bad = frame.loc["XAA-05"]
    assert bad["value"] == 103.0 and bad["band"] == DATA_CHECK and math.isnan(bad["change %"])
    assert bad["data check"] == "recovered_le_generated" and bad["vs sector median"] == "n/a"
    # the other four are ranked among themselves, higher is better: 98, 97, 96, 95
    assert [frame.loc[c, "rank in sector"] for c in ("XAA-04", "XAA-03", "XAA-02", "XAA-01")] == [
        1,
        2,
        3,
        4,
    ]
    assert set(frame["companies compared"]) == {4}
    assert [frame.loc[c, "band"] for c in ("XAA-04", "XAA-03", "XAA-02", "XAA-01")] == [
        BANDS[0],
        BANDS[0],
        BANDS[2],
        BANDS[2],
    ]
    assert set(frame[frame["data check"] == ""]["sector median"]) == {96.5}  # (96 + 97) / 2


def test_a_movement_is_not_measured_against_a_prior_year_that_failed_a_check(fixture_world):
    with session_scope(fixture_world.engine) as s:
        frame = sector_overview(s, FY, "waste_recovery_rate", fixture_world.ind).set_index("code")
    # XAA-02's FY2023-24 value (90) is flagged, so there is no change to report
    assert math.isnan(frame.loc["XAA-02", "change %"]) and frame.loc["XAA-02", "movement"] == "n/a"
    # XAA-01's prior year (94) is clean: (95-94)/94 = +1.0638%, higher is better, above the 1% tolerance
    assert frame.loc["XAA-01", "change %"] == pytest.approx(100 / 94)
    assert frame.loc["XAA-01", "movement"] == "better"


def test_nearly_identical_values_are_not_ranked_into_thirds(fixture_world):
    with session_scope(fixture_world.engine) as s:
        frame = sector_overview(s, FY, "renewable_share", fixture_world.ind)
    # 50.0 .. 50.4 against a median of 50.2: a spread of 0.8%, under the 1% tolerance
    assert set(frame["band"]) == {BAND_FLAT}
    assert list(frame["rank in sector"]) == [1, 2, 3, 4, 5]  # still shown, but with no weight
    assert list(frame["code"]) == [
        "XAA-05",
        "XAA-04",
        "XAA-03",
        "XAA-02",
        "XAA-01",
    ]  # higher is better


def test_the_matrix_holds_every_kpi_that_has_data(fixture_world):
    with session_scope(fixture_world.engine) as s:
        matrix = kpi_matrix(s, FY, fixture_world.ind)
    assert set(matrix["kpi"]) == {"emissions_intensity", "waste_recovery_rate", "renewable_share"}
    assert len(matrix) == 7 + 5 + 5


def test_the_over_time_table_has_every_year_loaded(fixture_world):
    with session_scope(fixture_world.engine) as s:
        lines = kpi_over_time(s, "emissions_intensity")
    assert len(lines) == 5 * 2 + 2  # five companies in two years, two in one
    assert list(lines["fy"][:2]) == [PRIOR, FY] and list(lines["code"][:2]) == ["XAA-01"] * 2


def test_data_as_of_gives_the_latest_year_and_retrieval(fixture_world):
    with session_scope(fixture_world.engine) as s:
        assert data_as_of(s) == {"latest_fy": FY, "retrieved_on": date(2026, 10, 3)}


# ---- attention -------------------------------------------------------------------------------
def test_attention_puts_data_errors_first_then_the_biggest_wrong_way_moves(fixture_world):
    with session_scope(fixture_world.engine) as s:
        found = attention_list(s, FY, fixture_world.ind, worsening_pct=10.0)
        stricter = attention_list(s, FY, fixture_world.ind, worsening_pct=20.0)
    assert list(zip(found["kind"], found["code"], found["item"], strict=True)) == [
        ("data", "XAA-05", "data-quality errors"),
        ("movement", "XAA-05", "Emissions intensity (Scope 1+2)"),  # +25.0%
        ("movement", "XAA-03", "Emissions intensity (Scope 1+2)"),  # +11.1%
    ]
    assert (
        "worsened by 25.0% against the previous year (40.0 to 50.0 tCO2e per ₹ crore)"
        in (found["detail"][1])
    )
    assert list(stricter["code"]) == ["XAA-05", "XAA-05"]  # the 11.1% move drops out


# ---- trust ------------------------------------------------------------------------------------
def test_flag_counts_and_evidence_quality(fixture_world):
    with session_scope(fixture_world.engine) as s:
        assert flag_counts(s, FY) == {
            "XAA-05": {"errors": 1, "warnings": 0},
            "XAA-03": {"errors": 0, "warnings": 1},
        }
        good = evidence_quality(s, "XAA-01", FY)
        assert good == {
            "errors": 0,
            "warnings": 0,
            "values": 2,
            "checked": 1,
            "assured": True,
            "boundary": "standalone",
            "entry_method": "xbrl",
            "filing": True,
        }
        assert evidence_sentence(good) == (
            "0 error and 0 warning flags; 1 of 2 values checked by a person; assured; reporting "
            "boundary standalone; read from the filing's own XBRL."
        )
        assert evidence_sentence(evidence_quality(s, "XAA-02", FY)) == (
            "no filing is loaded for this year."
        )


def test_reviewer_notes_come_back_with_the_indicator_label(fixture_world):
    with session_scope(fixture_world.engine) as s:
        notes = reviewer_notes(s, "XAA-01", fixture_world.ind)
    assert list(notes["indicator"]) == ["Scope 1 emissions"]
    assert list(notes["result"]) == ["ok"] and list(notes["note"]) == ["matches page 48"]


# ---- readings, gap and what-if -------------------------------------------------------------
def test_the_reading_states_position_movement_and_evidence_in_words(fixture_world):
    with session_scope(fixture_world.engine) as s:
        third = company_reading(s, "XAA-03", FY, fixture_world.ind)
        first = company_reading(s, "XAA-01", FY, fixture_world.ind)
        broken = company_reading(s, "XAA-05", FY, fixture_world.ind)
    assert (
        "Emissions intensity (Scope 1+2): 30.0 tCO2e per ₹ crore; rank 3 of 5 in Test Alpha "
        "(1 = best), middle third; 11.1% higher than the previous year (worse)."
    ) in third
    assert any("almost identical" in line and "Renewable energy share" in line for line in third)
    assert "Better third of its sector sample on: Emissions intensity (Scope 1+2)." in first
    assert "Weaker third of its sector sample on: Waste recovery rate." in first
    assert (
        "Waste recovery rate: 103 %; not ranked, because it fails a data-quality check "
        "(recovered_le_generated)."
    ) in broken
    assert broken[-1].startswith("Evidence: 1 error and 0 warning flags")


def test_the_gap_to_the_median_is_arithmetic_on_the_median_of_clean_peers(fixture_world):
    ind = fixture_world.ind
    with session_scope(fixture_world.engine) as s:
        far = gap_to_benchmark(s, "XAA-04", FY, ind).set_index("kpi")
        near = gap_to_benchmark(s, "XAA-01", FY, ind).set_index("kpi")
        broken = gap_to_benchmark(s, "XAA-05", FY, ind).set_index("kpi")
    label = "Emissions intensity (Scope 1+2)"
    # 40 against a median of 30, lower is better: (30-40)/40 = -25%
    assert far.loc[label, "change to reach median %"] == pytest.approx(-25.0)
    assert far.loc[label, "reading"] == "a fall of 25.0% would reach the median"
    assert far.loc[label, "basis"] == "median of the 5 companies compared"
    assert near.loc[label, "reading"] == "already at or better than the median"
    # 50.0 against a median of 50.2, higher is better: a rise of 0.4% would reach it
    assert near.loc["Renewable energy share", "reading"] == "a rise of 0.4% would reach the median"
    assert broken.loc["Waste recovery rate", "reading"].startswith("n/a")


def test_what_if_is_arithmetic_with_everyone_else_held_fixed(fixture_world):
    ind = fixture_world.ind
    with session_scope(fixture_world.engine) as s:
        result = what_if(s, "XAA-04", FY, "emissions_intensity", -50.0, ind)
        none = what_if(s, "XAA-05", FY, "waste_recovery_rate", 10.0, ind)  # fails a check
        missing = what_if(s, "XAA-04", FY, "water_intensity", 10.0, ind)  # no such values
    # 40 falls to 20; the others (10, 20, 30, 50) leave only 10 strictly better: rank 2 of 5
    assert result == {
        "kpi": "Emissions intensity (Scope 1+2)",
        "unit": "tCO2e per ₹ crore",
        "value_now": 40.0,
        "value_after": 20.0,
        "rank_now": 4,
        "rank_after": 2,
        "n": 5,
        "band_now": BANDS[2],
        "band_after": BANDS[0],
    }
    assert none is None and missing is None


# ---- knowledge --------------------------------------------------------------------------------
def test_the_indicator_guide_is_written_from_the_config_the_code_runs(fixture_world):
    inputs, kpis = indicator_guide(fixture_world.ind)
    assert len(inputs) == 9 and len(kpis) == 5
    row = kpis[kpis["KPI"] == "Emissions intensity (Scope 1+2)"].iloc[0]
    assert (
        row["how it is computed"]
        == "(Scope 1 emissions + Scope 2 emissions) / Revenue from operations"
    )
    assert row["direction"] == "lower is better" and row["core KPI"] == "yes"
    assert kpis[kpis["KPI"] == "Renewable energy share"].iloc[0]["direction"] == "higher is better"


def test_every_capability_points_at_a_real_view_and_every_term_is_defined():
    for capability, views, does in CAPABILITIES:
        assert capability and does and views
        assert set(views) <= set(vocab.DASHBOARD_VIEWS), capability
    assert len({c for c, _, _ in CAPABILITIES}) == len(CAPABILITIES)
    assert all(len(text) > 10 for text in GLOSSARY.values())
    assert any(vocab.SDG_CAPTION in limit for limit in LIMITS)


def test_the_briefing_is_complete_and_makes_no_claim_the_data_cannot_support(fixture_world):
    ind = fixture_world.ind
    with session_scope(fixture_world.engine) as s:
        brief = company_brief_markdown(s, "XAA-01", FY, ind, "XAA-01 (XAA-01 Ltd)")
        broken = company_brief_markdown(s, "XAA-05", FY, ind, "XAA-05")
    assert brief.startswith("# XAA-01 (XAA-01 Ltd): environmental KPI briefing, FY2024-25")
    for heading in (
        "## Reading",
        "## Figures",
        "## Distance from the sector median",
        "## Data-quality flags",
        "## Where the figures came from",
        "## Read this with care",
    ):
        assert heading in brief
    assert "cd" * 32 in brief and "data/raw/xbrl/A1.xml" in brief  # provenance
    assert (
        "| Emissions intensity (Scope 1+2) | 10.0 tCO2e per ₹ crore | 1 of 5 | better third |"
        in brief
    )
    assert "not ranked" in broken and "recovered_le_generated" in broken
    for text in (brief, broken):
        assert "greener than" not in text and "thinks" not in text  # spec §11
        assert "self-reported" in text and "not a forecast" in text


# ---- the app: scorecard, drill-down, company page ---------------------------------------------
def _run(monkeypatch, repo_root, config="config/study_dry.yaml") -> AppTest:
    monkeypatch.setattr(sys, "argv", ["app.py", "--config", config])
    return AppTest.from_file(str(repo_root / "dashboard" / "app.py"), default_timeout=120).run()


def go(at: AppTest, page: str) -> AppTest:
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _scorecard(at: AppTest) -> tuple[list[str], dict[str, list[tuple[str, str, str]]]]:
    """The scorecard matrix drawn by the page: its column headers, and for each company the
    (position class, text of the cell, tooltip) of every metric."""
    html = next(
        e.proto.body
        for e in at.get("html")
        if "eis-table" in e.proto.body and "eis-cell" in e.proto.body
    )
    headers = [re.sub(r"<[^>]+>", " ", h) for h in re.findall(r"<th[^>]*>(.*?)</th>", html, re.S)]
    rows = {}
    for row in re.findall(r"<tr><td class=\"firstcol\">(.*?)</tr>", html, re.S):
        name = re.search(r"<b>(.*?)</b>", row).group(1)
        cells = re.findall(
            r'<div class="eis-cell ([a-z]+)"[^>]*data-tip="([^"]*)">(.*?)</div>', row, re.S
        )
        rows[name] = [
            (css, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip(), tip)
            for css, tip, body in cells
        ]
    return headers, rows


def test_the_scorecard_colours_each_cell_by_its_position(fixture_world, repo_root, monkeypatch):
    at = go(_run(monkeypatch, repo_root), "KPI scorecard")
    headers, rows = _scorecard(at)
    assert len(rows) == 7  # seven companies
    column = next(i for i, h in enumerate(headers[1:]) if h.startswith("Emissions intensity"))
    assert "tCO2e per \u20b9 crore" in headers[1:][column]  # units in the column header
    css = lambda name, col: rows[name][col][0]  # noqa: E731
    text = lambda name, col: rows[name][col][1]  # noqa: E731
    assert css("XAA-01 Ltd", column) == "better" and text("XAA-01 Ltd", column).startswith("10.0")
    assert css("XAA-03 Ltd", column) == "middle" and css("XAA-05 Ltd", column) == "weaker"
    waste = next(i for i, h in enumerate(headers[1:]) if h.startswith("Waste recovery"))
    assert css("XAA-05 Ltd", waste) == "check"  # the impossible 103% is amber, not ranked
    assert "Data check" in text("XAA-05 Ltd", waste) and " of " not in text("XAA-05 Ltd", waste)
    renewable = next(i for i, h in enumerate(headers[1:]) if h.startswith("Renewable"))
    assert css("XAA-02 Ltd", renewable) == "flat"  # no clear difference
    assert css("XBB-01 Ltd", column) == "na"  # two companies: no position


def test_the_scorecard_labels_rows_with_real_names_in_the_table_and_hover(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "KPI scorecard")
    _, rows = _scorecard(at)
    assert any("XAA-01 Ltd" in tip for cells in rows.values() for _, _, tip in cells)
    assert at.dataframe[0].value["Company"].iloc[0] == "XAA-01 Ltd"


def test_drilling_down_from_the_scorecard_opens_that_company(fixture_world, repo_root, monkeypatch):
    at = go(_run(monkeypatch, repo_root), "KPI scorecard")
    at.selectbox(key="scorecard_pick").set_value("XAA-03").run()
    at.button(key="scorecard_open").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.sidebar.radio[0].value == "Companies"
    assert at.selectbox(key="company_pick").value == "XAA-03"
    assert any("What the numbers say" in e.proto.body for e in at.get("html"))
    # switching names to masked codes keeps the same company selected
    at.sidebar.toggle[0].set_value(False).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox(key="company_pick").value == "XAA-03"


def test_the_company_page_reads_the_figures_offers_a_briefing_and_a_what_if(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Companies")
    at.selectbox(key="company_pick").set_value("XAA-04").run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.get("download_button")) == 1
    at.selectbox(key="whatif_kpi").set_value("Emissions intensity (Scope 1+2)").run()
    at.slider(key="whatif_change").set_value(-50).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(
        "would move from 4 to 2 of 5 (weaker third to better third)" in m.value for m in at.markdown
    )
    assert any("not a forecast" in c.value for c in at.caption)


def test_the_company_page_explains_each_metric_with_its_unit(fixture_world, repo_root, monkeypatch):
    at = go(_run(monkeypatch, repo_root), "Companies")
    at.selectbox(key="company_pick").set_value("XAA-03").run()
    titles = [e.label for e in at.expander]
    assert "Emissions intensity (Scope 1+2): 30.0 tCO2e per \u20b9 crore" in titles
    text = " ".join(m.value for m in at.markdown)
    assert (
        "For every \u20b91 crore (\u20b910 million) of revenue the company emitted 30.0 tonnes"
        in text
    )
    assert "The median of its sector is 30.0" in text
    table = next(d.value for d in at.dataframe if "Unit" in d.value.columns)
    emissions = table[table["Metric"] == "Emissions intensity (Scope 1+2)"].iloc[0]
    assert (emissions["Value"], emissions["Unit"]) == ("30.0", "tCO2e per \u20b9 crore")


def test_switching_names_on_and_off_keeps_the_company_picker_working(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Companies")
    at.selectbox(key="company_pick").set_value("XAA-04").run()
    at.sidebar.toggle[0].set_value(False).run()
    at.sidebar.toggle[0].set_value(True).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox(key="company_pick").value == "XAA-04"
