"""Data-quality validators (spec §6.5). Each produces flags; none changes or drops data.

Severity: `error` = the value or its report cannot be trusted as it stands; `warning` = worth a
human look. Flags are stored in `quality_flag`, shown in the dashboard, and read by sample
selection. Checks compare values with each other, so they run on standardized data only.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig, StudyConfig
from gauge.db.models import Company, IndicatorValue, QualityFlag, Report
from gauge.kpi.formula import percent_change
from gauge.standardize.fiscal import shift_fy
from gauge.standardize.run import assert_standardized

# Rule identifiers: stable strings that appear in the DB, the dashboard and the paper's data notes.
NON_NEGATIVE = "non_negative"
RENEWABLE_LE_TOTAL = "renewable_le_total"
RECOVERED_LE_GENERATED = "recovered_le_generated"
CONSUMPTION_LE_WITHDRAWAL = "consumption_le_withdrawal"
CHANGE_2Y = "change_2y_gt_60pct"
BOUNDARY_CHANGE = "boundary_change"
BOUNDARY_MISSING = "boundary_missing"
MISSING_INDICATOR = "missing_indicator"
NONPOSITIVE_DENOMINATOR = "nonpositive_denominator"
ZERO_WASTE_GENERATED = "zero_waste_generated"

VALIDATOR_RULES = (
    NON_NEGATIVE,
    RENEWABLE_LE_TOTAL,
    RECOVERED_LE_GENERATED,
    CONSUMPTION_LE_WITHDRAWAL,
    CHANGE_2Y,
    BOUNDARY_CHANGE,
    BOUNDARY_MISSING,
    MISSING_INDICATOR,
    NONPOSITIVE_DENOMINATOR,
    ZERO_WASTE_GENERATED,
)

CHANGE_2Y_THRESHOLD_PCT = Decimal("60")  # §6.5: flag any 2-year change above +/-60%


@dataclass(frozen=True)
class Flag:
    company_id: int
    fy: str | None
    indicator: str | None
    rule: str
    severity: str
    message: str


@dataclass(frozen=True)
class ReportView:
    company_id: int
    code: str
    fy: str
    boundary: str | None
    values: dict[str, Decimal]


# ---- pure checks (unit-testable without a database) --------------------------------------------
def check_report(view: ReportView) -> list[Flag]:
    """Within-report checks: sign, ordering relations, denominators, boundary present."""
    out: list[Flag] = []
    v = view.values

    def flag(rule: str, severity: str, message: str, indicator: str | None = None) -> None:
        out.append(
            Flag(
                view.company_id,
                view.fy,
                indicator,
                rule,
                severity,
                f"{view.code} {view.fy}: {message}",
            )
        )

    for code, value in sorted(v.items()):
        if value < 0:
            flag(NON_NEGATIVE, "error", f"{code} is negative ({value})", code)

    def le(small: str, big: str, rule: str, label: str) -> None:
        if small in v and big in v and v[small] > v[big]:
            flag(rule, "error", f"{label}: {small} ({v[small]}) exceeds {big} ({v[big]})", small)

    le(
        "energy_renewable",
        "energy_total",
        RENEWABLE_LE_TOTAL,
        "renewable energy cannot exceed total",
    )
    le(
        "waste_recovered",
        "waste_generated",
        RECOVERED_LE_GENERATED,
        "recovered waste cannot exceed generated",
    )
    le(
        "water_consumption",
        "water_withdrawal",
        CONSUMPTION_LE_WITHDRAWAL,
        "consumption cannot exceed withdrawal",
    )

    for code in ("revenue_from_operations", "energy_total"):
        if code in v and v[code] <= 0:
            flag(NONPOSITIVE_DENOMINATOR, "error", f"{code} is {v[code]}; KPIs divide by it", code)
    if "waste_generated" in v and v["waste_generated"] == 0:
        flag(
            ZERO_WASTE_GENERATED,
            "warning",
            "waste_generated is 0; recovery rate is undefined",
            "waste_generated",
        )
    if view.boundary is None:
        flag(BOUNDARY_MISSING, "warning", "reporting boundary (standalone/consolidated) not stated")
    return out


def check_completeness(
    company_id: int,
    code: str,
    views_by_fy: dict[str, ReportView],
    fys: list[str],
    required: list[str],
) -> list[Flag]:
    out = []
    for fy in fys:
        view = views_by_fy.get(fy)
        for indicator in required:
            if view is None or indicator not in view.values:
                where = "no report" if view is None else "value missing"
                out.append(
                    Flag(
                        company_id,
                        fy,
                        indicator,
                        MISSING_INDICATOR,
                        "error",
                        f"{code} {fy}: {indicator} - {where}",
                    )
                )
    return out


def check_two_year_change(
    company_id: int, code: str, views_by_fy: dict[str, ReportView], fys: list[str]
) -> list[Flag]:
    """Flag any indicator whose value changed by more than +/-60% over two fiscal years."""
    out = []
    for fy in fys:
        old_view, new_view = views_by_fy.get(shift_fy(fy, -2)), views_by_fy.get(fy)
        if old_view is None or new_view is None:
            continue
        for indicator, new in sorted(new_view.values.items()):
            old = old_view.values.get(indicator)
            if old is None:
                continue
            change = percent_change(new, old)
            if change is None:
                if new != 0:
                    out.append(
                        Flag(
                            company_id,
                            fy,
                            indicator,
                            CHANGE_2Y,
                            "warning",
                            f"{code} {fy}: {indicator} rose from 0 to {new} in two years",
                        )
                    )
            elif abs(change) > CHANGE_2Y_THRESHOLD_PCT:
                out.append(
                    Flag(
                        company_id,
                        fy,
                        indicator,
                        CHANGE_2Y,
                        "warning",
                        f"{code} {fy}: {indicator} changed {change:+.1f}% over two years",
                    )
                )
    return out


def check_boundary_changes(
    company_id: int, code: str, views_by_fy: dict[str, ReportView], fys: list[str]
) -> list[Flag]:
    stated = {
        fy: views_by_fy[fy].boundary for fy in fys if fy in views_by_fy and views_by_fy[fy].boundary
    }
    if len(set(stated.values())) <= 1:
        return []
    detail = ", ".join(f"{fy}: {b}" for fy, b in sorted(stated.items()))
    return [
        Flag(
            company_id,
            None,
            None,
            BOUNDARY_CHANGE,
            "warning",
            f"{code}: reporting boundary changes across years ({detail}); trends may not compare",
        )
    ]


# ---- database step -----------------------------------------------------------------------------
def load_views(session: Session) -> dict[int, tuple[str, dict[str, ReportView]]]:
    """company_id -> (code, {fy: ReportView}) for every non-excluded company."""
    companies = {
        c.id: c
        for c in session.scalars(select(Company).where(Company.selection_status != "excluded"))
    }
    values: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for iv in session.scalars(select(IndicatorValue)):
        values[iv.report_id][iv.indicator] = iv.value
    result: dict[int, tuple[str, dict[str, ReportView]]] = {
        cid: (c.code, {}) for cid, c in companies.items()
    }
    for report in session.scalars(select(Report)):
        if report.company_id in companies:
            code = companies[report.company_id].code
            result[report.company_id][1][report.fy] = ReportView(
                report.company_id, code, report.fy, report.boundary, values.get(report.id, {})
            )
    return result


@dataclass
class ValidationSummary:
    flags: list[Flag]

    def count(self, severity: str | None = None, rule: str | None = None) -> int:
        return sum(
            1
            for f in self.flags
            if (severity is None or f.severity == severity) and (rule is None or f.rule == rule)
        )


def run_validators(
    session: Session, cfg: StudyConfig, indicators: IndicatorsConfig
) -> ValidationSummary:
    """Recompute all validator flags (replacing the previous set) and store them."""
    assert_standardized(session)
    fys = cfg.study.trend_fys
    required = [i.code for i in indicators.indicators]
    flags: list[Flag] = []
    for company_id, (code, views) in sorted(load_views(session).items()):
        for view in views.values():
            flags.extend(check_report(view))
        flags.extend(check_completeness(company_id, code, views, fys, required))
        flags.extend(check_two_year_change(company_id, code, views, fys))
        flags.extend(check_boundary_changes(company_id, code, views, fys))

    session.execute(delete(QualityFlag).where(QualityFlag.rule.in_(VALIDATOR_RULES)))
    session.add_all(
        QualityFlag(
            company_id=f.company_id,
            fy=f.fy,
            indicator=f.indicator,
            rule=f.rule,
            severity=f.severity,
            message=f.message,
        )
        for f in flags
    )
    session.flush()
    return ValidationSummary(flags)
