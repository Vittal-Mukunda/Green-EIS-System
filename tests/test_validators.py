"""Quality validators (spec §6.5). Pure checks first, then the database step."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from gauge.db.models import Company, IndicatorValue, QualityFlag, Report, Sector
from gauge.db.session import session_scope
from gauge.quality import validators as q
from gauge.quality.validators import ReportView
from gauge.standardize.run import NotStandardizedError

D = Decimal
GOOD = {
    "revenue_from_operations": D("1000"),
    "energy_total": D("500"),
    "energy_renewable": D("100"),
    "water_withdrawal": D("900"),
    "water_consumption": D("600"),
    "waste_generated": D("50"),
    "waste_recovered": D("40"),
    "scope1_emissions": D("70"),
    "scope2_emissions": D("30"),
}


def view(values=None, fy="FY2024-25", boundary="consolidated", code="SYA-01") -> ReportView:
    return ReportView(1, code, fy, boundary, dict(GOOD if values is None else values))


def rules(flags) -> list[str]:
    return sorted(f.rule for f in flags)


# ---- within-report checks -----------------------------------------------------------------------
def test_clean_report_has_no_flags():
    assert q.check_report(view()) == []


def test_negative_values_are_errors():
    flags = q.check_report(view({**GOOD, "scope1_emissions": D("-1")}))
    assert [(f.rule, f.severity, f.indicator) for f in flags] == [
        (q.NON_NEGATIVE, "error", "scope1_emissions")
    ]


@pytest.mark.parametrize(
    "small, big, rule",
    [
        ("energy_renewable", "energy_total", q.RENEWABLE_LE_TOTAL),
        ("waste_recovered", "waste_generated", q.RECOVERED_LE_GENERATED),
        ("water_consumption", "water_withdrawal", q.CONSUMPTION_LE_WITHDRAWAL),
    ],
)
def test_ordering_relations(small, big, rule):
    over = q.check_report(view({**GOOD, small: GOOD[big] + 1}))
    assert [(f.rule, f.severity, f.indicator) for f in over] == [(rule, "error", small)]
    assert q.check_report(view({**GOOD, small: GOOD[big]})) == []  # equal is allowed


def test_nonpositive_denominators():
    flags = q.check_report(view({**GOOD, "revenue_from_operations": D("0")}))
    assert rules(flags) == [q.NONPOSITIVE_DENOMINATOR]
    flags = q.check_report(view({**GOOD, "energy_total": D("0"), "energy_renewable": D("0")}))
    assert rules(flags) == [q.NONPOSITIVE_DENOMINATOR]


def test_zero_waste_generated_is_a_warning_not_an_error():
    flags = q.check_report(view({**GOOD, "waste_generated": D("0"), "waste_recovered": D("0")}))
    assert [(f.rule, f.severity) for f in flags] == [(q.ZERO_WASTE_GENERATED, "warning")]


def test_missing_boundary_is_a_warning():
    flags = q.check_report(view(boundary=None))
    assert [(f.rule, f.severity) for f in flags] == [(q.BOUNDARY_MISSING, "warning")]


def test_checks_skip_what_is_not_there():
    assert q.check_report(view({"energy_renewable": D("5")})) == []  # no total to compare with


def test_messages_name_company_and_year():
    flag = q.check_report(view({**GOOD, "scope1_emissions": D("-1")}, code="CEM-03"))[0]
    assert "CEM-03" in flag.message and "FY2024-25" in flag.message


# ---- completeness -------------------------------------------------------------------------------
FYS = ["FY2022-23", "FY2023-24", "FY2024-25"]
REQUIRED = list(GOOD)


def views(**by_fy) -> dict[str, ReportView]:
    return {fy: view(v, fy=fy) for fy, v in by_fy.items()}


def test_completeness_flags_missing_values_and_reports():
    by_fy = {
        "FY2022-23": view(fy="FY2022-23"),
        "FY2024-25": view({k: v for k, v in GOOD.items() if k != "water_consumption"}),
    }
    flags = q.check_completeness(1, "SYA-01", by_fy, FYS, REQUIRED)
    found = {(f.fy, f.indicator): f.message for f in flags}
    assert set(found) == {("FY2023-24", i) for i in REQUIRED} | {("FY2024-25", "water_consumption")}
    assert "no report" in found[("FY2023-24", "energy_total")]
    assert "value missing" in found[("FY2024-25", "water_consumption")]
    assert {f.rule for f in flags} == {q.MISSING_INDICATOR} and {f.severity for f in flags} == {
        "error"
    }


def test_complete_company_has_no_missing_flags():
    full = {fy: view(fy=fy) for fy in FYS}
    assert q.check_completeness(1, "SYA-01", full, FYS, REQUIRED) == []


# ---- two-year change ----------------------------------------------------------------------------
def two_year(old, new, indicator="scope1_emissions"):
    by_fy = {
        "FY2022-23": view({indicator: D(old)}, fy="FY2022-23"),
        "FY2024-25": view({indicator: D(new)}, fy="FY2024-25"),
    }
    return q.check_two_year_change(1, "SYA-01", by_fy, FYS)


@pytest.mark.parametrize(
    "old, new, flagged",
    [
        ("100", "160", False),  # exactly +60% is not "above"
        ("100", "160.1", True),  # +60.1%
        ("100", "40", False),  # exactly -60%
        ("100", "39.9", True),  # -60.1%
        ("100", "100", False),
        ("0", "0", False),  # nothing happened
        ("0", "5", True),  # rose from zero: change is unbounded
    ],
)
def test_two_year_change_threshold(old, new, flagged):
    flags = two_year(old, new)
    assert bool(flags) is flagged
    if flags:
        assert flags[0].rule == q.CHANGE_2Y and flags[0].severity == "warning"
        assert flags[0].fy == "FY2024-25"


def test_two_year_change_needs_both_years():
    by_fy = {"FY2024-25": view(fy="FY2024-25")}
    assert q.check_two_year_change(1, "SYA-01", by_fy, FYS) == []


def test_two_year_change_message_has_the_percentage():
    assert "+200.0%" in two_year("100", "300")[0].message


# ---- boundary -----------------------------------------------------------------------------------
def test_boundary_change_across_years():
    by_fy = {
        "FY2022-23": view(fy="FY2022-23", boundary="standalone"),
        "FY2023-24": view(fy="FY2023-24", boundary="consolidated"),
        "FY2024-25": view(fy="FY2024-25", boundary="consolidated"),
    }
    flags = q.check_boundary_changes(1, "SYA-01", by_fy, FYS)
    assert [(f.rule, f.severity, f.fy) for f in flags] == [(q.BOUNDARY_CHANGE, "warning", None)]
    assert "FY2022-23: standalone" in flags[0].message


def test_stable_or_unstated_boundary_is_fine():
    stable = {fy: view(fy=fy, boundary="standalone") for fy in FYS}
    assert q.check_boundary_changes(1, "SYA-01", stable, FYS) == []
    partly = {
        "FY2022-23": view(fy="FY2022-23", boundary=None),
        "FY2024-25": view(fy="FY2024-25", boundary="consolidated"),
    }
    assert q.check_boundary_changes(1, "SYA-01", partly, FYS) == []  # missing is a separate rule


# ---- database step ------------------------------------------------------------------------------
def _store(db, code="SYA-01", status="included", values=GOOD, fy="FY2024-25", standardized=True):
    with session_scope(db.engine) as s:
        sector = s.scalar(select(Sector).where(Sector.code == "SYA"))
        company = s.scalar(select(Company).where(Company.code == code))
        if company is None:
            company = Company(
                code=code,
                real_name=code,
                sector_id=sector.id,
                selection_status=status,
                exclusion_reason="x" if status == "excluded" else None,
            )
            s.add(company)
            s.flush()
        report = Report(
            company_id=company.id, fy=fy, boundary="consolidated", entry_method="manual"
        )
        s.add(report)
        s.flush()
        for indicator, value in values.items():
            s.add(
                IndicatorValue(
                    report_id=report.id,
                    indicator=indicator,
                    value=value,
                    unit="u",
                    original_value=value if standardized else None,
                    original_unit="u" if standardized else None,
                )
            )


def test_run_validators_stores_flags_and_replaces_them(db):
    _store(db, values={**GOOD, "energy_renewable": D("999")})
    for _ in range(2):  # a second run must not duplicate
        with session_scope(db.engine) as s:
            summary = q.run_validators(s, db.cfg, db.ind)
    with session_scope(db.engine) as s:
        stored = s.scalars(
            select(QualityFlag).where(QualityFlag.rule == q.RENEWABLE_LE_TOTAL)
        ).all()
    assert (
        len(stored) == 1
        and stored[0].severity == "error"
        and stored[0].indicator == "energy_renewable"
    )
    assert summary.count("error", q.RENEWABLE_LE_TOTAL) == 1


def test_validators_only_replace_their_own_flags(db):
    _store(db)
    with session_scope(db.engine) as s:
        company = s.scalar(select(Company))
        s.add(
            QualityFlag(
                company_id=company.id, rule="kpi_undefined", severity="warning", message="keep"
            )
        )
        q.run_validators(s, db.cfg, db.ind)
    with session_scope(db.engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(QualityFlag)
                .where(QualityFlag.rule == "kpi_undefined")
            )
            == 1
        )


def test_validators_skip_excluded_companies(db):
    _store(db, "SYA-01", values={**GOOD, "energy_renewable": D("999")})
    _store(db, "SYA-02", status="excluded", values={**GOOD, "energy_renewable": D("999")})
    with session_scope(db.engine) as s:
        q.run_validators(s, db.cfg, db.ind)
        codes = {f.message.split()[0] for f in s.scalars(select(QualityFlag))}
    assert codes == {"SYA-01"}


def test_validators_refuse_unstandardized_data(db):
    _store(db, standardized=False)
    with pytest.raises(NotStandardizedError), session_scope(db.engine) as s:
        q.run_validators(s, db.cfg, db.ind)
