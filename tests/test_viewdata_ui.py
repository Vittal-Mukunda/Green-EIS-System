"""Presentation helpers for the redesigned dashboard. Expected values are worked out by hand; none is
recomputed with the code under test."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from fixture_alpha import FY, PRIOR
from gauge.db.session import session_scope
from gauge.viewdata_ui import (
    figures_failing_checks,
    filing_facts,
    fmt_figure,
    fmt_value,
    formula_latex,
    largest_movements,
    pct_vs_median,
    register_rows,
    sector_summary,
    source_trace,
    unit_reconciliation,
)

RUPEE = "₹"


def _matrix(rows):
    """A kpi_matrix-shaped frame: (sector, kpi, value, band, data check, change %, movement)."""
    return pd.DataFrame(
        [
            {
                "code": f"C{i}",
                "sector": sector,
                "kpi": kpi,
                "label": "Water intensity",
                "unit": f"kL per {RUPEE} crore",
                "better": "lower",
                "value": value,
                "band": band,
                "data check": check,
                "rank in sector": 1,
                "companies compared": 5,
                "previous year": 100.0,
                "change %": change,
                "movement": movement,
            }
            for i, (sector, kpi, value, band, check, change, movement) in enumerate(rows)
        ]
    )


# ---- sector summaries ---------------------------------------------------------------------------
def test_a_sector_sample_has_a_median_and_quartiles_from_the_figures_that_pass_the_checks():
    nan = float("nan")
    rows = [("Cement", "water", v, "middle third", "", nan, "n/a") for v in (10, 20, 30, 40, 50)]
    rows.append(("Cement", "water", 999, "data check", "recovered_le_generated", nan, "n/a"))
    summary = sector_summary(_matrix(rows)).iloc[0]
    # sorted 10 20 30 40 50: median is x[2]; P25 sits at position 1 and P75 at position 3 (type 7)
    assert (summary["median"], summary["p25"], summary["p75"]) == (30.0, 20.0, 40.0)
    assert (summary["companies"], summary["compared"], summary["data checks"]) == (6, 5, 1)


def test_quartiles_interpolate_between_order_statistics():
    nan = float("nan")
    rows = [("Steel", "water", v, "middle third", "", nan, "n/a") for v in (1, 2, 3, 10)]
    summary = sector_summary(_matrix(rows)).iloc[0]
    # n=4: median at position 1.5 -> 2.5; P25 at 0.75 -> 1 + 0.75*1 = 1.75; P75 at 2.25 -> 3 + 0.25*7 = 4.75
    assert (summary["median"], summary["p25"], summary["p75"]) == (2.5, 1.75, 4.75)


def test_two_companies_are_too_few_for_a_median_or_quartiles():
    rows = [("IT", "water", v, "n/a", "", float("nan"), "n/a") for v in (5, 7)]
    summary = sector_summary(_matrix(rows)).iloc[0]
    assert (
        math.isnan(summary["median"]) and math.isnan(summary["p25"]) and math.isnan(summary["p75"])
    )
    assert summary["compared"] == 2


def test_the_summary_median_agrees_with_the_median_the_matrix_already_shows(fixture_world):
    from gauge.viewdata import kpi_matrix

    with session_scope(fixture_world.engine) as s:
        matrix = kpi_matrix(s, FY, fixture_world.ind)
    summary = sector_summary(matrix).set_index(["sector", "kpi"])
    shown = matrix.drop_duplicates(["sector", "kpi"]).set_index(["sector", "kpi"])["sector median"]
    for key, median in shown.items():
        if pd.isna(median):
            assert math.isnan(summary.loc[key, "median"])
        else:
            assert summary.loc[key, "median"] == pytest.approx(median)


def test_figures_that_fail_a_check_are_listed_with_the_reason_in_words():
    nan = float("nan")
    rows = [
        ("Cement", "waste", 103.5, "data check", "recovered_le_generated", nan, "n/a"),
        ("Cement", "waste", 90.0, "better third", "", nan, "n/a"),
    ]
    failing = figures_failing_checks(_matrix(rows))
    assert list(failing["value"]) == [103.5]
    assert list(failing["reason"]) == ["waste recovered exceeds waste generated"]


# ---- movements and distances --------------------------------------------------------------------
def test_the_largest_moves_come_first_in_either_direction_and_small_ones_are_left_out():
    rows = [
        ("A", "k", 1, "better third", "", -12.0, "better"),
        ("A", "k", 1, "better third", "", 40.0, "worse"),
        ("A", "k", 1, "better third", "", 9.9, "worse"),
        ("A", "k", 1, "data check", "x", float("nan"), "n/a"),
        ("A", "k", 1, "better third", "", -75.0, "better"),
    ]
    moves = largest_movements(_matrix(rows), top=2)
    assert list(moves["change %"]) == [-75.0, 40.0]


@pytest.mark.parametrize(
    ("value", "median", "expected"),
    [(120, 100, 20.0), (80, 100, -20.0), (50, 200, -75.0), (7, -2, 450.0)],
)
def test_distance_from_the_sample_median_is_a_percentage_of_the_median(value, median, expected):
    assert pct_vs_median(value, median) == pytest.approx(expected)


def test_no_distance_is_given_without_a_usable_median():
    assert math.isnan(pct_vs_median(5, 0)) and math.isnan(pct_vs_median(5, float("nan")))


@pytest.mark.parametrize(
    ("value", "unit", "text"),
    [
        (103.5, "%", "103.5 %"),
        (99.84, "%", "99.8 %"),
        (4272.04, f"GJ per {RUPEE} crore", f"4,272 GJ per {RUPEE} crore"),
        (8.42, f"tCO2e per {RUPEE} crore", f"8.42 tCO2e per {RUPEE} crore"),
        (float("nan"), "%", "not available"),
    ],
)
def test_a_figure_is_written_with_its_unit(value, unit, text):
    assert fmt_value(value, unit) == text


def test_a_figure_without_its_unit_keeps_the_same_precision():
    assert fmt_figure(103.5, "%") == "103.5"
    assert fmt_figure(4272.04, "GJ") == "4,272"


# ---- formulas -----------------------------------------------------------------------------------
LABELS = {
    "scope1_emissions": "Scope 1 emissions",
    "scope2_emissions": "Scope 2 emissions",
    "revenue_from_operations": "Revenue from operations",
    "energy_total": "Total energy",
    "energy_renewable": "Renewable energy",
}


@pytest.mark.parametrize(
    ("formula", "latex"),
    [
        (
            "energy_total / revenue_from_operations",
            r"\frac{\text{Total energy}}{\text{Revenue from operations}}",
        ),
        (
            "(scope1_emissions + scope2_emissions) / revenue_from_operations",
            r"\frac{\text{Scope 1 emissions} + \text{Scope 2 emissions}}{\text{Revenue from operations}}",
        ),
        (
            "100 * energy_renewable / energy_total",
            r"\frac{100 \times \text{Renewable energy}}{\text{Total energy}}",
        ),
        ("energy_total", r"\text{Total energy}"),
    ],
)
def test_a_configured_formula_becomes_latex_with_the_indicator_labels(formula, latex):
    assert formula_latex(formula, LABELS) == latex


def test_every_configured_kpi_formula_has_a_latex_form_naming_only_known_indicators(fixture_world):
    labels = {i.code: i.label for i in fixture_world.ind.indicators}
    for spec in fixture_world.ind.kpis:
        latex = formula_latex(spec.formula, labels)
        assert latex.startswith(r"\frac{") and "_" not in latex.replace(r"\_", ""), spec.code


# ---- the register -------------------------------------------------------------------------------
def test_every_flag_becomes_a_register_row_with_the_figure_and_a_status(fixture_world):
    with session_scope(fixture_world.engine) as s:
        rows = register_rows(s, fixture_world.ind).set_index(["code", "fy"])
    assert len(rows) == 3
    old = rows.loc[("XAA-02", PRIOR)]
    assert (old["metric"], old["reported"]) == ("Waste recovery rate", "90.0 %")
    assert (old["status"], old["tone"], old["reviewer"]) == ("Needs verification", "warn", None)
    now = rows.loc[("XAA-05", FY)]
    assert (
        now["reported"] == "103.0 %" and now["issue"] == "waste recovered exceeds waste generated"
    )
    note = rows.loc[("XAA-03", FY)]
    assert (note["severity"], note["status"], note["reported"]) == (
        "warning",
        "Noted, no action needed",
        "not available",
    )


def test_a_flag_never_calls_a_company_anything(fixture_world):
    with session_scope(fixture_world.engine) as s:
        statuses = set(register_rows(s, fixture_world.ind)["status"])
    assert statuses <= {
        "Needs verification",
        "Reviewed: matches filing",
        "Reviewed: error recorded",
        "Review",
        "Noted, no action needed",
        "Data unavailable",
    }


# ---- the chain back to a filing -----------------------------------------------------------------
def test_a_kpi_traces_to_its_inputs_validation_filing_and_fingerprint(fixture_world):
    with session_scope(fixture_world.engine) as s:
        trace = source_trace(s, "XAA-01", FY, "emissions_intensity", fixture_world.ind)
    assert trace["kpi"]["value"] == 10.0 and trace["kpi"]["better"] == "lower"
    assert [i["code"] for i in trace["inputs"]] == [
        "scope1_emissions",
        "scope2_emissions",
        "revenue_from_operations",
    ]
    assert [i["present"] for i in trace["inputs"]] == [True, False, True]
    assert trace["inputs"][0]["value"] == 1.0 and trace["inputs"][0]["verified"] is True
    assert (trace["checked"], trace["of"], trace["rules"], trace["converted"]) == (1, 2, [], 0)
    assert trace["report"]["sha256"] == "cd" * 32
    assert trace["report"]["retrieved_on"] == "2026-10-02"
    assert trace["formula_latex"].startswith(r"\frac{\text{Scope 1 emissions}")


def test_a_figure_that_fails_a_check_says_which_rule_in_its_trace(fixture_world):
    with session_scope(fixture_world.engine) as s:
        trace = source_trace(s, "XAA-05", FY, "waste_recovery_rate", fixture_world.ind)
    assert trace["rules"] == ["recovered_le_generated"]
    assert trace["kpi"]["value"] == 103.0


def test_a_company_year_without_a_filing_has_no_source(fixture_world):
    with session_scope(fixture_world.engine) as s:
        assert filing_facts(s, "XAA-02", FY) is None
        trace = source_trace(s, "XAA-02", FY, "emissions_intensity", fixture_world.ind)
    assert trace["report"] is None and trace["of"] == 0


def test_unit_conversions_are_counted_from_the_filing_units():
    lineage = pd.DataFrame(
        {
            "unit": ["GJ", f"{RUPEE} crore", "tCO2e"],
            "as-filed unit": ["GJ", "INR", None],
            "as filed": [5.0, 2.0e7, None],
        }
    )
    assert unit_reconciliation(lineage) == {"values": 3, "converted": 1}
    assert unit_reconciliation(lineage.iloc[0:0]) == {"values": 0, "converted": 0}
