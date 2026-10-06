"""Deterministic KPI engine: the study's ground truth (spec §4.2).

All arithmetic is Decimal. Stored values are rounded half-even to 12 decimal places, the scale of
the PostgreSQL column, so SQLite and PostgreSQL hold identical numbers. `engine_version` embeds a
hash of the KPI formulas: if a formula in config/indicators.yaml changes, stored values carry the
old hash and can be told apart from fresh ones.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig, KpiSpec, StudyConfig
from gauge.db.models import KpiValue, QualityFlag
from gauge.kpi.formula import CONTEXT, Formula, percent_change
from gauge.quality.validators import CHANGE_2Y_THRESHOLD_PCT, Flag, load_views
from gauge.standardize.fiscal import shift_fy
from gauge.standardize.run import assert_standardized

ENGINE_BASE_VERSION = "1.0"
QUANTUM = Decimal("1E-12")
KPI_UNDEFINED = "kpi_undefined"
KPI_CHANGE_2Y = "kpi_change_2y_gt_60pct"
KPI_RULES = (KPI_UNDEFINED, KPI_CHANGE_2Y)


def quantize(value: Decimal) -> Decimal:
    return value.quantize(QUANTUM, context=CONTEXT)


def engine_version(kpis: list[KpiSpec]) -> str:
    digest = hashlib.sha256(
        "|".join(f"{k.code}={k.formula}" for k in sorted(kpis, key=lambda k: k.code)).encode()
    )
    return f"{ENGINE_BASE_VERSION}+{digest.hexdigest()[:8]}"


@dataclass
class ReportKpis:
    values: dict[str, Decimal] = field(default_factory=dict)
    missing: dict[str, list[str]] = field(default_factory=dict)  # kpi -> missing input indicators
    undefined: dict[str, str] = field(default_factory=dict)  # kpi -> reason (division by zero)


def compute_report_kpis(values: Mapping[str, Decimal], kpis: list[KpiSpec]) -> ReportKpis:
    """KPIs for one company-year from its standardized indicator values."""
    out = ReportKpis()
    for spec in kpis:
        formula = Formula(spec.formula)
        absent = [n for n in formula.names if n not in values]
        if absent:
            out.missing[spec.code] = absent
            continue
        try:
            out.values[spec.code] = quantize(formula.evaluate(values))
        except ZeroDivisionError:
            out.undefined[spec.code] = "division by zero"
    return out


@dataclass
class KpiSummary:
    values_written: int = 0
    changes_computed: int = 0
    flags: list[Flag] = field(default_factory=list)


def compute_kpis(session: Session, cfg: StudyConfig, indicators: IndicatorsConfig) -> KpiSummary:
    """Rebuild kpi_value for every non-excluded company (KPIs are fully derived data)."""
    assert_standardized(session)
    fys = cfg.study.trend_fys
    version = engine_version(indicators.kpis)
    session.execute(delete(KpiValue))
    session.execute(delete(QualityFlag).where(QualityFlag.rule.in_(KPI_RULES)))

    summary = KpiSummary()
    for company_id, (code, views) in sorted(load_views(session).items()):
        results = {
            fy: compute_report_kpis(view.values, indicators.kpis) for fy, view in views.items()
        }
        rows: dict[tuple[str, str], KpiValue] = {}
        for fy, result in sorted(results.items()):
            for kpi, value in result.values.items():
                row = KpiValue(
                    company_id=company_id, fy=fy, kpi=kpi, value=value, engine_version=version
                )
                session.add(row)
                rows[(fy, kpi)] = row
                summary.values_written += 1
            for kpi, reason in result.undefined.items():
                summary.flags.append(
                    Flag(
                        company_id,
                        fy,
                        kpi,
                        KPI_UNDEFINED,
                        "warning",
                        f"{code} {fy}: {kpi} undefined ({reason})",
                    )
                )

        for fy in fys:
            for spec in indicators.kpis:
                new, old = rows.get((fy, spec.code)), rows.get((shift_fy(fy, -2), spec.code))
                if new is None or old is None:
                    continue
                change = percent_change(new.value, old.value)
                if change is None:
                    summary.flags.append(
                        Flag(
                            company_id,
                            fy,
                            spec.code,
                            KPI_UNDEFINED,
                            "warning",
                            f"{code} {fy}: {spec.code} 2-year change undefined (base is 0)",
                        )
                    )
                    continue
                new.change_2y_pct = quantize(change)
                summary.changes_computed += 1
                if abs(change) > CHANGE_2Y_THRESHOLD_PCT:
                    summary.flags.append(
                        Flag(
                            company_id,
                            fy,
                            spec.code,
                            KPI_CHANGE_2Y,
                            "warning",
                            f"{code} {fy}: {spec.code} changed {change:+.1f}% over two years",
                        )
                    )

    session.add_all(
        QualityFlag(
            company_id=f.company_id,
            fy=f.fy,
            indicator=f.indicator,
            rule=f.rule,
            severity=f.severity,
            message=f.message,
        )
        for f in summary.flags
    )
    session.flush()
    return summary
