"""KPI engine. Every expected value below was calculated by hand (the arithmetic is in the comments)
and is written into the test as a literal, not recomputed with the code under test."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from gauge.config import KpiSpec, load_indicators, load_study
from gauge.db.models import Company, IndicatorValue, KpiValue, QualityFlag, Report, Sector
from gauge.db.session import session_scope
from gauge.kpi.engine import (
    KPI_CHANGE_2Y,
    KPI_UNDEFINED,
    compute_kpis,
    compute_report_kpis,
    engine_version,
    quantize,
)
from gauge.kpi.formula import Formula, FormulaError, percent_change
from gauge.standardize.run import NotStandardizedError

D = Decimal


@pytest.fixture(scope="module")
def kpis() -> list[KpiSpec]:
    root = Path(__file__).resolve().parents[1]
    return load_indicators(load_study("config/study.yaml", root=root)).kpis


# Company X, FY2024-25 (hand-worked):
X = {
    "revenue_from_operations": D("2000"),  # INR crore
    "energy_total": D("500000"),  # GJ
    "energy_renewable": D("125000"),  # GJ
    "scope1_emissions": D("80000"),  # tCO2e
    "scope2_emissions": D("20000"),  # tCO2e
    "water_withdrawal": D("6000000"),  # kL
    "water_consumption": D("4000000"),  # kL
    "waste_generated": D("120"),  # t
    "waste_recovered": D("90"),  # t
}


def test_hand_calculated_kpis_for_company_x(kpis):
    result = compute_report_kpis(X, kpis).values
    # energy intensity   = 500,000 / 2,000                 = 250 GJ per crore
    assert result["energy_intensity"] == D("250")
    # emissions intensity = (80,000 + 20,000) / 2,000      = 50 tCO2e per crore
    assert result["emissions_intensity"] == D("50")
    # water intensity (on consumption, per the owner) = 4,000,000 / 2,000 = 2,000 kL per crore
    assert result["water_intensity"] == D("2000")
    # renewable share    = 100 * 125,000 / 500,000         = 25 %
    assert result["renewable_share"] == D("25")
    # waste recovery     = 100 * 90 / 120                  = 75 %
    assert result["waste_recovery_rate"] == D("75")


def test_water_intensity_uses_consumption_not_withdrawal(kpis):
    # withdrawal 6,000,000 / 2,000 would be 3,000; the KPI must be 2,000 (consumption)
    assert compute_report_kpis(X, kpis).values["water_intensity"] != D("3000")


def test_non_terminating_results_round_to_12_places(kpis):
    values = {
        **X,
        "revenue_from_operations": D("3"),
        "energy_total": D("1"),
        "energy_renewable": D("1"),
    }
    out = compute_report_kpis(values, kpis).values
    assert out["energy_intensity"] == D("0.333333333333")  # 1 / 3
    assert out["renewable_share"] == D("100")  # 100 * 1 / 1


def test_one_third_percent(kpis):
    values = {**X, "energy_total": D("3"), "energy_renewable": D("1")}
    assert compute_report_kpis(values, kpis).values["renewable_share"] == D("33.333333333333")


def test_rounding_is_half_even(kpis):
    # 1 / 8192 = 2^-13 = 0.0001220703125 exactly; at 12 places this is a tie (...312|5),
    # and half-even rounds to the even digit: 0.000122070312 (half-up would give ...313).
    values = {**X, "energy_total": D("1"), "revenue_from_operations": D("8192")}
    assert compute_report_kpis(values, kpis).values["energy_intensity"] == D("0.000122070312")


def test_no_float_contamination(kpis):
    out = compute_report_kpis(X, kpis).values
    assert all(isinstance(v, Decimal) for v in out.values())
    # 0.1 + 0.2 style trap: three intensities that are not representable in binary floating point
    values = {**X, "revenue_from_operations": D("10"), "energy_total": D("3")}
    assert compute_report_kpis(values, kpis).values["energy_intensity"] == D("0.3")


def test_missing_inputs_are_reported_not_guessed(kpis):
    values = {k: v for k, v in X.items() if k != "scope2_emissions"}
    out = compute_report_kpis(values, kpis)
    assert "emissions_intensity" not in out.values
    assert out.missing["emissions_intensity"] == ["scope2_emissions"]
    assert out.values["energy_intensity"] == D("250")  # unrelated KPIs still computed


def test_zero_denominators_are_undefined_not_infinite(kpis):
    out = compute_report_kpis({**X, "waste_generated": D("0"), "waste_recovered": D("0")}, kpis)
    assert "waste_recovery_rate" not in out.values
    assert out.undefined["waste_recovery_rate"] == "division by zero"
    out = compute_report_kpis({**X, "revenue_from_operations": D("0")}, kpis)
    assert set(out.undefined) == {"energy_intensity", "emissions_intensity", "water_intensity"}


# ---- 2-year change (hand-worked) ----------------------------------------------------------------
@pytest.mark.parametrize(
    "new, old, expected",
    [
        ("40", "50", "-20"),  # 100 * (40 - 50) / 50
        ("100", "80", "25"),  # 100 * (100 - 80) / 80
        ("0", "5", "-100"),
        ("5", "5", "0"),
    ],
)
def test_percent_change(new, old, expected):
    assert percent_change(D(new), D(old)) == D(expected)


def test_percent_change_to_stored_precision():
    # 100 * (250 - 300) / 300 = -16.6666...; stored at 12 places, half-even
    assert quantize(percent_change(D("250"), D("300"))) == D("-16.666666666667")


def test_percent_change_from_zero_is_undefined():
    assert percent_change(D("5"), D("0")) is None


# ---- formula evaluator --------------------------------------------------------------------------
def test_formula_names_and_value():
    f = Formula("100 * a / (b + c)")
    assert f.names == ("a", "b", "c")
    assert f.evaluate({"a": D("1"), "b": D("1"), "c": D("3")}) == D("25")


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os').system('x')",
        "a ** 2",
        "abs(a)",
        "a.b",
        "a if b else c",
        "1.5 * a",
        "[a]",
        "a % b",
        "'text'",
        "lambda: 1",
    ],
)
def test_formula_rejects_anything_but_plain_arithmetic(text):
    with pytest.raises(FormulaError):
        Formula(text)


def test_formula_errors():
    with pytest.raises(FormulaError, match="cannot parse"):
        Formula("a +")
    with pytest.raises(KeyError):
        Formula("a / b").evaluate({"a": D(1)})
    for numerator in (
        1,
        0,
    ):  # 0/0 is InvalidOperation in decimal but must also be ZeroDivisionError
        with pytest.raises(ZeroDivisionError):
            Formula("a / b").evaluate({"a": D(numerator), "b": D(0)})


def test_engine_version_tracks_formulas(kpis):
    v = engine_version(kpis)
    assert v.startswith("1.0+") and len(v) == len("1.0+") + 8
    changed = [
        k.model_copy(update={"formula": k.formula + " + 0"}) if k.code == "water_intensity" else k
        for k in kpis
    ]
    assert engine_version(changed) != v
    assert engine_version(list(reversed(kpis))) == v  # order does not matter


# ---- database step ------------------------------------------------------------------------------
def _add_company(session, db, code="SYA-01", status="included", reason=None):
    sector = session.scalar(select(Sector).where(Sector.code == "SYA"))
    company = Company(
        code=code,
        real_name=f"Co {code}",
        sector_id=sector.id,
        selection_status=status,
        exclusion_reason=reason,
    )
    session.add(company)
    session.flush()
    return company


def _add_year(session, company, fy, values, *, standardized=True):
    report = Report(company_id=company.id, fy=fy, entry_method="manual", boundary="consolidated")
    session.add(report)
    session.flush()
    for code, value in values.items():
        session.add(
            IndicatorValue(
                report_id=report.id,
                indicator=code,
                value=D(value),
                unit="x",
                original_value=D(value) if standardized else None,
                original_unit="x" if standardized else None,
            )
        )
    session.flush()


def test_database_kpis_and_two_year_change(db):
    # energy intensity: FY23 450,000 / 1,500 = 300; FY24 495,000 / 1,800 = 275;
    #                   FY25 500,000 / 2,000 = 250
    # 2-year change FY25 vs FY23: 100 * (250 - 300) / 300 = -16.666666666667 (12 dp, half-even)
    # emissions intensity: FY23 90,000 / 1,500 = 60; FY25 100,000 / 2,000 = 50
    #                      -> 2-year change 100 * (50 - 60) / 60 = -16.666666666667
    with session_scope(db.engine) as s:
        c = _add_company(s, db)
        _add_year(
            s,
            c,
            "FY2022-23",
            {
                "revenue_from_operations": "1500",
                "energy_total": "450000",
                "scope1_emissions": "60000",
                "scope2_emissions": "30000",
            },
        )
        _add_year(
            s,
            c,
            "FY2023-24",
            {
                "revenue_from_operations": "1800",
                "energy_total": "495000",
                "scope1_emissions": "70000",
                "scope2_emissions": "30000",
            },
        )
        _add_year(
            s,
            c,
            "FY2024-25",
            {
                "revenue_from_operations": "2000",
                "energy_total": "500000",
                "scope1_emissions": "80000",
                "scope2_emissions": "20000",
            },
        )
        summary = compute_kpis(s, db.cfg, db.ind)
    with session_scope(db.engine) as s:
        rows = {(r.fy, r.kpi): r for r in s.scalars(select(KpiValue))}
    assert rows[("FY2022-23", "energy_intensity")].value == D("300")
    assert rows[("FY2023-24", "energy_intensity")].value == D("275")
    assert rows[("FY2024-25", "energy_intensity")].value == D("250")
    assert rows[("FY2024-25", "energy_intensity")].change_2y_pct == D("-16.666666666667")
    assert rows[("FY2022-23", "energy_intensity")].change_2y_pct is None  # no base year
    assert rows[("FY2024-25", "emissions_intensity")].value == D("50")
    assert rows[("FY2024-25", "emissions_intensity")].change_2y_pct == D("-16.666666666667")
    assert summary.changes_computed == 2
    assert {r.engine_version for r in rows.values()} == {engine_version(db.ind.kpis)}


def test_large_kpi_change_is_flagged_as_warning(db):
    # emissions intensity 10 -> 20 over two years = +100% (> 60%)
    with session_scope(db.engine) as s:
        c = _add_company(s, db)
        for fy, em in (("FY2022-23", "10"), ("FY2023-24", "15"), ("FY2024-25", "20")):
            _add_year(
                s,
                c,
                fy,
                {"revenue_from_operations": "1", "scope1_emissions": em, "scope2_emissions": "0"},
            )
        compute_kpis(s, db.cfg, db.ind)
    with session_scope(db.engine) as s:
        flags = s.scalars(select(QualityFlag).where(QualityFlag.rule == KPI_CHANGE_2Y)).all()
    assert [(f.fy, f.indicator, f.severity) for f in flags] == [
        ("FY2024-25", "emissions_intensity", "warning")
    ]


def test_zero_base_change_is_undefined_and_flagged(db):
    with session_scope(db.engine) as s:
        c = _add_company(s, db)
        for fy, em in (("FY2022-23", "0"), ("FY2023-24", "1"), ("FY2024-25", "2")):
            _add_year(
                s,
                c,
                fy,
                {"revenue_from_operations": "1", "scope1_emissions": em, "scope2_emissions": "0"},
            )
        compute_kpis(s, db.cfg, db.ind)
    with session_scope(db.engine) as s:
        row = s.scalar(
            select(KpiValue).where(
                KpiValue.fy == "FY2024-25", KpiValue.kpi == "emissions_intensity"
            )
        )
        assert row.change_2y_pct is None
        assert s.scalar(select(QualityFlag).where(QualityFlag.rule == KPI_UNDEFINED)) is not None


def test_rerun_replaces_values_and_excluded_companies_are_skipped(db):
    with session_scope(db.engine) as s:
        a = _add_company(s, db, "SYA-01")
        b = _add_company(s, db, "SYA-02", status="excluded", reason="test")
        for company in (a, b):
            _add_year(
                s, company, "FY2024-25", {"revenue_from_operations": "10", "energy_total": "50"}
            )
        compute_kpis(s, db.cfg, db.ind)
        compute_kpis(s, db.cfg, db.ind)
    with session_scope(db.engine) as s:
        rows = s.scalars(select(KpiValue)).all()
    assert len(rows) == 1 and rows[0].value == D("5")  # only SYA-01, only once


def test_refuses_unstandardized_data(db):
    with session_scope(db.engine) as s:
        c = _add_company(s, db)
        _add_year(s, c, "FY2024-25", {"revenue_from_operations": "10"}, standardized=False)
    with pytest.raises(NotStandardizedError), session_scope(db.engine) as s:
        compute_kpis(s, db.cfg, db.ind)
