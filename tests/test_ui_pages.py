"""The pages, run through Streamlit's AppTest. The example factory's numbers are the hand-worked ones
(see test_analysis_modules.py): 38.97 tCO2e, trust index 0.72, plus or minus 12.9%."""

from __future__ import annotations

import pathlib
import sys
from decimal import Decimal as D

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

DASHBOARD = pathlib.Path(__file__).resolve().parents[1] / "dashboard"
sys.path.insert(0, str(DASHBOARD))

import pages_study  # noqa: E402
import state  # noqa: E402
import vocab  # noqa: E402

from greeneis import whatif  # noqa: E402
from greeneis.engine import Activity  # noqa: E402
from greeneis.study import synthetic  # noqa: E402
from greeneis.study.run import run_study, write  # noqa: E402


@pytest.fixture(autouse=True)
def no_outputs(tmp_path, monkeypatch):
    """Pages read study results from OUTPUTS; point it at an empty folder unless a test fills it."""
    monkeypatch.setattr(pages_study, "OUTPUTS", tmp_path / "outputs")


def run(page, before=None) -> AppTest:
    at = AppTest.from_file(str(DASHBOARD / "app.py"), default_timeout=90)
    at.session_state["view"] = page
    if before:
        before(at)
    at.run()
    return at


def html(at: AppTest) -> str:
    return " ".join(h.proto.body for h in at.get("html"))


def text(at: AppTest) -> str:
    return (
        html(at)
        + " "
        + " ".join(m.value for m in at.markdown)
        + " "
        + " ".join(c.value for c in at.caption)
    )


def frame(rows):
    return pd.DataFrame(rows, columns=state.COLUMNS)


def with_frames(**periods):
    def setup(at):
        frames = {k.replace("_", " "): v for k, v in periods.items()}
        at.session_state["bases"] = {k: v.copy() for k, v in frames.items()}
        at.session_state["periods"] = {k: v.copy() for k, v in frames.items()}
        at.session_state["period"] = next(iter(frames))
        at.session_state["unit_name"] = "Test unit"

    return setup


# ---- every page renders -------------------------------------------------------------------------
@pytest.mark.parametrize("page", vocab.PAGES)
def test_every_page_renders_without_an_exception(page):
    at = run(page)
    assert not at.exception, [e.value for e in at.exception]
    assert "GreenEIS" in html(at)


def test_the_example_is_labelled_on_every_unit_page():
    for page in vocab.UNIT_PAGES:
        at = run(page)
        assert "Illustrative factory" in html(at) and "Illustrative example" in html(at), page
        assert "not real data" in html(at), page


def test_a_page_address_opens_that_page():
    at = AppTest.from_file(str(DASHBOARD / "app.py"), default_timeout=90)
    at.query_params["page"] = "hotspots"
    at.run()
    assert at.session_state["view"] == "Hotspots"


# ---- the example's numbers ----------------------------------------------------------------------
def test_summary_shows_the_hand_calculated_figures():
    t = text(run("Summary"))
    assert "38.97 tCO2e" in t and "0.72" in t and "plus or minus 12.9%" in t
    assert "33.94 to 43.99" in t
    assert "Coal (boiler)" in t and "48.5% of emissions" in t
    assert "does not certify" in t.lower()


def test_summary_points_at_the_estimated_coal_as_the_place_to_improve_data():
    t = text(run("Summary"))
    assert "Improve this data first" in t and "89%" in t  # coal is 88.7% of the squared uncertainty
    assert "coal grade is unknown" in t.lower()


def test_hotspots_table_has_the_cost_link_and_the_vital_few():
    t = text(run("Hotspots"))
    assert "Vital few" in t
    assert "4,759" in t and "11,004" in t and "32,892" in t and "33,417" in t
    assert "Polluting but cheap" in t and "Costly but low in emissions" in t
    assert (
        "Boiler and thermic-fluid heater efficiency" in t
    )  # the boiler rule fired for Coal (boiler)


def test_what_if_reproduces_the_reference_scenarios():
    def setup(at):
        at.session_state["scenarios"] = [
            whatif.ActivityChange("Diesel (generator and vehicle)", D(15)),
            whatif.ActivityChange("Coal (boiler)", D(10)),
            whatif.ElectricityShift(D(20)),
        ]

    t = text(run("What-if", setup))
    assert "0.82" in t and "1.89" in t and "2.62" in t and "5.33" in t
    assert "27,000" in t and "9,000" in t and "28,800" in t and "64,800" in t
    assert "All scenarios together" in t


def test_what_if_reports_a_scenario_that_no_longer_fits_the_data():
    at = run(
        "What-if",
        lambda a: a.session_state.__setitem__("scenarios", [whatif.ActivityChange("Gone", D(10))]),
    )
    assert not at.exception and "A scenario cannot be applied" in html(at)


def test_report_carries_the_numbers_and_the_standing_statements():
    at = run("Report")
    t = text(at)
    assert "# Emissions summary" in t or "Emissions summary: Illustrative factory" in t
    assert "38.97 tCO2e" in t and "does not certify" in t and "indicative design values" in t


# ---- what goes wrong is said, not hidden --------------------------------------------------------
def test_a_row_that_cannot_be_calculated_is_left_out_and_named():
    rows = [
        [state.GRID_NAME, "Grid", 18000.0, "kWh", "Measured", None, ""],
        [
            "Liquefied petroleum gas (LPG)",
            "LPG",
            100.0,
            "L",
            "Estimated",
            None,
            "",
        ],  # no LPG density
    ]
    at = run("Summary", with_frames(June=frame(rows)))
    assert not at.exception
    t = text(at)
    assert "1 row(s) are left out" in t and "Row 2" in t and "cannot be entered in L" in t
    assert "13.09 tCO2e" in t  # only the grid row is counted


def test_a_blank_table_asks_for_data_instead_of_showing_zeros():
    for page in ("Summary", "Hotspots", "What-if", "Report"):
        at = run(page, with_frames(Blank=state.empty_frame()))
        assert not at.exception, page
        assert "No activities yet" in html(at), page


def test_missing_data_class_is_treated_as_default_and_says_so():
    rows = [["Coal (sub-bituminous, grade assumed)", "Coal", 1000.0, "kg", None, None, ""]]
    at = run("Summary", with_frames(June=frame(rows)))
    t = text(at)
    assert "treated as Default" in t and "0.30" in t  # one default line: trust index 0.3


def test_two_periods_can_be_shown_together_and_the_lines_are_merged():
    example = state.example_frame()
    at = run(
        "Summary",
        lambda a: (
            with_frames(May=example, June=example)(a),
            a.session_state.__setitem__("scope", "All periods entered"),
        ),
    )
    t = text(at)
    assert not at.exception and "77.93 tCO2e" in t  # 2 x 38.966
    assert "all periods entered" in t


# ---- study results ------------------------------------------------------------------------------
def test_study_page_without_a_result_says_how_to_make_one():
    t = html(run("Study results"))
    assert "No study result yet" in t


def test_study_page_marks_synthetic_results(tmp_path):
    result = run_study(synthetic.generate(300, 2), "synthetic", "invented", seed=2, n_boot=100)
    write(result, tmp_path / "outputs" / "study_test.json")
    at = run("Study results")
    t = text(at)
    assert not at.exception
    assert "Synthetic data." in t and "SYNTHETIC DATA" in t
    for h in ("H1", "H2", "H3", "H4", "H5"):
        assert h in t
    assert "uncalibrated placeholders" in t


# ---- the entry table -> activities --------------------------------------------------------------
def test_frame_to_activities_by_hand():
    rows = [
        [
            "Coal (sub-bituminous, grade assumed)",
            "Coal",
            10000.0,
            "kg",
            "Estimated",
            90000.0,
            "boiler",
        ],
        [None, None, None, None, None, None, None],  # a blank row is skipped silently
        ["Coal (sub-bituminous, grade assumed)", "Coal", 5.0, "t", "Measured", None, ""],
        [state.GRID_NAME, "", None, "kWh", "Measured", None, ""],  # no quantity
        [state.GRID_NAME, "", 100.0, None, "Measured", None, ""],  # no unit
        ["Peat", "x", 1.0, "kg", "Default", None, ""],  # unknown item
    ]
    acts, errors, warnings = state.frame_to_activities(frame(rows))
    assert [a.name for a in acts] == ["Coal", "Coal (2)"]
    assert (
        acts[0].quantity == D("10000.0")
        and acts[0].cost_inr == D("90000.0")
        and acts[0].equipment == "boiler"
    )
    assert errors == ["Row 4: enter a quantity.", "Row 5: choose a unit.", "Row 6: choose an item."]
    assert any("renamed 'Coal (2)'" in w for w in warnings)


def test_aggregate_merges_units_costs_and_takes_the_least_trusted_class():
    a = Activity("coal", D("10"), "t", "measured", D("1000"), "Coal", "boiler")
    b = Activity("coal", D("5000"), "kg", "estimated", D("500"), "Coal", "boiler")
    c = Activity("coal", D("1"), "t", "measured", None, "Coal", "boiler")  # a line with no cost
    d = Activity("diesel", D("100"), "L", "default", D("10"), "Diesel")
    merged = state.aggregate([a, b, d])
    assert len(merged) == 2
    coal = next(m for m in merged if m.item_id == "coal")
    assert coal.quantity == D("15000") and coal.unit == "kg" and coal.cost_inr == D("1500")
    assert coal.data_class == "estimated"  # the weakest of measured and estimated
    assert next(m for m in merged if m.item_id == "diesel").quantity == D("85.00")  # 100 L x 0.85
    assert (
        state.aggregate([a, c])[0].cost_inr is None
    )  # one missing cost makes the merged cost unknown
