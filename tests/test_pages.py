"""The evidence pages: units and explanations, query and automatic charts, comparison, compliance,
and the pages themselves. Expectations are worked out by hand from tests/fixture_alpha.py."""

from __future__ import annotations

import json
import sys

import pytest
from streamlit.testing.v1 import AppTest

from fixture_alpha import FY, PRIOR
from gauge import vocab
from gauge.db.session import session_scope
from gauge.viewdata import (
    CHECK_ORDER,
    CHECK_TITLES,
    CHECK_WHY,
    GLIDE_PATH,
    METRIC_NOTES,
    SECTOR_FALLBACK,
    SECTOR_NOTES,
    _gap_text,
    choose_chart,
    company_directory,
    compare_table,
    comparison_sentences,
    compliance_checks,
    compliance_matrix,
    compliance_summary,
    describe_query,
    explain_value,
    metric_catalog,
    pretty_unit,
    query_data,
    sector_note,
)

RUPEE = "₹"
NAMES = {
    "XAA-01": "Alpha One",
    "XAA-02": "Alpha Two",
    "XAA-03": "Alpha Three",
    "XAA-04": "Alpha Four",
    "XAA-05": "Alpha Five",
}
EVIDENCE = [
    "Home",
    "Sectors",
    "KPI scorecard",
    "Companies",
    "Compare companies",
    "Query and chart",
    "Compliance check",
    "Data quality register",
    "Sources and filings",
    "Data verification",
    "Metrics guide",
    "About",
]


# ---- units and explanations -------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("kL per INR crore", f"kL per {RUPEE} crore"),
        ("INR_crore", f"{RUPEE} crore"),
        ("tCO2e", "tCO2e"),
        ("%", "%"),
    ],
)
def test_units_are_written_the_way_a_person_writes_them(raw, shown):
    assert pretty_unit(raw) == shown


@pytest.mark.parametrize(
    ("code", "value", "median", "text"),
    [
        (
            "water_intensity", 498, 250,
            f"For every {RUPEE}1 crore ({RUPEE}10 million) of revenue the company consumed 498 "
            "kilolitres of water, which is 498,000 litres. The median of its sector is 250, so this "
            "is 99% above it.",
        ),
        (
            "water_intensity", 100, 250,
            f"For every {RUPEE}1 crore ({RUPEE}10 million) of revenue the company consumed 100 "
            "kilolitres of water, which is 100,000 litres. The median of its sector is 250, so this "
            "is 60% below it.",
        ),
        (
            "energy_intensity", 4272.04, None,
            f"For every {RUPEE}1 crore ({RUPEE}10 million) of revenue the company used 4,272 "
            "gigajoules of energy, about 1.19 million kWh.",
        ),
        (
            "emissions_intensity", 1013.3, None,
            f"For every {RUPEE}1 crore ({RUPEE}10 million) of revenue the company emitted 1,013 "
            "tonnes of greenhouse gas (CO2-equivalent, Scope 1 and 2).",
        ),
        (
            "renewable_share", 5.39, None,
            "5.39% of the energy the company consumed came from renewable sources, so about 5.39 of "
            "every 100 gigajoules.",
        ),
        (
            "waste_recovery_rate", 99.8, None,
            "99.8% of the waste the company generated was recovered through recycling, re-use or "
            "other recovery operations.",
        ),
        ("not_a_metric", 7, None, "7.00."),
    ],
)  # fmt: skip
def test_a_value_is_explained_in_a_sentence_with_its_unit(code, value, median, text):
    assert explain_value(code, value, median) == text


def test_a_missing_or_zero_median_adds_no_comparison():
    assert "median" not in explain_value("water_intensity", 498, float("nan"))
    assert "median" not in explain_value("water_intensity", 498, 0)


def test_every_metric_has_a_plain_description(fixture_world):
    for m in metric_catalog(fixture_world.ind):
        notes = METRIC_NOTES[m["code"]]
        assert set(notes) == {"means", "how", "reading", "caution"}, m["code"]
        assert all(len(v) > 15 for v in notes.values()), m["code"]


def test_the_catalog_lists_five_derived_metrics_and_nine_reported_figures_with_units(fixture_world):
    catalog = metric_catalog(fixture_world.ind)
    assert [m["kind"] for m in catalog].count("derived") == 5
    assert [m["kind"] for m in catalog].count("reported") == 9
    assert all("INR" not in m["unit"] for m in catalog)
    water = next(m for m in catalog if m["code"] == "water_intensity")
    assert (water["unit"], water["better"]) == (f"kL per {RUPEE} crore", "lower")


def test_the_directory_names_every_company_and_what_its_latest_filing_states(fixture_world):
    with session_scope(fixture_world.engine) as s:
        directory = company_directory(s).set_index("code")
    assert list(directory.index) == [*NAMES, "XBB-01", "XBB-02"]
    first = directory.loc["XAA-01"]
    assert (first["name"], first["sector"], first["symbol"]) == (
        "XAA-01 Ltd",
        "Test Alpha",
        "XAA-01",
    )
    assert (first["years loaded"], first["boundary"], first["assurance"]) == (
        FY,
        "standalone",
        "assured",
    )
    nothing = directory.loc["XAA-02"]
    assert (nothing["years loaded"], nothing["boundary"], nothing["assurance"]) == (
        "none",
        "not stated",
        "not stated",
    )


def test_each_known_sector_is_described_and_an_unknown_one_still_gets_a_description():
    assert set(SECTOR_NOTES) == {"Cement", "Iron & Steel", "IT Services", "FMCG"}
    assert all(set(n) == {"what", "footprint", "compare"} for n in SECTOR_NOTES.values())
    assert sector_note("Cement") is SECTOR_NOTES["Cement"]
    assert sector_note("Shipping") is SECTOR_FALLBACK


# ---- query ----------------------------------------------------------------------------------------
def test_a_derived_query_returns_the_values_asked_for_with_their_units(fixture_world):
    with session_scope(fixture_world.engine) as s:
        data = query_data(
            s, ["emissions_intensity"], ["XAA-03", "XAA-01"], [FY, PRIOR], fixture_world.ind
        )
    assert list(zip(data["code"], data["fy"], data["value"], strict=True)) == [
        ("XAA-01", PRIOR, 10.0),
        ("XAA-01", FY, 10.0),
        ("XAA-03", PRIOR, 27.0),
        ("XAA-03", FY, 30.0),
    ]
    assert set(data["unit"]) == {f"tCO2e per {RUPEE} crore"} and set(data["kind"]) == {"derived"}
    assert set(data["data check"]) == {""}


def test_a_reported_query_reads_the_filing_and_marks_failed_figures(fixture_world):
    ind = fixture_world.ind
    with session_scope(fixture_world.engine) as s:
        raw = query_data(s, ["scope1_emissions"], ["XAA-01"], [FY], ind)
        waste = query_data(s, ["waste_recovery_rate"], ["XAA-05", "XAA-04"], [FY], ind)
        none = query_data(s, ["scope1_emissions"], ["XAA-01"], ["FY1999-00"], ind)
    assert list(raw["value"]) == [1.0] and list(raw["unit"]) == ["tCO2e"]
    assert list(raw["kind"]) == ["reported"]
    by_code = waste.set_index("code")
    assert by_code.loc["XAA-04", "data check"] == ""
    assert by_code.loc["XAA-05", "value"] == 103.0
    assert by_code.loc["XAA-05", "data check"] == "recovered_le_generated"
    assert none.empty and list(none.columns)[:3] == ["code", "sector", "fy"]


@pytest.mark.parametrize(
    ("shape", "kind"),
    [
        ((1, 5, 1), "bar"), ((1, 5, 3), "line"), ((1, 1, 3), "line"),
        ((2, 5, 1), "scatter"), ((2, 2, 1), "bar_panels"), ((3, 4, 1), "bar_panels"),
        ((2, 4, 3), "line_panels"), ((3, 1, 1), "table"), ((1, 1, 1), "table"), ((0, 3, 1), "table"),
    ],
)  # fmt: skip
def test_the_chart_follows_the_shape_of_the_question(shape, kind):
    chosen, reason = choose_chart(*shape)
    assert chosen == kind
    assert reason


def test_the_reason_for_a_chart_restates_the_shape_of_the_question():
    assert choose_chart(1, 5, 1)[1] == (
        "1 metric, 5 companies, 1 year: one value per company, so a bar chart ranks them."
    )
    assert choose_chart(3, 1, 2)[1].startswith("3 metrics, 1 company, 2 years")


# ---- compare ------------------------------------------------------------------------------------
def test_the_comparison_says_who_is_best_and_by_how_much(fixture_world):
    codes = ["XAA-01", "XAA-03", "XAA-04"]
    with session_scope(fixture_world.engine) as s:
        table = compare_table(s, codes, FY, fixture_world.ind).set_index("metric")
    assert table.loc["Emissions intensity (Scope 1+2)", "best"] == "XAA-01"  # lower is better
    assert table.loc["Renewable energy share", "best"] == "XAA-04"  # higher is better
    assert table.loc["Waste recovery rate", "best"] == "XAA-04"
    assert comparison_sentences(table.reset_index(), codes, NAMES) == [
        f"Emissions intensity (Scope 1+2): Alpha One is best at 10.0 tCO2e per {RUPEE} crore; "
        "Alpha Three 30.0 (3 times as high); Alpha Four 40.0 (4 times as high).",
        "Renewable energy share: Alpha Four is best at 50.3 %; Alpha One 50.0 (1% lower); "
        "Alpha Three 50.2 (the same).",
        "Waste recovery rate: Alpha Four is best at 98.0 %; Alpha One 95.0 (3% lower); "
        "Alpha Three 97.0 (1% lower).",
    ]


def test_a_figure_that_failed_a_check_is_named_but_never_ranked(fixture_world):
    codes = ["XAA-04", "XAA-05"]
    with session_scope(fixture_world.engine) as s:
        table = compare_table(s, codes, FY, fixture_world.ind)
    lines = comparison_sentences(table, codes, NAMES)
    assert (
        "Waste recovery rate: Alpha Four is best at 98.0 %. Not ranked because the figure fails a "
        "data-quality check: Alpha Five."
    ) in lines
    assert any(
        line.startswith("Emissions intensity (Scope 1+2): Alpha Four is best")
        and "Alpha Five 50.0 (25% higher)" in line
        for line in lines
    )


@pytest.mark.parametrize(
    ("value", "reference", "text"),
    [
        (30, 10, "3 times as high"), (25, 10, "150% higher"), (15, 10, "50% higher"),
        (5, 10, "50% lower"), (10, 10, "the same"), (10.04, 10, "the same"), (620, 1, "620 times as high"),
    ],
)  # fmt: skip
def test_a_gap_is_put_in_words_that_stay_readable_for_large_ratios(value, reference, text):
    assert _gap_text(value, reference) == text


# ---- describe a query result --------------------------------------------------------------------
def test_a_query_result_is_described_with_its_extremes_and_its_movers(fixture_world):
    with session_scope(fixture_world.engine) as s:
        data = query_data(s, ["emissions_intensity"], list(NAMES), [PRIOR, FY], fixture_world.ind)
    label = "Emissions intensity (Scope 1+2)"
    assert describe_query(data, NAMES, {label: "lower"}) == [
        f"{label} (lower is better), {FY}: lowest is Alpha One at 10.0 tCO2e per {RUPEE} crore, "
        f"highest is Alpha Five at 50.0 tCO2e per {RUPEE} crore (Alpha Five is 5 times the lowest).",
        f"{label}, {PRIOR} to {FY}: largest rise Alpha Five (+25%); largest fall Alpha Two (-20%).",
    ]


def test_one_company_in_one_year_is_described_as_a_single_figure(fixture_world):
    with session_scope(fixture_world.engine) as s:
        data = query_data(s, ["emissions_intensity"], ["XAA-01"], [FY], fixture_world.ind)
    assert describe_query(data, NAMES, {"Emissions intensity (Scope 1+2)": "lower"}) == [
        "Emissions intensity (Scope 1+2) (lower is better): Alpha One had 10.0 tCO2e per "
        f"{RUPEE} crore in {FY}."
    ]


# ---- compliance ----------------------------------------------------------------------------------
def _by_key(checks):
    return {c["key"]: c for c in checks}


def test_a_filing_with_one_core_figure_is_reported_as_partly_disclosed(fixture_world):
    with session_scope(fixture_world.engine) as s:
        checks = _by_key(compliance_checks(s, "XAA-01", FY, fixture_world.ind))
    assert [checks[k]["status"] for k in CHECK_ORDER] == [
        "pass", "attention", "pass", "pass", "pass", "info", "info", "info",
    ]  # fmt: skip
    assert checks["core"]["found"] == (
        "1 of 7 present. Missing: Scope 2 emissions, Water consumption, Total energy consumption, "
        "Renewable energy consumption, Waste generated, Waste recovered."
    )
    assert checks["boundary"]["found"] == "Stated: standalone."
    assert checks["assurance"]["found"] == "The filing states that its figures are assured."
    assert checks["checked"]["found"] == "1 of 2 values checked by a person."
    assert checks["years"]["found"] == f"1 year(s) loaded: {FY}."


def test_a_restated_comparative_with_an_error_flag_fails_where_it_should(fixture_world):
    with session_scope(fixture_world.engine) as s:
        checks = compliance_checks(s, "XAA-05", FY, fixture_world.ind)
    by_key = _by_key(checks)
    assert by_key["filing"]["status"] == "attention"
    assert "prior-year column of a later filing" in by_key["filing"]["found"]
    assert by_key["core"]["status"] == "fail" and by_key["core"]["found"].startswith(
        "0 of 7 present"
    )
    assert by_key["boundary"]["status"] == "attention"
    assert by_key["assurance"]["status"] == "attention"
    assert (
        "A prior-year column does not carry the assurance statement."
        in by_key["assurance"]["found"]
    )
    assert by_key["consistency"]["status"] == "fail"
    assert by_key["consistency"]["found"] == (
        "1 error flag(s): recovered_le_generated (waste recovered exceeds waste generated)."
    )
    assert compliance_summary(checks) == {"passed": 0, "attention": 3, "failed": 2, "of": 5}


def test_a_company_with_no_filing_for_the_year_can_only_fail_that_one_check(fixture_world):
    with session_scope(fixture_world.engine) as s:
        checks = compliance_checks(s, "XAA-02", FY, fixture_world.ind)
    assert [(c["key"], c["status"]) for c in checks] == [("filing", "fail"), ("years", "info")]
    assert checks[1]["found"] == "0 year(s) loaded: none."
    assert compliance_summary(checks) == {"passed": 0, "attention": 0, "failed": 1, "of": 1}


def test_the_matrix_grades_every_company_and_marks_unassessable_checks_n_a(fixture_world):
    with session_scope(fixture_world.engine) as s:
        matrix = compliance_matrix(s, FY, fixture_world.ind).set_index("code")
    assert list(matrix.index) == [*NAMES, "XBB-01", "XBB-02"]
    clean = matrix.loc["XAA-01"]
    assert [clean[c] for c in ("Own filing", "Core figures", "Boundary", "Assurance", "Consistency")] == [
        "pass", "attention", "pass", "pass", "pass",
    ]  # fmt: skip
    assert (clean["passed"], clean["of"]) == (4, 5)
    missing = matrix.loc["XAA-02"]
    assert (missing["Own filing"], missing["Core figures"], missing["Consistency"]) == (
        "fail",
        "n/a",
        "n/a",
    )


def test_the_glide_path_and_the_checklist_are_complete_and_consistent():
    assert GLIDE_PATH == (
        ("FY2023-24", "top 150"),
        ("FY2024-25", "top 250"),
        ("FY2025-26", "top 500"),
        ("FY2026-27", "top 1000"),
    )
    assert set(CHECK_ORDER) == set(CHECK_TITLES) == set(CHECK_WHY)
    assert "does not compute each company's rank" in CHECK_WHY["assurance"]


def test_every_page_has_a_caption_and_a_distinct_address():
    assert set(vocab.DASHBOARD_VIEWS) <= set(vocab.VIEW_NOTES)
    slugs = [vocab.slug(v) for v in vocab.DASHBOARD_VIEWS]
    assert len(set(slugs)) == len(slugs)
    assert vocab.slug("Compare companies") == "compare-companies"
    assert vocab.slug("Query and chart") == "query-and-chart"
    assert list(vocab.EIS_VIEWS) == EVIDENCE


# ---- the pages -------------------------------------------------------------------------------------
def _run(monkeypatch, repo_root, config="config/study_dry.yaml") -> AppTest:
    monkeypatch.setattr(sys, "argv", ["app.py", "--config", config])
    return AppTest.from_file(str(repo_root / "dashboard" / "app.py"), default_timeout=120).run()


def go(at: AppTest, page: str) -> AppTest:
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _spec(at: AppTest, index: int = 0) -> dict:
    return json.loads(at.get("plotly_chart")[index].proto.spec)


def test_every_page_opens_with_what_it_shows_and_what_is_compared(
    fixture_world, repo_root, monkeypatch
):
    at = _run(monkeypatch, repo_root)
    assert at.sidebar.radio[0].options[: len(EVIDENCE)] == EVIDENCE
    for page in EVIDENCE[1:]:
        go(at, page)
        first = [m.value for m in at.markdown][:2]
        assert first[0].startswith("**What this page shows.**"), page
        assert first[1].startswith("**What is being compared.**"), page


def test_names_show_by_default_and_codes_on_request(fixture_world, repo_root, monkeypatch):
    at = go(_run(monkeypatch, repo_root), "Companies")
    assert at.selectbox(key="company_pick").options[:2] == ["XAA-01 Ltd", "XAA-02 Ltd"]
    at.sidebar.toggle[0].set_value(False).run()
    assert at.selectbox(key="company_pick").options[:2] == ["XAA-01", "XAA-02"]


def test_the_home_page_leads_to_every_kind_of_information(fixture_world, repo_root, monkeypatch):
    at = _run(monkeypatch, repo_root)
    assert at.sidebar.radio[0].value == "Home"
    for key in ("companies", "sectors", "metrics-guide", "compare-companies", "query-and-chart",
                "kpi-scorecard", "compliance-check", "sources-and-filings"):  # fmt: skip
        assert at.button(key=f"home_{key}")
    at.button(key="home_query-and-chart").click().run()
    assert at.sidebar.radio[0].value == "Query and chart"
    assert not at.exception, [e.value for e in at.exception]


def test_a_page_address_opens_that_page(fixture_world, repo_root, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app.py", "--config", "config/study_dry.yaml"])
    at = AppTest.from_file(str(repo_root / "dashboard" / "app.py"), default_timeout=120)
    at.query_params["page"] = "compare-companies"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.sidebar.radio[0].value == "Compare companies"
    assert at.query_params["page"] == ["compare-companies"]


def test_the_sector_page_describes_the_sector_and_ranks_its_companies(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Sectors")
    assert at.radio(key="sector_pick").options == ["Test Alpha", "Test Beta"]
    at.selectbox(key="sector_kpi").set_value("Emissions intensity (Scope 1+2)").run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 3
    assert any("Compare companies with others in the same sector" in c.value for c in at.caption)
    assert any("Emissions intensity (Scope 1+2) (tCO2e per" in i.value for i in at.info)
    bars = _spec(at)["data"]
    assert bars[0]["type"] == "bar" and bars[0]["orientation"] == "h"
    table = next(d.value for d in at.dataframe if "Rank in sector" in d.value.columns)
    assert f"Value (tCO2e per {RUPEE} crore)" in table.columns
    assert list(table["Company"]) == [f"XAA-0{i} Ltd" for i in (1, 2, 3, 4, 5)]
    assert list(table["Rank in sector"]) == [f"{i} of 5" for i in (1, 2, 3, 4, 5)]


def test_the_metrics_guide_explains_498_and_any_other_value(fixture_world, repo_root, monkeypatch):
    at = go(_run(monkeypatch, repo_root), "Metrics guide")
    assert at.selectbox(key="explain_metric").value == f"Water intensity (kL per {RUPEE} crore)"
    assert any(
        "consumed 498 kilolitres of water, which is 498,000 litres" in s.value for s in at.success
    )
    at.number_input(key="explain_value").set_value(100.0).run()
    assert any(
        "consumed 100 kilolitres of water, which is 100,000 litres" in s.value for s in at.success
    )
    labels = [e.label for e in at.expander]
    assert len(labels) == 5 and labels[0].startswith("Energy intensity (GJ per")


def test_comparing_companies_shows_units_words_and_a_cross_sector_warning(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Compare companies")
    assert at.multiselect(key="compare_codes").value == ["XAA-01", "XAA-02"]
    assert not at.warning
    at.multiselect(key="compare_codes").set_value(["XAA-01", "XAA-03", "XAA-04"]).run()
    assert not at.exception, [e.value for e in at.exception]
    table = next(d.value for d in at.dataframe if "Best" in d.value.columns)
    emissions = table[table["Metric"] == "Emissions intensity (Scope 1+2)"].iloc[0]
    assert (emissions["Unit"], emissions["Best"], emissions["XAA-01"]) == (
        f"tCO2e per {RUPEE} crore",
        "XAA-01 Ltd",
        "10.0",
    )
    assert any(
        f"XAA-01 Ltd is best at 10.0 tCO2e per {RUPEE} crore" in m.value for m in at.markdown
    )
    at.multiselect(key="compare_codes").set_value(["XAA-01", "XBB-01"]).run()
    assert any("different sectors" in w.value for w in at.warning)
    at.multiselect(key="compare_codes").set_value(["XAA-01"]).run()
    assert any("at least two companies" in i.value for i in at.info)


def test_a_query_chooses_its_own_chart_and_says_why(fixture_world, repo_root, monkeypatch):
    at = go(_run(monkeypatch, repo_root), "Query and chart")
    metric = f"Emissions intensity (Scope 1+2) (tCO2e per {RUPEE} crore)"
    at.multiselect(key="query_metrics_d").set_value([metric]).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Your question." in m.value and "5 companies" in m.value for m in at.markdown)
    note = next(c.value for c in at.caption if c.value.startswith("Chart chosen"))
    assert "one value per company, so a bar chart ranks them" in note
    assert _spec(at)["data"][0]["type"] == "bar"
    at.multiselect(key="query_years").set_value([PRIOR, FY]).run()
    assert any(
        "one metric over several years, so a line shows the trend" in c.value for c in at.caption
    )
    assert _spec(at)["data"][0]["mode"].startswith("lines")
    at.multiselect(key="query_metrics_d").set_value([metric, "Renewable energy share (%)"]).run()
    at.multiselect(key="query_years").set_value([FY]).run()
    assert any(
        "two metrics for several companies, so a scatter plot" in c.value for c in at.caption
    )


def test_a_chosen_chart_overrides_the_automatic_one_when_it_makes_sense(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Query and chart")
    at.multiselect(key="query_metrics_d").set_value(
        [f"Emissions intensity (Scope 1+2) (tCO2e per {RUPEE} crore)"]
    ).run()
    at.selectbox(key="query_chart").set_value("Table only").run()
    assert not at.get("plotly_chart")
    at.selectbox(key="query_chart").set_value("Line").run()
    assert any(
        "a line needs more than one year, so a bar chart is shown instead" in c.value
        for c in at.caption
    )
    assert at.get("plotly_chart")


def test_reported_figures_carry_a_warning_that_totals_depend_on_size(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Query and chart")
    at.radio(key="query_kind").set_value(at.radio(key="query_kind").options[1]).run()
    assert not at.exception, [e.value for e in at.exception]
    options = at.multiselect(key="query_metrics_r").options
    assert (
        "Scope 1 emissions (tCO2e)" in options
        and f"Revenue from operations ({RUPEE} crore)" in options
    )
    at.multiselect(key="query_metrics_r").set_value(["Scope 1 emissions (tCO2e)"]).run()
    assert any("raw totals" in w.value for w in at.warning)


def test_the_compliance_page_grades_every_company_and_is_clear_it_is_not_a_legal_finding(
    fixture_world, repo_root, monkeypatch
):
    at = go(_run(monkeypatch, repo_root), "Compliance check")
    assert any("not a legal finding of compliance" in w.value for w in at.warning)
    matrix = next(d.value for d in at.dataframe if "Checks passed" in d.value.columns)
    assert len(matrix) == 7
    row = matrix[matrix["Company"] == "XAA-01 Ltd"].iloc[0]
    assert (row["Own filing"], row["Core figures"], row["Checks passed"]) == (
        "✔ Pass", "▲ Attention", "4 of 5",
    )  # fmt: skip
    none = matrix[matrix["Company"] == "XAA-02 Ltd"].iloc[0]
    assert (none["Own filing"], none["Core figures"]) == ("✖ Fail", "– n/a")
    at.selectbox(key="compliance_company").set_value("XAA-05").run()
    assert not at.exception, [e.value for e in at.exception]
    assert [m.value for m in at.metric][:3] == ["0 of 5", "3", "2"]


# ---- a breach of under 1% is rounding for ranking, but never for the compliance check ------------
def test_a_tiny_breach_is_ranked_a_large_one_is_not_and_compliance_stays_strict(fixture_world):
    from decimal import Decimal

    from sqlalchemy import select

    from gauge.db.models import Company, IndicatorValue, KpiValue, QualityFlag, Report
    from gauge.viewdata import sector_overview

    with session_scope(fixture_world.engine) as s:
        company = {c.code: c for c in s.scalars(select(Company))}
        for code, value in zip(NAMES, (100, 200, 300, 400, 500), strict=True):
            s.add(KpiValue(company_id=company[code].id, fy=FY, kpi="water_intensity",
                           value=Decimal(value), engine_version="t"))  # fmt: skip
        # XAA-03 consumed 10% more water than it withdrew; XAA-04 0.05% more
        for code, consumed in (("XAA-03", "1100"), ("XAA-04", "1000.5")):
            report = Report(company_id=company[code].id, fy=FY, entry_method="xbrl")
            s.add(report)
            s.flush()
            s.add(IndicatorValue(report_id=report.id, indicator="water_consumption",
                                 value=Decimal(consumed), unit="kL"))  # fmt: skip
            s.add(IndicatorValue(report_id=report.id, indicator="water_withdrawal",
                                 value=Decimal(1000), unit="kL"))  # fmt: skip
            s.add(QualityFlag(company_id=company[code].id, fy=FY, rule="consumption_le_withdrawal",
                              severity="error", indicator="water_consumption",
                              message=f"{code}: consumption exceeds withdrawal"))  # fmt: skip
    with session_scope(fixture_world.engine) as s:
        water = sector_overview(s, FY, "water_intensity", fixture_world.ind).set_index("code")
        strict = _by_key(compliance_checks(s, "XAA-04", FY, fixture_world.ind))
    assert water.loc["XAA-03", "band"] == "data check"
    assert water.loc["XAA-03", "data check"] == "consumption_le_withdrawal"
    assert water.loc["XAA-04", "data check"] == ""  # 0.05% over is rounding: ranked
    assert [water.loc[c, "rank in sector"] for c in ("XAA-01", "XAA-02", "XAA-04", "XAA-05")] == [
        1,
        2,
        3,
        4,
    ]
    assert set(water["companies compared"][:5]) == {4}
    assert strict["consistency"]["status"] == "fail"  # the compliance check reports it regardless
