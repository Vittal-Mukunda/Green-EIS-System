"""Results tables built from the stored metric rows (CSV for analysis, Markdown for reading).

Every table is a pandas DataFrame of raw numbers. A column `x` with companions `x_lo` and `x_hi` is
shown as `x [lo, hi]` in Markdown. Nothing here interprets a result: tables carry numbers, the rule
each hypothesis is checked against, and the outcome of that mechanical check.
"""

from __future__ import annotations

import math

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gauge.db.models import Condition, Model, Run
from gauge.evaluate.results import Metric, load_metrics
from gauge.parse.rates import parse_rates


def _index(metrics: list[Metric]) -> dict[tuple, Metric]:
    return {(m.metric, m.model, m.condition): m for m in metrics}


def _put(row: dict, name: str, m: Metric | None, *, ci: bool = True) -> None:
    row[name] = None if m is None else m.value
    if ci:
        row[name + "_lo"] = None if m is None else m.ci_low
        row[name + "_hi"] = None if m is None else m.ci_high


def _models(session: Session) -> dict[str, Model]:
    return {m.key: m for m in session.scalars(select(Model).order_by(Model.key))}


# ---- tables -----------------------------------------------------------------------------------------
def scorecard(session: Session, metrics: list[Metric]) -> pd.DataFrame:
    ix, models = _index(metrics), _models(session)
    rows = []
    for key, model in models.items():
        for cond in sorted({m.condition for m in metrics if m.condition}):
            if ("t2_accuracy", key, cond) not in ix:
                continue
            row = {"model": key, "role": model.role, "model_name": model.name, "condition": cond}
            acc = ix[("t2_accuracy", key, cond)]
            row["n_judgments"] = acc.n
            _put(row, "t2_accuracy", acc)
            _put(row, "valid_share", ix.get(("valid_share", key, cond)))
            _put(row, "t2_repeat_agreement", ix.get(("t2_repeatability_agreement", key, cond)))
            _put(row, "t2_repeat_kappa", ix.get(("t2_repeatability_kappa", key, cond)), ci=False)
            _put(row, "t3_mean_rating", ix.get(("t3_mean_rating", key, cond)), ci=False)
            _put(row, "t3_repeat_wkappa", ix.get(("t3_repeatability_wkappa", key, cond)), ci=False)
            rows.append(row)
    return pd.DataFrame(rows)


def context_effects(session: Session, metrics: list[Metric]) -> pd.DataFrame:
    ix, models = _index(metrics), _models(session)
    rows = []
    for key, model in models.items():
        if ("t2_context_distortion", key, None) not in ix:
            continue
        row = {"model": key, "role": model.role, "model_name": model.name}
        dist = ix[("t2_context_distortion", key, None)]
        row["n_pairs"] = dist.n
        _put(row, "t2_context_distortion", dist)
        _put(row, "t3_mean_rating_shift", ix.get(("t3_mean_rating_shift", key, None)), ci=False)
        for label in ("consistent", "violating", "unconstrained"):
            m = ix.get((f"t3_{label}_rate", key, None))
            _put(row, f"t3_{label}", m)
            row["n_transitions"] = m.n if m else row.get("n_transitions")
        rows.append(row)
    return pd.DataFrame(rows)


def agreement_between_models(metrics: list[Metric]) -> pd.DataFrame:
    ix = _index(metrics)
    names = [
        ("t2_between_alpha_nominal", "t2_alpha_nominal"),
        ("t2_between_fleiss_kappa", "t2_fleiss_kappa"),
        ("t3_between_alpha_ordinal", "t3_alpha_ordinal"),
        ("t2_between_kappa_pairwise", "t2_kappa_pairwise"),
        ("t3_between_wkappa_pairwise", "t3_wkappa_pairwise"),
        ("t2_within_kappa_mean", "t2_within_kappa_mean"),
        ("t3_within_wkappa_mean", "t3_within_wkappa_mean"),
    ]
    rows = []
    for cond in sorted({m.condition for m in metrics if m.metric == "t2_between_alpha_nominal"}):
        first = ix[("t2_between_alpha_nominal", None, cond)]
        row = {"condition": cond, "n_companies": first.n}
        for metric, label in names:
            _put(row, label, ix.get((metric, None, cond)))
        rows.append(row)
    return pd.DataFrame(rows)


def attribute_agreement(session: Session, metrics: list[Metric]) -> pd.DataFrame:
    ix, models = _index(metrics), _models(session)
    rows = []
    for cond in sorted({m.condition for m in metrics if m.metric == "msa_within_appraiser"}):
        for key, model in models.items():
            within = ix.get(("msa_within_appraiser", key, cond))
            if within is None:
                continue
            row = {"condition": cond, "appraiser": key, "role": model.role, "n_companies": within.n}
            _put(row, "within_appraiser", within)
            _put(row, "vs_standard", ix.get(("msa_vs_standard", key, cond)))
            _put(row, "kappa_vs_standard", ix.get(("msa_kappa_vs_standard", key, cond)), ci=False)
            rows.append(row)
        between = ix.get(("msa_between_appraisers", None, cond))
        if between is not None:
            row = {
                "condition": cond,
                "appraiser": "ALL (primary panel)",
                "role": "primary",
                "n_companies": between.n,
            }
            _put(row, "between_appraisers", between)
            _put(row, "all_vs_standard", ix.get(("msa_all_vs_standard", None, cond)))
            rows.append(row)
    return pd.DataFrame(rows)


def hypothesis_summary(metrics: list[Metric]) -> pd.DataFrame:
    rows = []
    for m in metrics:
        if m.metric.endswith("_outcome"):
            d = m.detail
            rows.append(
                {
                    "hypothesis": m.metric.split("_")[0].upper(),
                    "statement": d.get("statement"),
                    "metric": d.get("metric"),
                    "test": d.get("test"),
                    "falsification_condition": d.get("falsification"),
                    "outcome": d.get("outcome"),
                    "outcome_rule": d.get("outcome_rule"),
                    "note": d.get("note"),
                }
            )
    return pd.DataFrame(rows)


def hypothesis_tests(metrics: list[Metric]) -> pd.DataFrame:
    rows = []
    for m in metrics:
        if m.metric.endswith("_test"):
            d = m.detail
            extra = {k: v for k, v in d.items() if k not in ("label", "p", "p_holm")}
            row = {
                "hypothesis": m.metric.split("_")[0].upper(),
                "test": d.get("label"),
                "estimate": m.value,
                "estimate_lo": m.ci_low,
                "estimate_hi": m.ci_high,
                "p": d.get("p"),
                "p_holm": d.get("p_holm"),
                "n": m.n,
            }
            row.update({k: v for k, v in extra.items() if not isinstance(v, (dict, list))})
            rows.append(row)
    return pd.DataFrame(rows)


def baseline_vs_panel(metrics: list[Metric]) -> pd.DataFrame:
    rows = []
    for m in metrics:
        if m.metric.startswith("cmp_"):
            d = m.detail
            rows.append(
                {
                    "metric": d.get("metric"),
                    "condition": m.condition,
                    "baseline_model": m.model,
                    "baseline": d.get("baseline"),
                    "panel_mean": d.get("panel_mean"),
                    "panel_min": d.get("panel_min"),
                    "panel_max": d.get("panel_max"),
                    "difference": m.value,
                    "panel_models": d.get("panel_models"),
                }
            )
    return pd.DataFrame(rows)


def position_effect(metrics: list[Metric]) -> pd.DataFrame:
    rows = []
    for m in metrics:
        if m.metric in ("position_t2_logit", "position_t3_ordinal"):
            d = m.detail
            rows.append(
                {
                    "model_set": m.model or "primary panel",
                    "outcome": "T2 correct (logit)"
                    if m.metric.endswith("logit")
                    else "T3 rating (ordered logit)",
                    "odds_ratio_per_position": m.value,
                    "odds_ratio_per_position_lo": m.ci_low,
                    "odds_ratio_per_position_hi": m.ci_high,
                    "p": d.get("p"),
                    "n": m.n,
                    "estimable": d.get("estimable"),
                    "reason": d.get("reason"),
                }
            )
        elif m.metric in ("position_t2_accuracy_tercile", "position_t3_mean_tercile"):
            rows.append(
                {
                    "model_set": m.model or "primary panel",
                    "outcome": "T2 accuracy by tercile"
                    if "accuracy" in m.metric
                    else "mean T3 rating by tercile",
                    "tercile": m.detail.get("tercile"),
                    "value": m.value,
                    "value_lo": m.ci_low,
                    "value_hi": m.ci_high,
                    "n": m.n,
                }
            )
    return pd.DataFrame(rows)


def grounding(session: Session, metrics: list[Metric]) -> pd.DataFrame:
    ix, models = _index(metrics), _models(session)
    rows = []
    for key, model in models.items():
        for cond in sorted({m.condition for m in metrics if m.metric == "claims_supported"}):
            sup = ix.get(("claims_supported", key, cond))
            if sup is None:
                continue
            row = {
                "model": key,
                "role": model.role,
                "condition": cond,
                "numeric_claims": sup.n,
                "claims_pending_annotation": sup.detail.get("pending_annotation"),
            }  # noqa: E501
            _put(row, "supported", sup)
            _put(row, "unsupported", ix.get(("claims_unsupported", key, cond)))
            _put(row, "wrong", ix.get(("claims_wrong", key, cond)))
            _put(row, "objective_error", ix.get(("taxonomy_objective_error", key, cond)))
            _put(
                row,
                "unsupported_claim_with_correct_t2",
                ix.get(("taxonomy_unsupported_claim", key, cond)),
            )
            rows.append(row)
    return pd.DataFrame(rows)


def parse_failure_table(session: Session) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model": r.model_key,
                "model_name": r.model_name,
                "runs": r.runs,
                "runs_with_invalid_first_reply": r.runs_not_ok_first,
                "runs_repaired": r.runs_repaired,
                "runs_still_invalid": r.runs_failed_final,
                "judgments": r.companies,
                "first_reply_failure_rate": r.first_attempt_rate,
                "final_failure_rate": r.final_rate,
                "failed_calls": r.call_failures,
            }
            for r in parse_rates(session)
        ]
    )


def run_counts(session: Session) -> pd.DataFrame:
    rows = session.execute(
        select(
            Model.key,
            Condition.code,
            Run.repetition,
            Run.is_repair,
            Run.mode,
            Run.status,
            func.count(),
        )
        .join(Model, Model.id == Run.model_id)
        .join(Condition, Condition.id == Run.condition_id)
        .where(Run.variant == "")
        .group_by(Model.key, Condition.code, Run.repetition, Run.is_repair, Run.mode, Run.status)
        .order_by(Model.key, Condition.code, Run.repetition)
    ).all()
    return pd.DataFrame(
        rows, columns=["model", "condition", "repetition", "is_repair", "mode", "status", "runs"]
    )


def all_tables(session: Session) -> dict[str, pd.DataFrame]:
    metrics = load_metrics(session)
    return {
        "scorecard": scorecard(session, metrics),
        "context_effects": context_effects(session, metrics),
        "agreement_between_models": agreement_between_models(metrics),
        "attribute_agreement": attribute_agreement(session, metrics),
        "hypotheses": hypothesis_summary(metrics),
        "hypothesis_tests": hypothesis_tests(metrics),
        "baseline_vs_panel": baseline_vs_panel(metrics),
        "position_effect": position_effect(metrics),
        "grounding": grounding(session, metrics),
        "parse_failure_rates": parse_failure_table(session),
        "run_counts": run_counts(session),
    }


def uses_mock_runs(session: Session) -> bool:
    return bool(session.scalar(select(func.count()).select_from(Run).where(Run.mode == "mock")))


# ---- Markdown ---------------------------------------------------------------------------------------
COUNT_COLUMNS = {
    "n", "k", "correct", "errors", "class_changed", "consistent", "violating", "unconstrained",
    "up", "down", "same", "resamples", "tercile", "runs", "judgments", "repetition",
    "failed_calls", "panel_models", "headline",
}  # fmt: skip


def _is_count(column: str) -> bool:
    prefixes = ("n_", "b_", "c_", "runs_", "numeric_", "claims_pending")
    return column in COUNT_COLUMNS or column.startswith(prefixes)


def _fmt(value, digits: int, count: bool = False) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if count and value == int(value):
            return str(int(value))
        if abs(value) < 1e-9:
            return f"{0:.{digits}f}"  # floating-point dust such as -1.1e-16
        return f"{value:.{digits}f}" if abs(value) >= 10**-digits else f"{value:.2e}"
    return str(value).replace("|", "/").replace("\n", " ")


def to_markdown(df: pd.DataFrame, digits: int = 3) -> str:
    """A GitHub-style table; `x`, `x_lo`, `x_hi` columns are merged into `x [lo, hi]`."""
    if df.empty:
        return "*(no rows)*"
    cols = list(df.columns)
    merged: dict[str, tuple[str, str]] = {
        c: (c + "_lo", c + "_hi") for c in cols if c + "_lo" in cols and c + "_hi" in cols
    }
    skip = {x for pair in merged.values() for x in pair}
    header = [c for c in cols if c not in skip]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for _, row in df.iterrows():
        cells = []
        for c in header:
            text = _fmt(row[c], digits, _is_count(c))
            if c in merged:
                lo, hi = (row[x] for x in merged[c])
                if text and not (pd.isna(lo) or pd.isna(hi)):
                    text += f" [{_fmt(lo, digits)}, {_fmt(hi, digits)}]"
            cells.append(text)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ---- sample and data quality (for the paper's data section) -----------------------------------------
def sample_description(session: Session, fy: str) -> pd.DataFrame:
    """One row per sector: companies by selection status, and the reporting boundary, assurance and
    entry method of the analysis-year reports."""
    from gauge.db.models import Company, Report, Sector

    rows = []
    for sector in session.scalars(select(Sector).order_by(Sector.name)):
        companies = list(session.scalars(select(Company).where(Company.sector_id == sector.id)))
        reports = list(
            session.scalars(
                select(Report)
                .join(Company, Company.id == Report.company_id)
                .where(Company.sector_id == sector.id, Report.fy == fy)
            )
        )
        included = [c for c in companies if c.selection_status == "included"]
        rows.append(
            {
                "sector": sector.name,
                "companies": len(companies),
                "included": len(included),
                "excluded": sum(c.selection_status == "excluded" for c in companies),
                "candidates": sum(c.selection_status == "candidate" for c in companies),
                "standalone": sum(r.boundary == "standalone" for r in reports),
                "consolidated": sum(r.boundary == "consolidated" for r in reports),
                "assured": sum(r.assured is True for r in reports),
                "assurance_not_stated": sum(r.assured is None for r in reports),
                "as_filed": sum(r.entry_method == "xbrl" for r in reports),
                "comparative_column": sum(r.entry_method == "xbrl_comparative" for r in reports),
            }
        )
    return pd.DataFrame(rows)


def selection_log(session: Session) -> pd.DataFrame:
    """Every excluded company with the reason (spec 4.1: log every exclusion)."""
    from gauge.db.models import Company, Sector

    rows = session.execute(
        select(Company.code, Sector.name, Company.selection_status, Company.exclusion_reason)
        .join(Sector, Sector.id == Company.sector_id)
        .where(Company.selection_status == "excluded")
        .order_by(Sector.name, Company.code)
    ).all()
    return pd.DataFrame(rows, columns=["code", "sector", "status", "reason"])


def data_quality(session: Session) -> pd.DataFrame:
    """Quality flags by rule and severity (flags never change data)."""
    from gauge.db.models import QualityFlag

    rows = session.execute(
        select(QualityFlag.rule, QualityFlag.severity, func.count())
        .group_by(QualityFlag.rule, QualityFlag.severity)
        .order_by(QualityFlag.severity, QualityFlag.rule)
    ).all()
    return pd.DataFrame(rows, columns=["rule", "severity", "flags"])


def verification_summary(session: Session) -> pd.DataFrame:
    """Outcome of the 10% verification sample: values confirmed, found wrong, not yet checked."""
    from gauge.db.models import IndicatorValue

    values = list(session.scalars(select(IndicatorValue.verified)))
    ok = sum(v is True for v in values)
    wrong = sum(v is False for v in values)
    checked = ok + wrong
    return pd.DataFrame(
        [
            {
                "values_in_database": len(values),
                "verified_ok": ok,
                "verified_error": wrong,
                "not_checked": len(values) - checked,
                "error_rate_among_checked": wrong / checked if checked else None,
            }
        ]
    )
