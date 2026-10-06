"""The redesigned pages under AppTest: the principles the interface must keep (positions are words,
a data check is never a rank, units and sources stay visible, benchmarks are the study sample) and
the navigation between pages. Hand-made data: tests/fixture_alpha.py."""

from __future__ import annotations

import re
import sys

from streamlit.testing.v1 import AppTest

from fixture_alpha import FY, PRIOR


def _run(monkeypatch, repo_root, config="config/study_dry.yaml") -> AppTest:
    monkeypatch.setattr(sys, "argv", ["app.py", "--config", config])
    return AppTest.from_file(str(repo_root / "dashboard" / "app.py"), default_timeout=120).run()


def go(at: AppTest, page: str) -> AppTest:
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def html_of(at: AppTest) -> str:
    """Every st.html block on the page, as written."""
    return "\n".join(e.proto.body for e in at.get("html"))


def visible(at: AppTest) -> str:
    """The text of those blocks with tags removed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_of(at)))


# ---- shell --------------------------------------------------------------------------------------
def test_the_shell_has_the_brand_the_pilot_block_and_grouped_navigation(
    fixture_world, repo_root, monkeypatch
):
    at = _run(monkeypatch, repo_root)
    text = visible(at)
    assert "Green Executive Information System" in text
    assert "Pilot dataset" in text and "Latest year loaded" in text
    css = html_of(at)
    for group in ("Overview", "Analysis", "Assurance", "Reference"):
        assert f'content:"{group}"' in css
    assert "<style>" in css and "--accent" in css  # the design system was injected


def test_the_top_bar_search_opens_a_page_a_sector_or_a_company(
    fixture_world, repo_root, monkeypatch
):
    at = _run(monkeypatch, repo_root)
    search = at.selectbox(key="eis_search")
    assert "Page · Sectors" in search.options and "Sector · Test Alpha" in search.options
    assert "Company · XAA-01 Ltd · Test Alpha" in search.options
    at.selectbox(key="eis_search").set_value("Page · Compare companies").run()
    assert at.sidebar.radio[0].value == "Compare companies" and not at.exception
    at.selectbox(key="eis_search").set_value("Sector · Test Beta").run()
    assert (
        at.sidebar.radio[0].value == "Sectors" and at.radio(key="sector_pick").value == "Test Beta"
    )
    at.selectbox(key="eis_search").set_value("Company · XAA-03 Ltd · Test Alpha").run()
    assert at.sidebar.radio[0].value == "Companies"
    assert at.selectbox(key="company_pick").value == "XAA-03"
    assert at.selectbox(key="eis_search").value is None  # reset, ready for the next search


def test_the_search_follows_the_names_switch(fixture_world, repo_root, monkeypatch):
    at = _run(monkeypatch, repo_root)
    at.sidebar.toggle[0].set_value(False).run()
    options = at.selectbox(key="eis_search").options
    assert "Company · XAA-01 · Test Alpha" in options
    assert not any("XAA-01 Ltd" in o for o in options)


# ---- the home page: needs attention is about figures, not about companies -----------------------
def test_home_lists_the_figure_that_fails_a_check_without_ranking_or_blaming(
    fixture_world, repo_root, monkeypatch
):
    at = _run(monkeypatch, repo_root)
    text = visible(at)
    assert "1 figure require review" in text
    assert "XAA-05 Ltd" in text and "Waste recovery rate" in text and "103.0" in text
    assert "Data check" in text
    assert "not a finding that a company misreported" in text
    assert "Waste recovered exceeds waste generated." in text
    exceptions = next(e.proto.body for e in at.get("html") if "eis-exceptions" in e.proto.body)
    assert "#1" not in exceptions and "rank" not in re.sub(r"<[^>]+>", " ", exceptions).lower()


def test_home_shows_the_chain_of_assurance_with_real_counts(fixture_world, repo_root, monkeypatch):
    text = visible(_run(monkeypatch, repo_root))
    for step in ("Filings", "Standardised", "Validated", "Computed", "Verified by a person"):
        assert step in text
    assert "1 of 2" in text  # one of the two stored values has been checked by a person


# ---- the scorecard: colours are positions, a data check is not placed ---------------------------
def test_the_scorecard_cells_say_where_a_figure_sits_and_never_rank_a_data_check(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "KPI scorecard")
    html = html_of(at)
    cells = re.findall(r'<div class="eis-cell ([a-z]+)"[^>]*>(.*?)</div>', html, re.S)
    by_class = {}
    for css, body in cells:
        by_class.setdefault(css, []).append(re.sub(r"<[^>]+>", " ", body))
    assert any("Data check" in b and " of " not in b for b in by_class["check"])  # XAA-05's 103%
    assert any(
        "No clear difference" in b for b in by_class["flat"]
    )  # renewable share, all within 1%
    assert any("Better third · 1 of 4" in b for b in by_class["better"])
    text = visible(at)
    assert "not environmental ratings" in text and "ESG scores" in text
    assert "tCO2e per ₹ crore" in text  # units are in the column headers
    assert "lower is better" in text and "higher is better" in text


def test_the_scorecard_sector_filter_keeps_sectors_apart(fixture_world, repo_root, monkeypatch):
    at = go(_run(monkeypatch, repo_root), "KPI scorecard")
    at.selectbox(key="scorecard_sector").set_value("Test Beta").run()
    assert not at.exception
    text = visible(at)
    assert "XBB-01 Ltd" in text and "XAA-01 Ltd" not in text


# ---- sectors: the benchmark is the study sample -------------------------------------------------
def test_the_sector_page_calls_the_benchmark_the_study_sample_and_not_the_industry(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Sectors")
    text = visible(at)
    assert "Study-sample median" in text and "P25 to P75" in text
    assert "Not an external industry benchmark" in text
    assert re.search(r"industry benchmark", text, re.I) and "Industry median" not in text
    emissions = re.search(r"Emissions intensity.*?(\d[\d,.]*)</b>", html_of(at), re.S)
    assert emissions  # a median is drawn for the sample


# ---- the register -------------------------------------------------------------------------------
def test_the_register_has_status_actions_and_never_says_a_company_misreported(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Data quality register")
    text = visible(at)
    assert "Needs verification" in text and "not yet reviewed" in text
    assert "103.0 %" in text and "waste recovered exceeds waste generated" in text
    for forbidden in ("misreported by", "fraud", "violated", "breached"):
        assert forbidden not in text.lower()
    assert at.button(key="register_source")
    at.button(key="register_source").click().run()
    assert at.sidebar.radio[0].value == "Sources and filings" and not at.exception


# ---- the company page: evidence, then the trace to the filing -----------------------------------
def test_the_company_page_makes_the_evidence_visible(fixture_world, repo_root, monkeypatch):
    at = go(_run(monkeypatch, repo_root), "Companies")
    at.selectbox(key="company_pick").set_value("XAA-01").run()
    text = visible(at)
    assert "Can these numbers be checked?" in text
    assert "Source identified" in text and "data/raw/xbrl/A1.xml" in text
    assert "SHA-256 cdcdcdcdcdcd…cdcdcd" in text and "retrieved 2026-10-02" in text
    assert "Partly verified by a person" in text and "1 of 2 values" in text
    assert "vs study-sample median" in text or "No study-sample median" in text
    assert "Not a forecast" in text or any("not a forecast" in c.value for c in at.caption)


def test_a_company_without_a_checkable_source_says_so_plainly(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Companies")
    at.selectbox(key="company_pick").set_value("XAA-02").run()
    text = visible(at)
    assert f"No filing is loaded for {FY}" in text
    assert (
        "Human verification: none" in text
        or "Not yet verified" in text
        or "No stored values" in text
    )


def test_the_company_page_opens_the_trace_with_that_company_and_year_chosen(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Companies")
    at.selectbox(key="company_pick").set_value("XAA-01").run()
    at.button(key="link_company_to_source").click().run()
    assert not at.exception
    assert at.sidebar.radio[0].value == "Sources and filings"
    assert at.selectbox(key="sources_company").value == "XAA-01"
    assert at.selectbox(key="sources_fy").value == FY
    text = visible(at)
    assert "SHA-256 fingerprint" in text and "cd" * 32 in html_of(at)
    assert "Retrieved" in text and "2026-10-02" in text
    assert (
        "Human verification" in text and "0 of 1 inputs" in text
    )  # Energy intensity: one stored input


def test_the_trace_follows_a_kpi_from_value_to_inputs_to_validation(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Sources and filings")
    at.selectbox(key="sources_company").set_value("XAA-01").run()
    at.selectbox(key="sources_kpi").set_value("Emissions intensity (Scope 1+2)").run()
    assert not at.exception
    text = visible(at)
    order = [
        "KPI · Emissions intensity",
        "Input figures",
        "Normalisation",
        "Validation",
        "Source filing",
        "SHA-256 fingerprint",
        "Retrieved",
        "Human verification",
    ]
    positions = [text.index(step) for step in order]
    assert positions == sorted(positions)
    assert "(Scope 1 emissions + Scope 2 emissions) / Revenue from operations" in text
    assert "not in the filing data" in text  # Scope 2 is missing and is said to be missing
    assert at.code[0].value == "cd" * 32  # copyable fingerprint


# ---- verification: the system finding and the human decision are separate -----------------------
def test_verification_separates_the_system_finding_from_the_reviewer_decision(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Data verification")
    at.text_input(key="reviewer").set_value("dana").run()
    assert not at.exception
    text = visible(at)
    assert "System finding" in text and "automatic" in text
    assert "NO FLAG" in text or "FLAGGED" in text
    assert "Reviewer decision" in text and "human" in text
    assert at.radio(key="verification_result").options == ["Yes, it matches", "No, it is wrong"]
    assert (
        at.radio(key="verification_result").value == "ok"
    )  # the two results the data layer stores


# ---- comparison and units -----------------------------------------------------------------------
def test_the_comparison_table_names_units_and_warns_across_sectors(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Compare companies")
    at.multiselect(key="compare_codes").set_value(["XAA-01", "XAA-03"]).run()
    text = visible(at)
    assert "tCO2e per ₹ crore" in text and "lower is better" in text
    assert "Best of those compared" in text
    assert not at.warning
    at.multiselect(key="compare_codes").set_value(["XAA-01", "XBB-01"]).run()
    assert any("Direct comparison may not be meaningful" in w.value for w in at.warning)


def test_the_compliance_page_is_labelled_a_monitoring_view_with_icons_and_words(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Compliance check")
    assert any("Monitoring view, not a legal finding" in w.value for w in at.warning)
    html = html_of(at)
    for word in (
        "Loaded",
        "Stated",
        "Statement present",
        "Consistent",
        "Review required",
        "Check failed",
    ):
        assert word in html
    assert html.count("eis-st ") >= 7  # every result is an icon plus a word
    assert "check_circle" in html and "warning" in html and "cancel" in html


def test_a_chart_choice_is_explained_in_a_labelled_card(fixture_world, repo_root, monkeypatch):
    at = go(_run(monkeypatch, repo_root), "Query and chart")
    metric = "Emissions intensity (Scope 1+2) (tCO2e per ₹ crore)"
    at.multiselect(key="query_metrics_d").set_value([metric]).run()
    at.multiselect(key="query_years").set_value([PRIOR, FY]).run()
    text = visible(at)
    assert "Recommended visualisation" in text and "Line chart" in text
    assert any(c.value.startswith("Chart chosen:") and "trend" in c.value for c in at.caption)


def test_the_metrics_guide_shows_a_formula_for_each_metric(fixture_world, repo_root, monkeypatch):
    at = go(_run(monkeypatch, repo_root), "Metrics guide")
    formulas = [latex.value.strip("$\n") for latex in at.latex]
    assert len(formulas) == 5 and all(f.startswith(r"\frac{") for f in formulas)
    assert any("Scope 1 emissions" in f for f in formulas)
    text = visible(at)
    for heading in (
        "What it measures",
        "How it is computed",
        "How to interpret it",
        "Important limitation",
    ):
        assert heading in text


def test_the_about_page_puts_the_limitations_before_the_methodology(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "About")
    text = visible(at)
    assert text.index("Limitations") < text.index("Data sources and methodology")
    assert "The system does not" in text and "Use a language model on the evidence pages" in text
