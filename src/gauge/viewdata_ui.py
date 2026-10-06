"""Presentation helpers over the evidence database, for the redesigned dashboard.

Everything here arranges figures the system has already computed: no KPI formula, validation rule,
benchmark method or ranking rule is changed or reimplemented. The one statistic computed here, the
P25 and P75 of a sector sample, reuses the exact quantile method of `gauge.benchmark.quantiles` on the
same set of figures that `sector_overview` uses for its median (those that pass the data checks), so
the spread shown beside a median always agrees with it. No model is called.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.benchmark.quantiles import describe
from gauge.config import IndicatorsConfig
from gauge.db.models import Company, IndicatorValue, KpiValue, QualityFlag, Report
from gauge.viewdata import (
    DATA_CHECK,
    MIN_FOR_BAND,
    RULE_NOTES,
    _flagged_kpis,
    flag_register,
    pretty_unit,
)

SUMMARY_COLUMNS = [
    "sector",
    "kpi",
    "label",
    "unit",
    "better",
    "companies",
    "compared",
    "median",
    "p25",
    "p75",
    "data checks",
]


# ---- sector summaries (study sample) -------------------------------------------------------------
def sector_summary(matrix: pd.DataFrame) -> pd.DataFrame:
    """Per sector and KPI: how many companies, how many pass the data checks, and the median, P25
    and P75 of those that do. With fewer than three the statistics are left empty, as `sector_overview`
    leaves the median empty."""
    rows = []
    if matrix.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    for (sector, kpi), part in matrix.groupby(["sector", "kpi"], sort=False):
        clean = part[part["data check"] == ""]["value"]
        median = p25 = p75 = float("nan")
        if len(clean) >= MIN_FOR_BAND:
            stats = describe([Decimal(repr(float(v))) for v in clean])
            median, p25, p75 = (float(stats[k]) for k in ("median", "p25", "p75"))
        first = part.iloc[0]
        rows.append(
            {
                "sector": sector,
                "kpi": kpi,
                "label": first["label"],
                "unit": first["unit"],
                "better": first["better"],
                "companies": len(part),
                "compared": len(clean),
                "median": median,
                "p25": p25,
                "p75": p75,
                "data checks": int((part["band"] == DATA_CHECK).sum()),
            }
        )
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def figures_failing_checks(matrix: pd.DataFrame) -> pd.DataFrame:
    """The KPI figures shown but not ranked, each with the plain-language reason for each rule."""
    if matrix.empty:
        return pd.DataFrame(columns=["code", "sector", "label", "value", "unit", "rules", "reason"])
    flagged = matrix[matrix["band"] == DATA_CHECK].copy()
    flagged["rules"] = flagged["data check"]
    flagged["reason"] = [
        "; ".join(RULE_NOTES.get(r.strip(), r.strip()) for r in rules.split(",") if r.strip())
        for rules in flagged["data check"]
    ]
    return flagged[["code", "sector", "label", "value", "unit", "rules", "reason"]].reset_index(
        drop=True
    )


def largest_movements(
    matrix: pd.DataFrame, top: int = 8, min_abs_pct: float = 10.0
) -> pd.DataFrame:
    """The biggest year-on-year moves of at least `min_abs_pct`, whichever direction, largest first.
    A figure that fails a data check has no change in the matrix, so it never appears here."""
    columns = ["code", "sector", "label", "unit", "previous year", "value", "change %", "movement"]
    if matrix.empty:
        return pd.DataFrame(columns=columns)
    moved = matrix[matrix["change %"].abs() >= min_abs_pct].copy()
    moved["_size"] = moved["change %"].abs()
    moved = moved.sort_values(["_size", "code", "kpi"], ascending=[False, True, True])
    return moved[columns].head(top).reset_index(drop=True)


def pct_vs_median(value: float, median: float) -> float:
    """How far a figure is above (+) or below (-) the sample median, in percent of the median."""
    if pd.isna(value) or pd.isna(median) or median == 0:
        return float("nan")
    return (value - median) / abs(median) * 100


def fmt_figure(value: float, unit: str) -> str:
    """A figure as text, without its unit: percentages to one decimal place (103.5, not 104)."""
    from gauge.viewdata import fmt_number

    if pd.isna(value):
        return "not available"
    return f"{value:,.1f}" if unit.strip() == "%" else fmt_number(value)


def fmt_value(value: float, unit: str) -> str:
    """A figure with its unit: 103.5 %, 8.42 tCO2e per ₹ crore."""
    return f"{fmt_figure(value, unit)} {unit}".strip() if not pd.isna(value) else "not available"


# ---- formulas ------------------------------------------------------------------------------------
_NAME = re.compile(r"[a-z][a-z_0-9]*")


def _tex_text(label: str) -> str:
    for char in ("\\", "&", "%", "#", "_", "{", "}"):
        label = label.replace(char, "\\" + char if char != "\\" else "")
    return label


def _balanced_outer(expr: str) -> bool:
    if not (expr.startswith("(") and expr.endswith(")")):
        return False
    depth = 0
    for i, ch in enumerate(expr):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and i < len(expr) - 1:
            return False
    return True


def formula_latex(formula: str, labels: Mapping[str, str]) -> str:
    """A KPI formula from config/indicators.yaml as LaTeX, with indicator codes replaced by their labels.
    A top-level division becomes a fraction. Generated from the configured formula so it cannot drift."""
    expr = formula.strip()
    depth, split = 0, None
    for i, ch in enumerate(expr):
        depth += ch == "("
        depth -= ch == ")"
        if ch == "/" and depth == 0:
            split = i

    def term(text: str) -> str:
        text = text.strip()
        while _balanced_outer(text):
            text = text[1:-1].strip()
        text = _NAME.sub(
            lambda m: "\\text{" + _tex_text(labels.get(m.group(0), m.group(0))) + "}", text
        )
        return text.replace("*", "\\times")

    if split is None:
        return term(expr)
    return "\\frac{" + term(expr[:split]) + "}{" + term(expr[split + 1 :]) + "}"


# ---- the data quality register -------------------------------------------------------------------
REVIEW_STAMP = re.compile(r"checked by (?P<who>.+?) via the dashboard on (?P<on>\d{4}-\d{2}-\d{2})")
REGISTER_COLUMNS = [
    "code",
    "sector",
    "fy",
    "metric",
    "indicator_code",
    "reported",
    "rule",
    "severity",
    "issue",
    "status",
    "tone",
    "reviewer",
    "verified_on",
    "note",
    "item_id",
]


def _review_of(note: str | None) -> tuple[str | None, str | None]:
    match = REVIEW_STAMP.search(note or "")
    return (match["who"], match["on"]) if match else (None, None)


def register_rows(session: Session, indicators: IndicatorsConfig) -> pd.DataFrame:
    """Every data-quality flag as one audit-register row: the figure, the issue, the status and who
    reviewed it. Statuses are what is known, never a verdict on the company:

    - an error on a figure no person has checked: needs verification
    - an error on a figure a person has checked: the recorded result
    - missing data: not available (there is nothing to verify)
    - a warning about a correction the system made: noted
    """
    flags = flag_register(session)
    if flags.empty:
        return pd.DataFrame(columns=REGISTER_COLUMNS)
    label = {i.code: i.label for i in indicators.indicators}
    units = {i.code: pretty_unit(i.unit) for i in indicators.indicators}
    kpi_label = {k.code: k.label for k in indicators.kpis}
    kpi_unit = {k.code: pretty_unit(k.unit) for k in indicators.kpis}
    kpi_values = {
        (code, fy, kpi): float(value)
        for code, fy, kpi, value in session.execute(
            select(Company.code, KpiValue.fy, KpiValue.kpi, KpiValue.value).join(
                Company, Company.id == KpiValue.company_id
            )
        )
    }
    stored = {
        (code, fy, indicator): (item_id, float(value), unit, verified, note)
        for code, fy, indicator, item_id, value, unit, verified, note in session.execute(
            select(
                Company.code,
                Report.fy,
                IndicatorValue.indicator,
                IndicatorValue.id,
                IndicatorValue.value,
                IndicatorValue.unit,
                IndicatorValue.verified,
                IndicatorValue.verification_note,
            )
            .join(Report, Report.company_id == Company.id)
            .join(IndicatorValue, IndicatorValue.report_id == Report.id)
        )
    }
    flagged = _flagged_kpis(session, indicators)
    out = []
    for r in flags.to_dict("records"):
        code, fy, indicator, rule = r["code"], r["fy"], r["indicator"], r["rule"]
        found = stored.get((code, fy, indicator))
        kpis = sorted(
            k for (c, y, k), rules in flagged.items() if c == code and y == fy and rule in rules
        )
        if rule == "missing_indicator":
            reported, metric = (
                "not available",
                label.get(indicator, indicator or "a core indicator"),
            )
        elif kpis:
            kpi = kpis[0]
            reported = fmt_value(kpi_values.get((code, fy, kpi), float("nan")), kpi_unit[kpi])
            metric = kpi_label[kpi]
        elif found:
            reported = fmt_value(found[1], units.get(indicator, found[2]))
            metric = label.get(indicator, indicator)
        else:
            reported, metric = "not available", label.get(indicator, indicator or "company-wide")
        reviewer = verified_on = None
        if rule == "missing_indicator":
            status, tone = "Data unavailable", "na"
        elif r["severity"] != "error":
            status, tone = (
                "Noted, no action needed" if rule == "xbrl_override_applied" else "Review",
                "info",
            )
        elif found and found[3] is not None:
            reviewer, verified_on = _review_of(found[4])
            status, tone = (
                ("Reviewed: matches filing", "ok")
                if found[3]
                else ("Reviewed: error recorded", "danger")
            )
        else:
            status, tone = "Needs verification", "warn"
        out.append(
            {
                "code": code,
                "sector": r["sector"],
                "fy": fy or "all years",
                "metric": metric,
                "indicator_code": indicator,
                "reported": reported,
                "rule": rule,
                "severity": r["severity"],
                "issue": RULE_NOTES.get(rule, rule),
                "status": status,
                "tone": tone,
                "reviewer": reviewer,
                "verified_on": verified_on,
                "note": found[4] if found else None,
                "item_id": found[0] if found else None,
            }
        )
    return pd.DataFrame(out, columns=REGISTER_COLUMNS)


# ---- the chain from a KPI back to its filing -----------------------------------------------------
def source_trace(
    session: Session, code: str, fy: str, kpi_code: str, indicators: IndicatorsConfig
) -> dict:
    """Everything behind one KPI figure: its value, the figures it is computed from (as stored and as
    filed), validation flags, the filing, its SHA-256 and the date it was retrieved."""
    spec = next(k for k in indicators.kpis if k.code == kpi_code)
    labels = {i.code: i.label for i in indicators.indicators}
    units = {i.code: pretty_unit(i.unit) for i in indicators.indicators}
    company = session.scalar(select(Company).where(Company.code == code))
    report = session.scalar(
        select(Report)
        .join(Company, Company.id == Report.company_id)
        .where(Company.code == code, Report.fy == fy)
    )
    value = None
    if company is not None:
        stored = session.scalar(
            select(KpiValue.value).where(
                KpiValue.company_id == company.id, KpiValue.fy == fy, KpiValue.kpi == kpi_code
            )
        )
        value = None if stored is None else float(stored)
    needed = [n for n in dict.fromkeys(_NAME.findall(spec.formula)) if n in labels]
    rows = {}
    if report is not None:
        for iv in session.scalars(
            select(IndicatorValue).where(IndicatorValue.report_id == report.id)
        ):
            rows[iv.indicator] = iv
    flags = (
        session.execute(
            select(
                QualityFlag.indicator, QualityFlag.rule, QualityFlag.severity, QualityFlag.message
            ).where(
                QualityFlag.company_id == company.id,
                (QualityFlag.fy == fy) | QualityFlag.fy.is_(None),
            )
        ).all()
        if company is not None
        else []
    )
    inputs = []
    for name in needed:
        iv = rows.get(name)
        touched = [f for f in flags if f[0] == name]
        inputs.append(
            {
                "code": name,
                "label": labels[name],
                "present": iv is not None,
                "value": None if iv is None else float(iv.value),
                "unit": units[name],
                "as_filed": None
                if iv is None or iv.original_value is None
                else float(iv.original_value),
                "as_filed_unit": None if iv is None else iv.original_unit,
                "element": None if iv is None else iv.page_ref,
                "verified": None if iv is None else iv.verified,
                "flags": [f"{f[1]}" for f in touched],
                "overrides": [f[3] for f in touched if f[1] == "xbrl_override_applied"],
            }
        )
    rules = sorted({f[1] for f in flagged_rules(session, indicators, code, fy, kpi_code)})
    checked = sum(1 for i in inputs if i["verified"] is not None)
    return {
        "kpi": {
            "code": spec.code,
            "label": spec.label,
            "unit": pretty_unit(spec.unit),
            "better": spec.better,
            "value": value,
        },
        "formula": spec.formula,
        "formula_latex": formula_latex(spec.formula, labels),
        "inputs": inputs,
        "converted": sum(
            1
            for i in inputs
            if i["as_filed_unit"] and i["as_filed"] is not None and i["as_filed_unit"] != i["unit"]
        ),
        "overrides": [text for i in inputs for text in i["overrides"]],
        "rules": rules,
        "checked": checked,
        "of": sum(1 for i in inputs if i["present"]),
        "report": filing_facts(session, code, fy),
    }


def flagged_rules(
    session: Session, indicators: IndicatorsConfig, code: str, fy: str, kpi_code: str
) -> list[tuple[str, str]]:
    """The error rules that stop this KPI figure being ranked (empty when it passes)."""
    rules = _flagged_kpis(session, indicators).get((code, fy, kpi_code), set())
    return [(kpi_code, r) for r in sorted(rules)]


# ---- one filing, as provenance -------------------------------------------------------------------
def filing_facts(session: Session, code: str, fy: str) -> dict | None:
    """The filing behind a company-year: file, SHA-256, retrieval date, how it was read. None when no
    filing is loaded."""
    report = session.scalar(
        select(Report)
        .join(Company, Company.id == Report.company_id)
        .where(Company.code == code, Report.fy == fy)
    )
    if report is None:
        return None
    return {
        "source_file": report.source_file,
        "sha256": report.file_sha256,
        "retrieved_on": report.retrieved_on.isoformat() if report.retrieved_on else None,
        "entry_method": report.entry_method,
        "boundary": report.boundary,
        "assured": report.assured,
    }


def unit_reconciliation(lineage: pd.DataFrame) -> dict:
    """How many stored values were converted from the unit printed in the filing: `values`, `converted`."""
    if lineage.empty:
        return {"values": 0, "converted": 0}
    filed = lineage["as-filed unit"].notna() & lineage["as filed"].notna()
    return {
        "values": len(lineage),
        "converted": int((filed & (lineage["as-filed unit"] != lineage["unit"])).sum()),
    }
