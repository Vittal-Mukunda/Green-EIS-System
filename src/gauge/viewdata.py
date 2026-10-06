"""Data access for the dashboard (spec §9): plain functions from a database session to data frames.

The dashboard reads from the database only; the single thing it writes is a human annotation. Keeping
these queries out of the Streamlit file means they can be tested without a browser.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from gauge import vocab
from gauge.config import IndicatorsConfig, StudyConfig
from gauge.db.models import (
    Annotation,
    Claim,
    Company,
    Condition,
    DisagreementFlag,
    IndicatorValue,
    Judgment,
    KpiValue,
    Model,
    QualityFlag,
    Report,
    Run,
    SdgMapping,
    Sector,
    SectorBenchmark,
)
from gauge.evaluate.frame import load_frame
from gauge.stats.primitives import NAN, cohen_kappa

SDG_CAPTION = vocab.SDG_CAPTION


# ---- companies and KPIs ---------------------------------------------------------------
@dataclass(frozen=True)
class CompanyRow:
    code: str
    sector: str
    real_name: str
    status: str
    synthetic: bool


def list_companies(session: Session) -> list[CompanyRow]:
    rows = session.execute(
        select(
            Company.code,
            Sector.name,
            Company.real_name,
            Company.selection_status,
            Company.is_synthetic,
        )
        .join(Sector, Sector.id == Company.sector_id)
        .order_by(Sector.name, Company.code)
    ).all()
    return [CompanyRow(*r) for r in rows]


def display_name(company: CompanyRow, real: bool) -> str:
    """The masked code, or (with the toggle) the code followed by the real name. Models only ever
    see codes; the real name is for the human reader of this dashboard."""
    return f"{company.code} ({company.real_name})" if real else company.code


def kpi_history(session: Session, code: str, indicators: IndicatorsConfig) -> pd.DataFrame:
    label = {k.code: (k.label, k.unit) for k in indicators.kpis}
    rows = session.execute(
        select(KpiValue.fy, KpiValue.kpi, KpiValue.value, KpiValue.change_2y_pct)
        .join(Company, Company.id == KpiValue.company_id)
        .where(Company.code == code)
        .order_by(KpiValue.kpi, KpiValue.fy)
    ).all()
    return pd.DataFrame(
        [
            {
                "fy": fy,
                "kpi": kpi,
                "label": label.get(kpi, (kpi, ""))[0],
                "unit": label.get(kpi, (kpi, ""))[1],
                "value": float(value),
                "change_2y_pct": None if change is None else float(change),
            }
            for fy, kpi, value, change in rows
        ],
        columns=["fy", "kpi", "label", "unit", "value", "change_2y_pct"],
    )


def indicator_table(
    session: Session, code: str, fy: str, indicators: IndicatorsConfig
) -> pd.DataFrame:
    label = {i.code: i for i in indicators.indicators}
    rows = session.execute(
        select(
            IndicatorValue.indicator,
            IndicatorValue.value,
            IndicatorValue.unit,
            IndicatorValue.verified,
        )
        .join(Report, Report.id == IndicatorValue.report_id)
        .join(Company, Company.id == Report.company_id)
        .where(Company.code == code, Report.fy == fy)
    ).all()
    return pd.DataFrame(
        [
            {
                "indicator": label[i].label if i in label else i,
                "value": float(v),
                "unit": u,
                "verified": verified,
            }
            for i, v, u, verified in sorted(
                rows, key=lambda r: list(label).index(r[0]) if r[0] in label else 99
            )
        ],
        columns=["indicator", "value", "unit", "verified"],
    )


def report_attributes(session: Session, code: str, fy: str) -> dict:
    report = session.scalar(
        select(Report)
        .join(Company, Company.id == Report.company_id)
        .where(Company.code == code, Report.fy == fy)
    )
    if report is None:
        return {}
    return {
        "boundary": report.boundary,
        "assured": report.assured,
        "entry_method": report.entry_method,
        "source_file": report.source_file,
        "retrieved_on": report.retrieved_on,
    }


def benchmark_position(
    session: Session, code: str, fy: str, indicators: IndicatorsConfig
) -> pd.DataFrame:
    """Where the company's KPI values sit against its sector's median, P25 and P75 (our own small
    sample): one row per KPI."""
    company = session.scalar(select(Company).where(Company.code == code))
    if company is None:
        return pd.DataFrame()
    values = {
        k.kpi: k.value
        for k in session.scalars(
            select(KpiValue).where(KpiValue.company_id == company.id, KpiValue.fy == fy)
        )
    }
    bench = {
        b.kpi: b
        for b in session.scalars(
            select(SectorBenchmark).where(
                SectorBenchmark.sector_id == company.sector_id, SectorBenchmark.fy == fy
            )
        )
    }
    rows = []
    for k in indicators.kpis:
        value, b = values.get(k.code), bench.get(k.code)
        rows.append(
            {
                "kpi": k.code,
                "label": k.label,
                "unit": k.unit,
                "better": k.better,
                "value": None if value is None else float(value),
                "p25": None if b is None else float(b.p25),
                "median": None if b is None else float(b.median),
                "p75": None if b is None else float(b.p75),
                "n_sector": None if b is None else b.n,
            }
        )
    return pd.DataFrame(rows)


def company_flags(session: Session, code: str) -> pd.DataFrame:
    rows = session.execute(
        select(
            QualityFlag.fy,
            QualityFlag.indicator,
            QualityFlag.rule,
            QualityFlag.severity,
            QualityFlag.message,
        )
        .join(Company, Company.id == QualityFlag.company_id)
        .where(Company.code == code)
        .order_by(QualityFlag.severity, QualityFlag.fy)
    ).all()
    return pd.DataFrame(rows, columns=["fy", "indicator", "rule", "severity", "message"])


def sdg_relevance(session: Session, indicators: IndicatorsConfig) -> pd.DataFrame:
    names = {i.code: i.label for i in indicators.indicators} | {
        k.code: k.label for k in indicators.kpis
    }
    rows = session.scalars(
        select(SdgMapping).order_by(SdgMapping.sdg_number, SdgMapping.indicator_code)
    )
    return pd.DataFrame(
        [
            {
                "indicator": names.get(r.indicator_code, r.indicator_code),
                "sdg": r.sdg_number,
                "target": r.sdg_target,
                "source": r.source,
            }
            for r in rows
        ],
        columns=["indicator", "sdg", "target", "source"],
    )


# ---- judgments and flags ---------------------------------------------------------------
def judgments_for_company(session: Session, code: str) -> pd.DataFrame:
    """Every model's output for one company, both conditions and repetitions, side by side."""
    frame = load_frame(session)
    mine = frame[frame["company_code"] == code].copy()
    if mine.empty:
        return mine
    mine["drivers"] = mine["top_drivers"].map(lambda d: "; ".join(d) if isinstance(d, list) else "")
    return mine.sort_values(["condition", "repetition", "model_key"])[
        ["model_key", "role", "condition", "repetition", "valid", "t2_class", "t3_rating", "t3_confidence",
         "drivers", "justification", "insufficient_evidence", "position"]
    ]  # fmt: skip


def disagreement_queue(session: Session) -> pd.DataFrame:
    model_key = {m.id: m.key for m in session.scalars(select(Model))}
    condition = {c.id: c.code for c in session.scalars(select(Condition))}
    rows = session.execute(
        select(DisagreementFlag, Company.code)
        .join(Company, Company.id == DisagreementFlag.company_id)
        .order_by(DisagreementFlag.flag_type, Company.code, DisagreementFlag.repetition)
    ).all()
    return pd.DataFrame(
        [
            {
                "flag_id": f.id,
                "type": f.flag_type,
                "company": code,
                "condition": condition.get(f.condition_id),
                "model": model_key.get(f.model_id),
                "repetition": f.repetition,
                "detail": ", ".join(f"{k}={v}" for k, v in (f.detail or {}).items()),
            }
            for f, code in rows
        ],
        columns=["flag_id", "type", "company", "condition", "model", "repetition", "detail"],
    )


# ---- annotation ---------------------------------------------------------------
class AnnotationError(ValueError):
    """An annotation that cannot be stored (unknown label, missing target)."""


def claims_to_annotate(
    session: Session, annotator: str, *, include_done: bool = False
) -> pd.DataFrame:
    """Claims a human should check: those the rules could not settle (non-numeric) and every numeric
    claim labelled wrong or unsupported. Excludes what `annotator` has already labelled."""
    done = set(
        session.scalars(
            select(Annotation.claim_id).where(
                Annotation.annotator == annotator, Annotation.kind == "claim_support"
            )
        )
    )
    rows = session.execute(
        select(Claim, Judgment, Run.run_id, Company.code, Model.key, Condition.code)
        .join(Judgment, Judgment.id == Claim.judgment_id)
        .join(Run, Run.id == Judgment.run_id)
        .join(Company, Company.id == Judgment.company_id)
        .join(Model, Model.id == Run.model_id)
        .join(Condition, Condition.id == Run.condition_id)
        .where(Claim.status.in_(["pending_annotation", "unsupported", "wrong"]))
        .order_by(Claim.id)
    ).all()
    out = [
        {
            "claim_id": c.id, "judgment_id": c.judgment_id, "company": code, "model": mk,
            "condition": cond, "run_id": run_id, "clause": c.clause_text, "automatic_status": c.status,
            "indicator": c.indicator_code,
        }
        for c, j, run_id, code, mk, cond in rows
        if include_done or c.id not in done
    ]  # fmt: skip
    return pd.DataFrame(
        out,
        columns=["claim_id", "judgment_id", "company", "model", "condition", "run_id", "clause",
                 "automatic_status", "indicator"],
    )  # fmt: skip


def judgments_for_taxonomy(
    session: Session, annotator: str, truth: Mapping[str, str], *, include_done: bool = False
) -> pd.DataFrame:
    """Judgments to classify with the four-way error taxonomy, each with the automatic suggestion:
    a wrong T2 class (objective error), a right class with an unsupported or wrong numeric claim
    (unsupported claim), or a judgment in a company/condition/repetition where the primary models
    disagree on T2. The two human-only categories (interpretation difference, legitimate ambiguity)
    can only be assigned here."""
    done = set(
        session.scalars(
            select(Annotation.judgment_id).where(
                Annotation.annotator == annotator,
                Annotation.kind == "taxonomy",
                Annotation.claim_id.is_(None),
            )
        )
    )
    columns = ["judgment_id", "company", "model", "condition", "repetition", "t2_class", "rule_class",
               "automatic_suggestion", "justification"]  # fmt: skip
    frame = load_frame(session)
    ok = frame[frame["valid"]].copy()
    if ok.empty:
        return pd.DataFrame(columns=columns)
    bad_claims = set(
        session.scalars(
            select(Claim.judgment_id).where(
                Claim.status.in_(["unsupported", "wrong"]), Claim.claim_type == "numeric"
            )
        )
    )
    code_of = {c.id: c.code for c in session.scalars(select(Company))}
    condition_of = {c.id: c.code for c in session.scalars(select(Condition))}
    disputed = {
        (code_of[f.company_id], condition_of.get(f.condition_id), f.repetition)
        for f in session.scalars(
            select(DisagreementFlag).where(DisagreementFlag.flag_type == "t2_models_disagree")
        )
    }
    rows = []
    for r in ok.itertuples():
        rule_class = truth.get(r.company_code)
        if rule_class is not None and r.t2_class != rule_class:
            why = "objective_error"
        elif r.judgment_id in bad_claims:
            why = "unsupported_claim"
        elif r.role == "primary" and (r.company_code, r.condition, r.repetition) in disputed:
            why = "models_disagree"
        else:
            continue
        if not include_done and r.judgment_id in done:
            continue
        rows.append(
            {
                "judgment_id": int(r.judgment_id), "company": r.company_code, "model": r.model_key,
                "condition": r.condition, "repetition": int(r.repetition), "t2_class": r.t2_class,
                "rule_class": rule_class, "automatic_suggestion": why, "justification": r.justification,
            }
        )  # fmt: skip
    return pd.DataFrame(rows, columns=columns)


def save_annotation(
    session: Session,
    *,
    annotator: str,
    kind: str,
    label: str,
    claim_id: int | None = None,
    judgment_id: int | None = None,
    note: str | None = None,
) -> Annotation:
    """Insert or update one annotator's label for a claim (claim_support) or a judgment (taxonomy)."""
    allowed = vocab.CLAIM_SUPPORT_LABELS if kind == "claim_support" else vocab.TAXONOMY_LABELS
    if kind not in vocab.ANNOTATION_KINDS:
        raise AnnotationError(f"unknown annotation kind {kind!r}")
    if label not in allowed:
        raise AnnotationError(f"{label!r} is not a {kind} label: {allowed}")
    if not annotator.strip():
        raise AnnotationError("annotator name is required")
    if claim_id is None and judgment_id is None:
        raise AnnotationError("an annotation needs a claim or a judgment")
    if kind == "claim_support" and claim_id is None:
        raise AnnotationError("claim_support annotations target a claim")
    if kind == "taxonomy" and (judgment_id is None or claim_id is not None):
        raise AnnotationError("taxonomy annotations target a judgment")
    if claim_id is not None and judgment_id is None:
        judgment_id = session.scalar(select(Claim.judgment_id).where(Claim.id == claim_id))
    query = select(Annotation).where(Annotation.annotator == annotator, Annotation.kind == kind)
    query = (
        query.where(Annotation.claim_id == claim_id)
        if claim_id is not None
        else query.where(Annotation.judgment_id == judgment_id, Annotation.claim_id.is_(None))
    )
    row = session.scalar(query)
    if row is None:
        row = Annotation(
            annotator=annotator, kind=kind, claim_id=claim_id, judgment_id=judgment_id, label=label
        )
        session.add(row)
    row.label, row.note = label, note
    session.flush()
    return row


def annotator_agreement(session: Session, kind: str) -> dict:
    """Cohen's kappa between the two annotators with the most labels of `kind`, over targets both labelled."""
    rows = list(session.scalars(select(Annotation).where(Annotation.kind == kind)))
    names = sorted({r.annotator for r in rows}, key=lambda n: -sum(r.annotator == n for r in rows))
    if len(names) < 2:
        return {"annotators": names, "n_both": 0, "kappa": NAN, "agreement": NAN}
    a_name, b_name = names[:2]

    def key(r: Annotation):
        return ("claim", r.claim_id) if r.claim_id is not None else ("judgment", r.judgment_id)

    first = {key(r): r.label for r in rows if r.annotator == a_name}
    second = {key(r): r.label for r in rows if r.annotator == b_name}
    shared = sorted(set(first) & set(second))
    a = [first[k] for k in shared]
    b = [second[k] for k in shared]
    return {
        "annotators": [a_name, b_name],
        "n_both": len(shared),
        "kappa": cohen_kappa(a, b) if shared else NAN,
        "agreement": sum(x == y for x, y in zip(a, b, strict=True)) / len(shared)
        if shared
        else NAN,
    }


# ---- audit trail ---------------------------------------------------------------
def audit_runs(session: Session) -> pd.DataFrame:
    rows = session.execute(
        select(
            Run.run_id, Model.key, Model.name, Condition.code, Run.repetition, Run.mode, Run.is_repair,
            Run.status, Run.parse_status, Run.cli_version, Run.started_utc, Run.finished_utc,
            Run.duration_s, Run.exit_code, Run.prompt_sha256, Run.seed,
        )
        .join(Model, Model.id == Run.model_id)
        .join(Condition, Condition.id == Run.condition_id)
        .order_by(Run.started_utc, Run.run_id)
    ).all()  # fmt: skip
    return pd.DataFrame(
        rows,
        columns=["run_id", "model", "model_name", "condition", "repetition", "mode", "is_repair", "status",
                 "parse_status", "cli_version", "started_utc", "finished_utc", "duration_s", "exit_code",
                 "prompt_sha256", "seed"],
    )  # fmt: skip


def run_detail(session: Session, run_id: str) -> dict | None:
    run = session.scalar(select(Run).where(Run.run_id == run_id))
    if run is None:
        return None
    return {
        "run_id": run.run_id,
        "command": run.command,
        "prompt_sha256": run.prompt_sha256,
        "system_prompt_sha256": run.system_prompt_sha256,
        "prompt_text": run.prompt_text,
        "system_prompt_text": run.system_prompt_text,
        "stdout": run.stdout,
        "stderr": run.stderr,
        "temperature": run.temperature,
        "provider_model": run.provider_model,
        "request_json": run.request_json,
        "rate_limit_headers": run.rate_limit_headers,
    }


def search_runs(df: pd.DataFrame, text: str) -> pd.DataFrame:
    """Case-insensitive substring search over every column of the audit table."""
    if not text.strip():
        return df
    needle = text.strip().lower()
    mask = (
        df.astype(str)
        .apply(lambda col: col.str.lower().str.contains(needle, regex=False))
        .any(axis=1)
    )
    return df[mask]


def evidence_markdown(
    session: Session, cfg: StudyConfig, indicators: IndicatorsConfig, code: str, condition: str
) -> str:
    """What the models were shown for this company under `condition` (rendered from the database)."""
    from gauge.render.evidence import load_evidence
    from gauge.render.prompts import company_block, context_block

    evidence = load_evidence(session, cfg, indicators)
    ce = evidence.companies[code]
    text = company_block(ce, indicators, evidence.analysis_fy)
    if condition == "C2":
        text += "\n\n" + context_block(ce, evidence, indicators)
    return text


# ---- EIS views: overview, exceptions, filings, verification ------------------------------
class VerificationError(ValueError):
    """A verification that cannot be stored (unknown value, missing reviewer or reason)."""


def headline_counts(session: Session) -> dict[str, int]:
    """Size of the evidence base, for the overview's headline figures."""

    def count(column, *where) -> int:
        return session.scalar(select(func.count(column)).where(*where)) or 0

    return {
        "companies": count(Company.id),
        "filings": count(Report.id),
        "indicator values": count(IndicatorValue.id),
        "KPI values": count(KpiValue.id),
        "errors": count(QualityFlag.id, QualityFlag.severity == "error"),
        "warnings": count(QualityFlag.id, QualityFlag.severity == "warning"),
        "values checked by a person": count(IndicatorValue.id, IndicatorValue.verified.isnot(None)),
    }


def flag_register(session: Session) -> pd.DataFrame:
    """Every data-quality flag for every company: the exception report."""
    rows = session.execute(
        select(
            Company.code,
            Sector.name,
            QualityFlag.fy,
            QualityFlag.indicator,
            QualityFlag.rule,
            QualityFlag.severity,
            QualityFlag.message,
        )
        .join(Company, Company.id == QualityFlag.company_id)
        .join(Sector, Sector.id == Company.sector_id)
        .order_by(QualityFlag.severity, QualityFlag.rule, Company.code, QualityFlag.fy)
    ).all()
    return pd.DataFrame(
        rows, columns=["code", "sector", "fy", "indicator", "rule", "severity", "message"]
    )


def filings_register(session: Session) -> pd.DataFrame:
    """One row per filing loaded, with its provenance (file, SHA-256, date retrieved)."""
    checked = func.sum(case((IndicatorValue.verified.isnot(None), 1), else_=0))
    rows = session.execute(
        select(
            Company.code,
            Sector.name,
            Report.fy,
            Report.entry_method,
            Report.boundary,
            Report.assured,
            Report.source_file,
            Report.file_sha256,
            Report.retrieved_on,
            func.count(IndicatorValue.id),
            checked,
        )
        .join(Company, Company.id == Report.company_id)
        .join(Sector, Sector.id == Company.sector_id)
        .outerjoin(IndicatorValue, IndicatorValue.report_id == Report.id)
        .group_by(Report.id)
        .order_by(Sector.name, Company.code, Report.fy)
    ).all()
    return pd.DataFrame(
        [(*r[:9], r[9], int(r[10] or 0)) for r in rows],
        columns=[
            "code",
            "sector",
            "fy",
            "entry method",
            "boundary",
            "assured",
            "source file",
            "SHA-256",
            "retrieved on",
            "values",
            "checked",
        ],
    )


LINEAGE_COLUMNS = [
    "item_id",
    "indicator",
    "value",
    "unit",
    "as filed",
    "as-filed unit",
    "source element",
    "review",
]


def indicator_lineage(
    session: Session, code: str, fy: str, indicators: IndicatorsConfig
) -> pd.DataFrame:
    """Each stored value beside what the filing stated, the element it came from, and whether a
    person has checked it against the filing."""
    label = {i.code: i.label for i in indicators.indicators}
    rows = session.execute(
        select(
            IndicatorValue.id,
            IndicatorValue.indicator,
            IndicatorValue.value,
            IndicatorValue.unit,
            IndicatorValue.original_value,
            IndicatorValue.original_unit,
            IndicatorValue.page_ref,
            IndicatorValue.verified,
            IndicatorValue.verification_note,
        )
        .join(Report, Report.id == IndicatorValue.report_id)
        .join(Company, Company.id == Report.company_id)
        .where(Company.code == code, Report.fy == fy)
    ).all()
    order = list(label)
    rows = sorted(rows, key=lambda r: order.index(r[1]) if r[1] in order else len(order))

    def review(verified: bool | None, note: str | None) -> str:
        status = "not yet checked" if verified is None else ("ok" if verified else "error")
        return f"{status}: {note}" if note else status

    return pd.DataFrame(
        [
            (
                item_id,
                label.get(indicator, indicator),
                float(value),
                unit,
                None if original is None else float(original),
                original_unit,
                element,
                review(verified, note),
            )
            for item_id, indicator, value, unit, original, original_unit, element, verified, note in rows
        ],
        columns=LINEAGE_COLUMNS,
    )


def record_verification(
    session: Session, *, item_id: int, reviewer: str, result: str, note: str | None = None
) -> None:
    """Record a person's check of one stored value against its filing (the same fields that
    `gauge verify-sample --record` fills). The note always carries who decided and when."""
    if result not in ("ok", "error"):
        raise VerificationError(f"result must be ok or error, got {result!r}")
    reviewer = (reviewer or "").strip()
    if not reviewer:
        raise VerificationError("enter your name so the decision can be traced")
    note = (note or "").strip()
    if result == "error" and not note:
        raise VerificationError("say what is wrong with the value")
    iv = session.get(IndicatorValue, item_id)
    if iv is None:
        raise VerificationError(f"no stored value with id {item_id}")
    stamp = f"checked by {reviewer} via the dashboard on {datetime.now(UTC).date().isoformat()}"
    iv.verified = result == "ok"
    iv.verification_note = f"{note} ({stamp})" if note else stamp
    session.flush()


def kpi_years(session: Session) -> list[str]:
    """The fiscal years that have KPI values, oldest first."""
    return list(session.scalars(select(KpiValue.fy).distinct().order_by(KpiValue.fy)))


# What each data-quality rule checks, in plain words (for the exception report).
RULE_NOTES: dict[str, str] = {
    "non_negative": "an indicator is negative",
    "renewable_le_total": "renewable energy exceeds total energy",
    "recovered_le_generated": "waste recovered exceeds waste generated",
    "consumption_le_withdrawal": "water consumed exceeds water withdrawn",
    "change_2y_gt_60pct": "a KPI moved by more than 60 percent over two years",
    "boundary_change": "the reporting boundary changed between years",
    "boundary_missing": "the filing does not state its reporting boundary",
    "missing_indicator": "no filing is loaded for this company and year",
    "nonpositive_denominator": "revenue is zero or negative, so intensities cannot be computed",
    "zero_waste_generated": "waste generated is zero, so the recovery rate is undefined",
    "xbrl_override_applied": "an XBRL unit label was replaced using evidence from the PDF filing",
    "xbrl_intensity_mismatch": "an absolute figure disagrees with the filing's own intensity",
    "xbrl_scale_break": "a value jumps by orders of magnitude between years in one filing",
    "xbrl_restatement": "a prior-year figure differs between two filings (restated)",
}


# ---- interpretation: position bands, movement, readings, scenarios -----------------------------
BANDS = ("better third", "middle third", "weaker third")
NO_BAND = "n/a"  # fewer than three companies: a position says nothing
BAND_FLAT = "no clear difference"  # the compared values are nearly identical: a rank means little
MIN_FOR_BAND = 3
NEGLIGIBLE_SPREAD_PCT = 1.0  # sector values within 1% of their median are treated as the same
MOVEMENT_TOLERANCE_PCT = 1.0  # a year-on-year change under 1% is "about the same"


def band_for(rank: int, n: int) -> str:
    """Which part of a sector sample a rank falls in (1 = best): the better third, the middle or the
    weaker third. Thirds are by rank and round up, so 5 companies give 2 / 1 / 2 and 4 give 2 / 0 / 2.
    A description of the sample at hand, not a classification rule."""
    if n < MIN_FOR_BAND:
        return NO_BAND
    k = -(-n // 3)
    if rank <= k:
        return BANDS[0]
    if rank > n - k:
        return BANDS[2]
    return BANDS[1]


def _rank_among(values: Mapping[str, float], code: str, better: str) -> int:
    """Rank of `code` among `values` (1 = best); a tie shares the better rank."""
    mine = values[code]
    ahead = sum(1 for v in values.values() if (v < mine if better == "lower" else v > mine))
    return ahead + 1


def rank_after_change(
    values: Mapping[str, float], code: str, new_value: float, better: str
) -> tuple[int, int, str]:
    """Rank, sample size and band of `code` if only its value became `new_value`."""
    changed = {**values, code: new_value}
    rank = _rank_among(changed, code, better)
    return rank, len(changed), band_for(rank, len(changed))


def fmt_number(value: float) -> str:
    """A number a person can read at a glance: separators, 3 to 4 significant figures, and never
    scientific notation."""
    if pd.isna(value):
        return "n/a"
    size = abs(value)
    if size >= 1000:
        return f"{value:,.0f}"
    if size >= 100:
        return f"{value:.0f}"
    if size >= 10:
        return f"{value:.1f}"
    if size >= 1:
        return f"{value:.2f}"
    if size >= 0.01:
        return f"{value:.3f}"
    return f"{value:.2g}"


def _signed_pct(change: float) -> str:
    """+1.5% / -2.0%, never "-0.0%"."""
    return f"{round(change, 1) + 0.0:+.1f}%"


def _movement(change: float, lower_is_better: bool) -> str:
    if pd.isna(change):
        return "n/a"
    if abs(change) < MOVEMENT_TOLERANCE_PCT:
        return "about the same"
    return "better" if (change < 0) == lower_is_better else "worse"


DATA_CHECK = (
    "data check"  # the figure failed a data-quality error check, so it is shown, not ranked
)

OVERVIEW_COLUMNS = [
    "code",
    "sector",
    "value",
    "rank in sector",
    "companies compared",
    "band",
    "previous year",
    "change %",
    "movement",
    "sector median",
    "vs sector median",
    "data check",
]


# Rules of the form "a part cannot exceed its whole": (the part, the whole). A breach this small
# (1%) is treated as rounding when deciding whether to rank a figure; it is still flagged everywhere.
PART_OF_WHOLE = {
    "recovered_le_generated": ("waste_recovered", "waste_generated"),
    "consumption_le_withdrawal": ("water_consumption", "water_withdrawal"),
    "renewable_le_total": ("energy_renewable", "energy_total"),
}
ROUNDING_BREACH = 0.01


def _flagged_kpis(
    session: Session, indicators: IndicatorsConfig
) -> dict[tuple[str, str, str], set]:
    """(company, year, KPI) -> the error rules that touched an indicator the KPI is computed from.
    A figure that fails an impossibility check (recovered waste above generated waste, say) must not
    be ranked as if it were sound. A part that exceeds its whole by less than 1% is treated as
    rounding and does not stop a figure being ranked."""
    rows = session.execute(
        select(Company.code, QualityFlag.fy, QualityFlag.indicator, QualityFlag.rule)
        .join(Company, Company.id == QualityFlag.company_id)
        .where(
            QualityFlag.severity == "error",
            QualityFlag.rule != "missing_indicator",
            QualityFlag.indicator.isnot(None),
            QualityFlag.fy.isnot(None),
        )
    ).all()
    needed = {i for pair in PART_OF_WHOLE.values() for i in pair}
    values = {
        (code, fy, indicator): float(value)
        for code, fy, indicator, value in session.execute(
            select(Company.code, Report.fy, IndicatorValue.indicator, IndicatorValue.value)
            .join(Report, Report.company_id == Company.id)
            .join(IndicatorValue, IndicatorValue.report_id == Report.id)
            .where(IndicatorValue.indicator.in_(needed))
        )
    }
    flagged: dict[tuple[str, str, str], set] = {}
    for code, fy, indicator, rule in rows:
        if rule in PART_OF_WHOLE:
            part, whole = (values.get((code, fy, name)) for name in PART_OF_WHOLE[rule])
            if part is not None and whole and (part - whole) / whole < ROUNDING_BREACH:
                continue
        for spec in indicators.kpis:
            if re.search(rf"\b{re.escape(indicator)}\b", spec.formula):
                flagged.setdefault((code, fy, spec.code), set()).add(rule)
    return flagged


def _kpi_by_year(session: Session, kpi_code: str) -> list:
    """Every stored value of one KPI: company code, sector id, sector name, fiscal year, value."""
    return session.execute(
        select(Company.code, Sector.id, Sector.name, KpiValue.fy, KpiValue.value)
        .join(Sector, Sector.id == Company.sector_id)
        .join(KpiValue, KpiValue.company_id == Company.id)
        .where(KpiValue.kpi == kpi_code)
    ).all()


def sector_overview(
    session: Session, fy: str, kpi_code: str, indicators: IndicatorsConfig
) -> pd.DataFrame:
    """One KPI for every company in one year, ranked within its own sector (never across sectors:
    the sectors' intensities are not comparable). Rank 1 is the best, using the KPI's direction.

    Only figures that pass the data-quality error checks are ranked and enter the sector median; the
    rest show `data check` instead of a position. `change %` is against the company's latest earlier
    year that is loaded, and is left empty when either year fails a check."""
    spec = next(k for k in indicators.kpis if k.code == kpi_code)
    lower_is_better = spec.better == "lower"
    history = _kpi_by_year(session, kpi_code)
    current = [r for r in history if r[3] == fy]
    if not current:
        return pd.DataFrame(columns=OVERVIEW_COLUMNS)
    flagged = _flagged_kpis(session, indicators)
    years_of: dict[str, dict[str, float]] = {}
    for code, _sector_id, _sector, year, value in history:
        years_of.setdefault(code, {})[year] = float(value)
    rows = []
    for code, _sector_id, sector, _fy, value in current:
        value = float(value)
        rules = flagged.get((code, fy, kpi_code), set())
        earlier = [y for y in years_of[code] if y < fy]
        previous = float("nan")
        if earlier and (code, max(earlier), kpi_code) not in flagged:
            previous = years_of[code][max(earlier)]
        change = float("nan")
        if not rules and previous and not pd.isna(previous):
            change = (value - previous) / previous * 100
        rows.append(
            {
                "code": code,
                "sector": sector,
                "value": value,
                "previous year": previous,
                "change %": change,
                "movement": _movement(change, lower_is_better),
                "data check": ", ".join(sorted(rules)),
            }
        )
    frame = pd.DataFrame(rows)
    clean = frame[frame["data check"] == ""]
    frame["rank in sector"] = (
        clean.groupby("sector")["value"]
        .rank(method="min", ascending=lower_is_better)
        .reindex(frame.index)
        .astype("Int64")
    )
    compared = clean.groupby("sector")["code"].size()
    frame["companies compared"] = frame["sector"].map(compared).fillna(0).astype(int)
    frame["band"] = [
        DATA_CHECK if check else band_for(int(rank), n)
        for check, rank, n in zip(
            frame["data check"],
            frame["rank in sector"].fillna(0),
            frame["companies compared"],
            strict=True,
        )
    ]
    median = clean.groupby("sector")["value"].median().where(compared >= MIN_FOR_BAND)
    frame["sector median"] = frame["sector"].map(median)
    extent = clean.groupby("sector")["value"].agg(lambda v: v.max() - v.min())
    flat = set(
        median.index[(median.abs() > 0) & (extent / median.abs() * 100 < NEGLIGIBLE_SPREAD_PCT)]
    )
    frame["band"] = [
        BAND_FLAT if band in BANDS and sector in flat else band
        for band, sector in zip(frame["band"], frame["sector"], strict=True)
    ]

    def versus(row: pd.Series) -> str:
        if row["data check"] or pd.isna(row["sector median"]):
            return "n/a"
        if row["value"] == row["sector median"]:
            return "at median"
        lower = row["value"] < row["sector median"]
        return "better" if lower == lower_is_better else "worse"

    frame["vs sector median"] = frame.apply(versus, axis=1)
    frame["_rank"] = frame["rank in sector"].fillna(10**6)
    frame = frame.sort_values(["sector", "_rank", "code"])
    return frame[OVERVIEW_COLUMNS].reset_index(drop=True)


def kpi_matrix(session: Session, fy: str, indicators: IndicatorsConfig) -> pd.DataFrame:
    """Every KPI for every company in one year, in long form, with its within-sector position."""
    parts = []
    for spec in indicators.kpis:
        frame = sector_overview(session, fy, spec.code, indicators)
        if frame.empty:
            continue
        parts.append(
            frame.assign(
                kpi=spec.code, label=spec.label, unit=pretty_unit(spec.unit), better=spec.better
            )
        )
    columns = [*OVERVIEW_COLUMNS, "kpi", "label", "unit", "better"]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)


def kpi_over_time(session: Session, kpi_code: str) -> pd.DataFrame:
    """One KPI for every company in every year loaded (for the sector trend lines)."""
    rows = _kpi_by_year(session, kpi_code)
    frame = pd.DataFrame(
        [
            {"code": code, "sector": sector, "fy": year, "value": float(value)}
            for code, _sector_id, sector, year, value in rows
        ],
        columns=["code", "sector", "fy", "value"],
    )
    return frame.sort_values(["sector", "code", "fy"]).reset_index(drop=True)


def data_as_of(session: Session) -> dict:
    """The most recent fiscal year loaded and the latest date a filing was retrieved."""
    return {
        "latest_fy": session.scalar(select(func.max(Report.fy))),
        "retrieved_on": session.scalar(select(func.max(Report.retrieved_on))),
    }


# ---- trust in the numbers ---------------------------------------------------------------------
def flag_counts(session: Session, fy: str) -> dict[str, dict[str, int]]:
    """Per company, the number of error and warning flags for one year (and company-wide flags)."""
    rows = session.execute(
        select(Company.code, QualityFlag.severity, func.count(QualityFlag.id))
        .join(Company, Company.id == QualityFlag.company_id)
        .where((QualityFlag.fy == fy) | QualityFlag.fy.is_(None))
        .group_by(Company.code, QualityFlag.severity)
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for code, severity, n in rows:
        counts.setdefault(code, {"errors": 0, "warnings": 0})[
            "errors" if severity == "error" else "warnings"
        ] = n
    return counts


ENTRY_NOTES = {
    "xbrl": "the filing's own XBRL",
    "xbrl_comparative": "the prior-year column of a later filing (as restated by the company)",
    "manual": "manual entry",
    "synthetic": "synthetic data",
}


def evidence_quality(session: Session, code: str, fy: str) -> dict:
    """How far one company's year can be trusted: flags, values a person has checked, and what the
    filing states about its own boundary and assurance."""
    counts = flag_counts(session, fy).get(code, {})
    report = session.scalar(
        select(Report)
        .join(Company, Company.id == Report.company_id)
        .where(Company.code == code, Report.fy == fy)
    )
    total = checked = 0
    if report is not None:
        total, checked = session.execute(
            select(
                func.count(IndicatorValue.id),
                func.sum(case((IndicatorValue.verified.isnot(None), 1), else_=0)),
            ).where(IndicatorValue.report_id == report.id)
        ).one()
    return {
        "errors": counts.get("errors", 0),
        "warnings": counts.get("warnings", 0),
        "values": total or 0,
        "checked": int(checked or 0),
        "assured": None if report is None else report.assured,
        "boundary": None if report is None else report.boundary,
        "entry_method": None if report is None else report.entry_method,
        "filing": report is not None,
    }


def evidence_sentence(quality: dict) -> str:
    if not quality["filing"]:
        return "no filing is loaded for this year."
    assurance = {True: "assured", False: "not assured", None: "assurance not stated"}[
        quality["assured"]
    ]
    return (
        f"{quality['errors']} error and {quality['warnings']} warning flags; "
        f"{quality['checked']} of {quality['values']} values checked by a person; {assurance}; "
        f"reporting boundary {quality['boundary'] or 'not stated'}; read from "
        f"{ENTRY_NOTES.get(quality['entry_method'], quality['entry_method'])}."
    )


def reviewer_notes(session: Session, code: str, indicators: IndicatorsConfig) -> pd.DataFrame:
    """The notes people have recorded against this company's values (soft information)."""
    label = {i.code: i.label for i in indicators.indicators}
    rows = session.execute(
        select(
            Report.fy,
            IndicatorValue.indicator,
            IndicatorValue.verified,
            IndicatorValue.verification_note,
        )
        .join(Report, Report.id == IndicatorValue.report_id)
        .join(Company, Company.id == Report.company_id)
        .where(Company.code == code, IndicatorValue.verification_note.isnot(None))
        .order_by(Report.fy, IndicatorValue.indicator)
    ).all()
    return pd.DataFrame(
        [
            {
                "fy": fy,
                "indicator": label.get(indicator, indicator),
                "result": "ok" if verified else "error",
                "note": note,
            }
            for fy, indicator, verified, note in rows
        ],
        columns=["fy", "indicator", "result", "note"],
    )


# ---- management by exception ------------------------------------------------------------------
def attention_list(
    session: Session, fy: str, indicators: IndicatorsConfig, worsening_pct: float = 10.0
) -> pd.DataFrame:
    """What needs a look first: companies with data-quality errors, then KPIs that moved the wrong
    way by at least `worsening_pct` against the previous year (largest moves first)."""
    rows = []
    errors = session.execute(
        select(Company.code, Sector.name, QualityFlag.rule)
        .join(Company, Company.id == QualityFlag.company_id)
        .join(Sector, Sector.id == Company.sector_id)
        .where(
            QualityFlag.severity == "error",
            (QualityFlag.fy == fy) | QualityFlag.fy.is_(None),
        )
    ).all()
    by_company: dict[str, tuple[str, set[str]]] = {}
    for code, sector, rule in errors:
        by_company.setdefault(code, (sector, set()))[1].add(rule)
    for code, (sector, rules) in sorted(by_company.items()):
        rows.append(
            {
                "kind": "data",
                "code": code,
                "sector": sector,
                "item": "data-quality errors",
                "detail": "; ".join(f"{r}: {RULE_NOTES.get(r, r)}" for r in sorted(rules)),
                "size": float("inf"),
            }
        )
    matrix = kpi_matrix(session, fy, indicators)
    if not matrix.empty:
        worse = matrix[
            (matrix["movement"] == "worse") & (matrix["change %"].abs() >= worsening_pct)
        ]
        for r in worse.to_dict("records"):
            rows.append(
                {
                    "kind": "movement",
                    "code": r["code"],
                    "sector": r["sector"],
                    "item": r["label"],
                    "detail": (
                        f"worsened by {abs(r['change %']):.1f}% against the previous year "
                        f"({fmt_number(r['previous year'])} to {fmt_number(r['value'])} {r['unit']})"
                    ),
                    "size": abs(r["change %"]),
                }
            )
    frame = pd.DataFrame(rows, columns=["kind", "code", "sector", "item", "detail", "size"])
    frame = frame.sort_values("size", ascending=False, kind="stable")  # data errors have size inf
    return frame[["kind", "code", "sector", "item", "detail"]].reset_index(drop=True)


# ---- plain-language reading and scenarios -----------------------------------------------------
def company_reading(
    session: Session, code: str, fy: str, indicators: IndicatorsConfig
) -> list[str]:
    """A company's year in plain sentences, generated from the figures by fixed templates."""
    matrix = kpi_matrix(session, fy, indicators)
    records = matrix[matrix["code"] == code].to_dict("records")
    if not records:
        return []
    lines = []
    for r in records:
        head = f"{r['label']}: {fmt_number(r['value'])} {r['unit']}"
        if r["band"] == DATA_CHECK:
            lines.append(
                f"{head}; not ranked, because it fails a data-quality check ({r['data check']})."
            )
            continue
        if r["band"] == NO_BAND:
            position = f"only {r['companies compared']} compared in {r['sector']}, too few to place"
        elif r["band"] == BAND_FLAT:
            position = (
                f"rank {r['rank in sector']} of {r['companies compared']} in {r['sector']} (1 = best), "
                "but the sector's values are almost identical, so the rank carries little weight"
            )
        else:
            position = (
                f"rank {r['rank in sector']} of {r['companies compared']} in {r['sector']} "
                f"(1 = best), {r['band']}"
            )
        if pd.isna(r["change %"]):
            movement = ""
        elif r["movement"] == "about the same":
            movement = f"; about the same as the previous year ({_signed_pct(r['change %'])})"
        else:
            way = "lower" if r["change %"] < 0 else "higher"
            movement = f"; {abs(r['change %']):.1f}% {way} than the previous year ({r['movement']})"
        lines.append(f"{head}; {position}{movement}.")
    strong = [r["label"] for r in records if r["band"] == BANDS[0]]
    weak = [r["label"] for r in records if r["band"] == BANDS[2]]
    if strong:
        lines.append("Better third of its sector sample on: " + ", ".join(strong) + ".")
    if weak:
        lines.append("Weaker third of its sector sample on: " + ", ".join(weak) + ".")
    lines.append("Evidence: " + evidence_sentence(evidence_quality(session, code, fy)))
    return lines


GAP_COLUMNS = [
    "kpi",
    "unit",
    "value",
    "sector median",
    "basis",
    "change to reach median %",
    "reading",
]


def gap_to_benchmark(
    session: Session, code: str, fy: str, indicators: IndicatorsConfig
) -> pd.DataFrame:
    """For each KPI, the change that would bring the company to its sector median (the median of the
    companies in its sector that pass the data-quality checks)."""
    matrix = kpi_matrix(session, fy, indicators)
    rows = []
    for r in matrix[matrix["code"] == code].to_dict("records"):
        value, median, lower = r["value"], r["sector median"], r["better"] == "lower"
        if r["band"] == DATA_CHECK:
            change, reading = float("nan"), "n/a: the figure fails a data-quality check"
        elif pd.isna(median) or value == 0:
            change, reading = float("nan"), "n/a"
        else:
            change = (median - value) / value * 100
            if (value <= median) if lower else (value >= median):
                reading = "already at or better than the median"
            else:
                way = "fall" if lower else "rise"
                reading = f"a {way} of {abs(change):.1f}% would reach the median"
        basis = (
            f"median of the {r['companies compared']} companies compared"
            if not pd.isna(median)
            else "too few companies compared"
        )
        rows.append(
            {
                "kpi": r["label"],
                "unit": r["unit"],
                "value": value,
                "sector median": median,
                "basis": basis,
                "change to reach median %": change,
                "reading": reading,
            }
        )
    return pd.DataFrame(rows, columns=GAP_COLUMNS)


def what_if(
    session: Session,
    code: str,
    fy: str,
    kpi_code: str,
    change_pct: float,
    indicators: IndicatorsConfig,
) -> dict | None:
    """Arithmetic only: the company's rank in its sector if its KPI moved by `change_pct` percent and
    every other company stayed where it is. Not a forecast and not a target. Empty when the figure
    fails a data-quality check."""
    spec = next(k for k in indicators.kpis if k.code == kpi_code)
    frame = sector_overview(session, fy, kpi_code, indicators)
    mine = frame[frame["code"] == code]
    if mine.empty or mine.iloc[0]["data check"]:
        return None
    peers = frame[(frame["sector"] == mine.iloc[0]["sector"]) & (frame["data check"] == "")]
    values = dict(zip(peers["code"], peers["value"], strict=True))
    now = values[code]
    after = now * (1 + change_pct / 100)
    rank_now = _rank_among(values, code, spec.better)
    rank_after, n, band_after = rank_after_change(values, code, after, spec.better)
    return {
        "kpi": spec.label,
        "unit": pretty_unit(spec.unit),
        "value_now": now,
        "value_after": after,
        "rank_now": rank_now,
        "rank_after": rank_after,
        "n": n,
        "band_now": band_for(rank_now, n),
        "band_after": band_after,
    }


# ---- knowledge: what the numbers mean ---------------------------------------------------------
LIMITS = (
    "Pilot scale: about five companies per sector, so a rank or a median describes this sample, "
    "not the sector.",
    "The figures come from each company's own, self-reported BRSR filing. A data-quality flag marks "
    "a figure to check; it is not a finding that a company misreported.",
    "Positions are on intensities within one sector. A better position on one KPI does not make a "
    "company greener overall, and sectors are never compared with each other.",
    f"SDG mappings: {vocab.SDG_CAPTION}.",
    "A what-if is arithmetic on today's figures with every other company held fixed. It is not a "
    "forecast and not a target.",
)

GLOSSARY = {
    "BRSR": "Business Responsibility and Sustainability Report: the annual sustainability disclosure "
    "that SEBI, India's securities regulator, requires of listed companies in scope.",
    "XBRL": "A machine-readable filing format. The system reads each filing's XBRL and cross-checks "
    "figures against the PDF where it has one.",
    "Scope 1 emissions": "Greenhouse-gas emissions from sources the company owns or controls.",
    "Scope 2 emissions": "Emissions from the electricity, steam, heat or cooling the company buys.",
    "tCO2e": "Tonnes of carbon dioxide equivalent: different gases expressed as the CO2 that would "
    "warm the climate by the same amount.",
    "Intensity": "A quantity divided by revenue (here, per rupee crore). It lets companies of "
    "different size be compared.",
    "Rupee crore": "Ten million rupees.",
    "Renewable share": "Renewable energy consumed as a percentage of all energy consumed.",
    "Reporting boundary": "Standalone means the company alone; consolidated means the company "
    "together with its subsidiaries. Figures on different boundaries are not like for like.",
    "Assurance": "An independent external check of reported figures. Where a filing does not state "
    "it, the system shows 'not stated'.",
    "Better, middle, weaker third": "A company's position among the companies loaded in its sector "
    "on one KPI, taking the KPI's direction into account. It describes the sample and is not a "
    "rating.",
    "Data-quality flag": "A rule that a figure failed: an arithmetic impossibility, a missing year, "
    "or a unit corrected from the PDF. Errors need a look; warnings are for information.",
    "Restated comparative": "A prior-year figure taken from a later filing, as the company then "
    "stated it. It can differ from the figure in the original filing.",
    "SHA-256": "A fingerprint of a file. If the file changes, the fingerprint changes, so it shows "
    "that a filing is the one that was loaded.",
}

# (capability, where in the system, what it does for the user). The views must all exist.
CAPABILITIES = (
    (
        "Status access",
        ("Home", "Sectors"),
        "The current picture, stamped with the latest fiscal year loaded and the date the filings "
        "were retrieved.",
    ),
    (
        "Critical success factors",
        ("KPI scorecard",),
        "Five metrics for every company, coloured by position within the sector.",
    ),
    (
        "Exception reporting",
        ("Sectors", "Data quality register"),
        "What to look at first in a sector, and the full register of figures that failed a check.",
    ),
    (
        "Drill-down",
        ("KPI scorecard", "Companies", "Sources and filings"),
        "Scorecard, then company, then figure, then the filing it was read from.",
    ),
    (
        "Trend analysis",
        ("Sectors", "Companies", "Compare companies"),
        "Year-on-year movement, and lines over time for a company, a sector or chosen companies.",
    ),
    (
        "Peer comparison",
        ("Compare companies",),
        "Chosen companies side by side, with who is best and by how much stated in words.",
    ),
    (
        "Ad hoc query with automatic charts",
        ("Query and chart",),
        "Choose the data type, metrics, companies and years; the chart type is picked from the "
        "shape of the question.",
    ),
    (
        "Benchmark comparison",
        ("Companies",),
        "How far each metric is from the sector median, and what change would close the gap.",
    ),
    (
        "Decision support",
        ("Companies",),
        "A what-if: how a company's rank would change if one metric moved.",
    ),
    (
        "Compliance monitoring",
        ("Compliance check",),
        "Does each filing disclose the BRSR Core figures, state its boundary and assurance, and "
        "stay internally consistent?",
    ),
    (
        "Interpretation aids",
        ("Companies", "Metrics guide", "About"),
        "What each number means in plain words, a worked example, a glossary and the limits of the data.",
    ),
    (
        "Data integration",
        ("Sources and filings",),
        "XBRL and PDF sources reconciled into one schema, one row per filing.",
    ),
    (
        "Traceability and audit",
        ("Sources and filings", "Data verification"),
        "Every value traced to a file, a fingerprint and the person who checked it.",
    ),
    (
        "Data-quality assurance",
        ("Data quality register", "Data verification"),
        "Rules find defects; a person confirms or corrects them.",
    ),
    (
        "Reporting and export",
        ("Companies", "Query and chart", "Compare companies"),
        "A one-page briefing per company and CSV export of every table.",
    ),
    (
        "Soft information",
        ("Companies", "Data verification"),
        "Reviewers' notes are kept beside the figures they concern.",
    ),
)


def indicator_guide(indicators: IndicatorsConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The reported indicators and the derived KPIs, defined from the same config the code runs."""
    labels = {i.code: i.label for i in indicators.indicators}
    inputs = pd.DataFrame(
        [{"indicator": i.label, "unit": i.unit, "group": i.group} for i in indicators.indicators]
    )

    def readable(formula: str) -> str:
        for code in sorted(labels, key=len, reverse=True):
            formula = formula.replace(code, labels[code])
        return formula

    kpis = pd.DataFrame(
        [
            {
                "KPI": k.label,
                "unit": k.unit,
                "how it is computed": readable(k.formula),
                "direction": "lower is better" if k.better == "lower" else "higher is better",
                "core KPI": "yes" if k.core else "no",
            }
            for k in indicators.kpis
        ]
    )
    return inputs, kpis


def _md_table(frame: pd.DataFrame) -> list[str]:
    head = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    rule = "|" + "|".join("---" for _ in frame.columns) + "|"
    body = [
        "| " + " | ".join(str(v).replace("|", "/") for v in row) + " |"
        for row in frame.itertuples(index=False)
    ]
    return [head, rule, *body]


def company_brief_markdown(
    session: Session, code: str, fy: str, indicators: IndicatorsConfig, name: str
) -> str:
    """A one-page briefing on one company: reading, figures, gap to the median, flags, provenance."""
    matrix = kpi_matrix(session, fy, indicators)
    mine = matrix[matrix["code"] == code]

    def rank_text(row) -> str:
        if row["band"] == DATA_CHECK:
            return "not ranked"
        return f"{row['rank in sector']} of {row['companies compared']}"

    records = mine.to_dict("records")
    table = pd.DataFrame(
        {
            "KPI": [r["label"] for r in records],
            "value": [f"{fmt_number(r['value'])} {r['unit']}" for r in records],
            "rank in sector": [rank_text(r) for r in records],
            "position": [r["band"] for r in records],
            "change vs previous year": [
                "n/a" if pd.isna(r["change %"]) else _signed_pct(r["change %"]) for r in records
            ],
        }
    )
    gap = gap_to_benchmark(session, code, fy, indicators)
    gap_table = pd.DataFrame(
        {
            "KPI": gap["kpi"],
            "sector median": [fmt_number(m) for m in gap["sector median"]],
            "reading": gap["reading"],
        }
    )
    flags = company_flags(session, code)
    flags = flags[(flags["fy"] == fy) | flags["fy"].isna()]
    report = session.scalar(
        select(Report)
        .join(Company, Company.id == Report.company_id)
        .where(Company.code == code, Report.fy == fy)
    )
    asof = data_as_of(session)
    lines = [
        f"# {name}: environmental KPI briefing, {fy}",
        "",
        f"Data as of the latest filing retrieved on {asof['retrieved_on'] or 'an unrecorded date'}.",
        "",
        "## Reading",
        "",
        *[f"- {line}" for line in company_reading(session, code, fy, indicators)],
        "",
        "## Figures",
        "",
        *_md_table(table),
        "",
        "## Distance from the sector median",
        "",
        *_md_table(gap_table),
        "",
        "## Data-quality flags",
        "",
    ]
    if flags.empty:
        lines.append("None for this year.")
    else:
        lines += [f"- **{r.severity}** {r.rule}: {r.message}" for r in flags.itertuples()]
    lines += ["", "## Where the figures came from", ""]
    if report is None:
        lines.append("No filing is loaded for this year.")
    else:
        lines += [
            f"- File: {report.source_file or 'not recorded'}",
            f"- SHA-256: {report.file_sha256 or 'not recorded'}",
            f"- Retrieved on: {report.retrieved_on or 'not recorded'}",
        ]
    lines += ["", "## Read this with care", "", *[f"- {limit}" for limit in LIMITS], ""]
    return "\n".join(lines)


# ---- units and plain-language explanations ------------------------------------------------------
def pretty_unit(unit: str) -> str:
    """The unit as a person writes it: INR_crore and INR crore become the rupee sign and crore."""
    return unit.replace("INR_crore", "₹ crore").replace("INR crore", "₹ crore")


KWH_PER_GJ = 277.78  # 1 gigajoule = 1,000 megajoules = 277.78 kilowatt-hours


def _big(value: float) -> str:
    """12,345 stays as is; 1,186,700 becomes 1.19 million."""
    return f"{value / 1e6:.2f} million" if abs(value) >= 1e6 else fmt_number(value)


# What each metric is, in words. `means` says what is measured; `how` says how it is computed;
# `reading` says which direction is good; `caution` says what can mislead.
METRIC_NOTES: dict[str, dict[str, str]] = {
    "energy_intensity": {
        "means": "How much energy the company uses to earn each rupee crore of revenue.",
        "how": "Total energy consumed (GJ) divided by revenue from operations (₹ crore).",
        "reading": "Lower is better: less energy for the same revenue.",
        "caution": "It depends heavily on the type of business. Heavy industry will always be far above "
        "software or consumer goods, so compare companies within a sector.",
    },
    "emissions_intensity": {
        "means": "How many tonnes of greenhouse gas the company emits to earn each rupee crore of revenue.",
        "how": "(Scope 1 + Scope 2 emissions in tCO2e) divided by revenue from operations (₹ crore).",
        "reading": "Lower is better: fewer emissions for the same revenue.",
        "caution": "Scope 3 (emissions elsewhere in the value chain) is not included. Compare within "
        "a sector.",
    },
    "water_intensity": {
        "means": "How much water the company consumes to earn each rupee crore of revenue.",
        "how": "Water consumption (kL) divided by revenue from operations (₹ crore). "
        "Consumption is water no longer available to the ecosystem or community after use.",
        "reading": "Lower is better: less water consumed for the same revenue.",
        "caution": "Based on consumption, not withdrawal. Compare within a sector.",
    },
    "renewable_share": {
        "means": "The share of all the energy the company consumes that comes from renewable sources.",
        "how": "Renewable energy consumed divided by total energy consumed, times 100.",
        "reading": "Higher is better: a larger part of the energy is renewable.",
        "caution": "It is a share, so a company can have a high share and still use a lot of energy.",
    },
    "waste_recovery_rate": {
        "means": "The share of the waste the company generates that is recovered through recycling, "
        "re-use or other recovery operations.",
        "how": "Waste recovered (t) divided by waste generated (t), times 100.",
        "reading": "Higher is better: more of the waste is recovered. Above 100% is impossible and "
        "is flagged.",
        "caution": "Rates close to 100% can hide large absolute quantities, and the definition of "
        "'recovered' is the company's own.",
    },
    "revenue_from_operations": {
        "means": "The company's sales and operating income for the year, in ₹ crore "
        "(1 crore = 10 million rupees).",
        "how": "Reported by the company. It is the denominator of the intensities, which is what lets "
        "companies of different size be compared.",
        "reading": "A size measure, not a performance measure.",
        "caution": "Not comparable across sectors as a measure of anything environmental.",
    },
    "energy_total": {
        "means": "All the energy the company consumed in the year: fuels, and purchased or self-generated "
        "electricity, heating, cooling and steam.",
        "how": "Reported by the company, in gigajoules (GJ).",
        "reading": "A raw total: it grows with the size of the company.",
        "caution": "Do not rank companies on raw totals; use energy intensity.",
    },
    "energy_renewable": {
        "means": "The part of the energy consumed that came from renewable sources.",
        "how": "Reported by the company, in gigajoules (GJ).",
        "reading": "A raw total: it grows with the size of the company.",
        "caution": "Use renewable share for comparison.",
    },
    "scope1_emissions": {
        "means": "Direct greenhouse-gas emissions from sources the company owns or controls.",
        "how": "Reported by the company, in tonnes of CO2-equivalent (tCO2e).",
        "reading": "A raw total: it grows with the size of the company.",
        "caution": "Do not rank companies on raw totals; use emissions intensity.",
    },
    "scope2_emissions": {
        "means": "Indirect emissions from the generation of energy the company buys from a utility.",
        "how": "Reported by the company, in tonnes of CO2-equivalent (tCO2e).",
        "reading": "A raw total: it grows with the size of the company.",
        "caution": "Do not rank companies on raw totals; use emissions intensity.",
    },
    "water_withdrawal": {
        "means": "All the water the company took in from every source during the year.",
        "how": "Reported by the company, in kilolitres (kL). 1 kL = 1,000 litres.",
        "reading": "A raw total: it grows with the size of the company.",
        "caution": "Withdrawal is not consumption: some withdrawn water is returned.",
    },
    "water_consumption": {
        "means": "Water that is no longer available to the ecosystem or local community after the "
        "company used it, for example because it went into products or evaporated.",
        "how": "Reported by the company, in kilolitres (kL). 1 kL = 1,000 litres.",
        "reading": "A raw total: it grows with the size of the company.",
        "caution": "Use water intensity for comparison. It cannot exceed withdrawal.",
    },
    "waste_generated": {
        "means": "All the waste the company generated in the year.",
        "how": "Reported by the company, in tonnes (t).",
        "reading": "A raw total: it grows with the size of the company.",
        "caution": "Do not rank companies on raw totals.",
    },
    "waste_recovered": {
        "means": "The part of the waste recovered through recycling, re-use or other recovery operations.",
        "how": "Reported by the company, in tonnes (t).",
        "reading": "A raw total. It cannot exceed the waste generated.",
        "caution": "Use waste recovery rate for comparison.",
    },
}


def explain_value(code: str, value: float, sector_median: float | None = None) -> str:
    """What one number means, in a sentence: 'a water intensity of 498 kL per rupee crore means ...'."""
    v = fmt_number(value)
    text = {
        "energy_intensity": (
            f"For every ₹1 crore (₹10 million) of revenue the company used {v} gigajoules of "
            f"energy, about {_big(value * KWH_PER_GJ)} kWh."
        ),
        "emissions_intensity": (
            f"For every ₹1 crore (₹10 million) of revenue the company emitted {v} tonnes of "
            "greenhouse gas (CO2-equivalent, Scope 1 and 2)."
        ),
        "water_intensity": (
            f"For every ₹1 crore (₹10 million) of revenue the company consumed {v} kilolitres of "
            f"water, which is {value * 1000:,.0f} litres."
        ),
        "renewable_share": (
            f"{v}% of the energy the company consumed came from renewable sources, so about {v} of "
            "every 100 gigajoules."
        ),
        "waste_recovery_rate": (
            f"{v}% of the waste the company generated was recovered through recycling, re-use or other "
            "recovery operations."
        ),
    }.get(code)
    if text is None:
        return f"{v}."
    if sector_median is not None and not pd.isna(sector_median) and sector_median:
        gap = (value - sector_median) / abs(sector_median) * 100
        way = "above" if gap > 0 else "below"
        text += (
            f" The median of its sector is {fmt_number(sector_median)}, so this is "
            f"{abs(gap):.0f}% {way} it."
        )
    return text


def metric_catalog(indicators: IndicatorsConfig) -> list[dict]:
    """Every metric a person can ask about: the derived KPIs and the reported figures."""
    catalog = [
        {
            "code": k.code,
            "label": k.label,
            "unit": pretty_unit(k.unit),
            "kind": "derived",
            "better": k.better,
        }
        for k in indicators.kpis
    ]
    catalog += [
        {
            "code": i.code,
            "label": i.label,
            "unit": pretty_unit(i.unit),
            "kind": "reported",
            "better": None,
        }
        for i in indicators.indicators
    ]
    return catalog


# ---- what kind of company ----------------------------------------------------------------------
SECTOR_NOTES: dict[str, dict[str, str]] = {
    "Cement": {
        "what": "Companies that make cement, the binding material in concrete.",
        "footprint": "Heating limestone releases carbon dioxide and needs a great deal of fuel, so cement "
        "is among the most emission- and energy-intensive of the four sectors.",
        "compare": "Compare cement companies with each other. Their intensities are far above those "
        "of IT services or consumer goods.",
    },
    "Iron & Steel": {
        "what": "Companies that make iron and steel, including stainless steel.",
        "footprint": "Making steel is energy- and emission-heavy, and the production route changes the "
        "figures a lot, so companies in this sector are not always like for like.",
        "compare": "Compare steel companies with each other, and read a large gap as a possible "
        "difference in production route before reading it as better or worse.",
    },
    "IT Services": {
        "what": "Companies that provide software and information-technology services.",
        "footprint": "Their direct emissions and water use are small. Electricity for offices and data "
        "centres is the main footprint, so intensities per rupee are far lower than in industry.",
        "compare": "Compare IT companies with each other; their numbers are not comparable with "
        "cement or steel.",
    },
    "FMCG": {
        "what": "Fast-moving consumer goods: packaged food, personal care and household products.",
        "footprint": "A mixed footprint from factories, agricultural inputs and packaging, with moderate "
        "intensities compared with heavy industry.",
        "compare": "Compare FMCG companies with each other; product mix differs widely between them.",
    },
}

SECTOR_FALLBACK = {
    "what": "A group of companies in the same line of business.",
    "footprint": "Its environmental footprint depends on what the companies do.",
    "compare": "Compare companies with others in the same sector.",
}


def sector_note(name: str) -> dict[str, str]:
    return SECTOR_NOTES.get(name, SECTOR_FALLBACK)


def company_directory(session: Session) -> pd.DataFrame:
    """One row per company: name, symbol, sector, the years loaded and what its latest filing states."""
    reports: dict[str, list] = {}
    for code, fy, boundary, assured, entry in session.execute(
        select(Company.code, Report.fy, Report.boundary, Report.assured, Report.entry_method)
        .join(Report, Report.company_id == Company.id)
        .order_by(Report.fy)
    ):
        reports.setdefault(code, []).append((fy, boundary, assured, entry))
    rows = []
    for code, name, symbol, sector in session.execute(
        select(Company.code, Company.real_name, Company.nse_symbol, Sector.name)
        .join(Sector, Sector.id == Company.sector_id)
        .order_by(Sector.name, Company.real_name)
    ):
        loaded = reports.get(code, [])
        latest = loaded[-1] if loaded else (None, None, None, None)
        rows.append(
            {
                "code": code,
                "name": name,
                "symbol": symbol or code,
                "sector": sector,
                "years loaded": ", ".join(fy for fy, *_ in loaded) or "none",
                "latest year": latest[0] or "none",
                "boundary": latest[1] or "not stated",
                "assurance": {True: "assured", False: "not assured", None: "not stated"}[latest[2]],
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "code",
            "name",
            "symbol",
            "sector",
            "years loaded",
            "latest year",
            "boundary",
            "assurance",
        ],
    )


# ---- ask for the data you want ----------------------------------------------------------------
QUERY_COLUMNS = [
    "code",
    "sector",
    "fy",
    "metric_code",
    "metric",
    "unit",
    "kind",
    "value",
    "data check",
]


def query_data(
    session: Session,
    metric_codes: list[str],
    company_codes: list[str],
    fys: list[str],
    indicators: IndicatorsConfig,
) -> pd.DataFrame:
    """The values asked for, one row per company, year and metric, with units. Derived metrics come
    from the computed KPIs, reported figures from the filings as standardised."""
    catalog = {m["code"]: m for m in metric_catalog(indicators)}
    order = {code: i for i, code in enumerate(catalog)}
    flagged = _flagged_kpis(session, indicators)
    rows = []
    kpi_codes = [c for c in metric_codes if catalog.get(c, {}).get("kind") == "derived"]
    if kpi_codes:
        for code, sector, fy, kpi, value in session.execute(
            select(Company.code, Sector.name, KpiValue.fy, KpiValue.kpi, KpiValue.value)
            .join(Sector, Sector.id == Company.sector_id)
            .join(KpiValue, KpiValue.company_id == Company.id)
            .where(
                KpiValue.kpi.in_(kpi_codes), Company.code.in_(company_codes), KpiValue.fy.in_(fys)
            )
        ):
            rows.append(
                (
                    code,
                    sector,
                    fy,
                    kpi,
                    float(value),
                    ", ".join(sorted(flagged.get((code, fy, kpi), ()))),
                )
            )
    raw_codes = [c for c in metric_codes if catalog.get(c, {}).get("kind") == "reported"]
    if raw_codes:
        bad = {
            (code, fy, indicator): rule
            for code, fy, indicator, rule in session.execute(
                select(Company.code, QualityFlag.fy, QualityFlag.indicator, QualityFlag.rule)
                .join(Company, Company.id == QualityFlag.company_id)
                .where(QualityFlag.severity == "error", QualityFlag.indicator.isnot(None))
            )
        }
        for code, sector, fy, indicator, value in session.execute(
            select(
                Company.code, Sector.name, Report.fy, IndicatorValue.indicator, IndicatorValue.value
            )
            .join(Sector, Sector.id == Company.sector_id)
            .join(Report, Report.company_id == Company.id)
            .join(IndicatorValue, IndicatorValue.report_id == Report.id)
            .where(
                IndicatorValue.indicator.in_(raw_codes),
                Company.code.in_(company_codes),
                Report.fy.in_(fys),
            )
        ):
            rows.append(
                (code, sector, fy, indicator, float(value), bad.get((code, fy, indicator), ""))
            )
    frame = pd.DataFrame(
        [
            {
                "code": code,
                "sector": sector,
                "fy": fy,
                "metric_code": metric,
                "metric": catalog[metric]["label"],
                "unit": catalog[metric]["unit"],
                "kind": catalog[metric]["kind"],
                "value": value,
                "data check": check,
            }
            for code, sector, fy, metric, value, check in rows
        ],
        columns=QUERY_COLUMNS,
    )
    frame["_order"] = frame["metric_code"].map(order)
    frame = frame.sort_values(["_order", "sector", "code", "fy"]).drop(columns="_order")
    return frame.reset_index(drop=True)


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def choose_chart(n_metrics: int, n_companies: int, n_years: int) -> tuple[str, str]:
    """Pick the chart that suits the shape of a query, and say why. Kinds: bar, line, scatter,
    bar_panels, line_panels, table."""
    if n_metrics == 0 or n_companies == 0 or n_years == 0:
        return "table", "Nothing is selected yet."
    shape = (
        f"{_count(n_metrics, 'metric', 'metrics')}, "
        f"{_count(n_companies, 'company', 'companies')}, {_count(n_years, 'year', 'years')}"
    )
    if n_companies == 1 and n_years == 1:
        return (
            "table",
            f"{shape}: one company in one year has nothing to compare, and metrics in different units "
            "cannot share an axis, so a table is clearer.",
        )
    if n_metrics == 1 and n_years == 1:
        return "bar", f"{shape}: one value per company, so a bar chart ranks them."
    if n_metrics == 1:
        return "line", f"{shape}: one metric over several years, so a line shows the trend."
    if n_years == 1 and n_metrics == 2 and n_companies >= 3:
        return (
            "scatter",
            f"{shape}: two metrics for several companies, so a scatter plot shows how they relate.",
        )
    if n_years == 1:
        return (
            "bar_panels",
            f"{shape}: the metrics have different units, so each gets its own panel and scale.",
        )
    return (
        "line_panels",
        f"{shape}: several metrics over several years, so each metric gets its own trend panel.",
    )


# ---- compare chosen companies -----------------------------------------------------------------
def compare_table(
    session: Session, codes: list[str], fy: str, indicators: IndicatorsConfig
) -> pd.DataFrame:
    """The chosen companies side by side on every KPI. `best` names the company with the best
    figure that passes the data checks, and `gap` how far each other figure is from it."""
    matrix = kpi_matrix(session, fy, indicators)
    rows = []
    for spec in indicators.kpis:
        part = matrix[(matrix["kpi"] == spec.code) & matrix["code"].isin(codes)]
        if part.empty:
            continue
        values = dict(zip(part["code"], part["value"], strict=True))
        checks = dict(zip(part["code"], part["data check"], strict=True))
        clean = {c: v for c, v in values.items() if not checks[c]}
        lower = spec.better == "lower"
        best = (min if lower else max)(clean, key=clean.get) if clean else None
        row = {
            "metric_code": spec.code,
            "metric": spec.label,
            "unit": pretty_unit(spec.unit),
            "better": spec.better,
            "best": best,
        }
        for c in codes:
            row[c] = values.get(c, float("nan"))
            row[f"{c} check"] = checks.get(c, "")
        rows.append(row)
    return pd.DataFrame(rows)


def _gap_text(value: float, reference: float) -> str:
    """How far `value` is from `reference` in words: '35% lower', '120% higher', '620 times as high'."""
    ratio = value / reference
    if ratio >= 3:
        return f"{ratio:,.0f} times as high"
    if ratio > 1.005:
        return f"{(ratio - 1) * 100:.0f}% higher"
    if ratio < 0.995:
        return f"{(1 - ratio) * 100:.0f}% lower"
    return "the same"


def comparison_sentences(
    table: pd.DataFrame, codes: list[str], names: Mapping[str, str]
) -> list[str]:
    """The comparison in words: who is best on each metric and how far the others are from it."""
    lines = []
    for r in table.to_dict("records"):
        best = r["best"]
        if best is None:
            lines.append(f"{r['metric']}: no figure passes the data checks, so nothing is ranked.")
            continue
        others = [c for c in codes if c != best and not pd.isna(r[c]) and not r[f"{c} check"]]
        parts = [
            f"{names[c]} {fmt_number(r[c])} ({_gap_text(r[c], r[best])})" for c in others if r[best]
        ]
        head = f"{r['metric']}: {names[best]} is best at {fmt_number(r[best])} {r['unit']}"
        line = head + ("; " + "; ".join(parts) if parts else "") + "."
        flagged = [names[c] for c in codes if r[f"{c} check"]]
        if flagged:
            line += (
                f" Not ranked because the figure fails a data-quality check: {', '.join(flagged)}."
            )
        lines.append(line)
    return lines


# ---- check what each filing discloses -----------------------------------------------------------
# From SEBI circular SEBI/HO/CFD/CMD-2/P/CIR/2023/122 of 12 July 2023, section 3.4.2: reasonable
# assurance of BRSR Core is mandatory for the top listed entities by market capitalisation.
GLIDE_PATH = (
    ("FY2023-24", "top 150"),
    ("FY2024-25", "top 250"),
    ("FY2025-26", "top 500"),
    ("FY2026-27", "top 1000"),
)

# BRSR Core (annexure I of that circular) covers GHG footprint (Scope 1 and 2), water footprint
# (consumption), energy footprint (total, renewable share) and waste management (generated, recovered).
CORE_REPORTED = (
    "scope1_emissions",
    "scope2_emissions",
    "water_consumption",
    "energy_total",
    "energy_renewable",
    "waste_generated",
    "waste_recovered",
)

CHECK_TITLES = {
    "filing": "The company's own filing is loaded",
    "core": "BRSR Core environmental figures are disclosed",
    "boundary": "Reporting boundary is stated",
    "assurance": "An assurance statement is present",
    "consistency": "Figures are internally consistent",
    "units": "Units needed no correction",
    "checked": "Values checked by a person",
    "years": "Years available for trend",
}
CHECK_WHY = {
    "filing": "A figure taken from the prior-year column of a later filing is the company's restated "
    "number, not the filing as it was submitted that year.",
    "core": "SEBI's BRSR Core lists greenhouse-gas, water, energy and waste figures for assurance. A "
    "missing figure cannot be assured or compared.",
    "boundary": "Figures on a standalone boundary and on a consolidated one are not like for like.",
    "assurance": "SEBI requires reasonable assurance of BRSR Core for the top listed entities by market "
    "capitalisation, on a glide path: top 150 for FY2023-24, 250 for FY2024-25, 500 for FY2025-26 and "
    "1000 for FY2026-27. This system does not compute each company's rank, so it reports what the "
    "data states and does not decide whether assurance was required.",
    "consistency": "Some rules cannot be broken by a sound figure, for example more waste recovered "
    "than generated, or water consumed above water withdrawn.",
    "units": "Where an XBRL unit label was wrong or missing, the system corrected it from the PDF. "
    "Each correction is recorded and can be inspected.",
    "checked": "A person compares a stored value with the filing and records the result.",
    "years": "Trends need more than one year loaded.",
}
CHECK_ORDER = (
    "filing",
    "core",
    "boundary",
    "assurance",
    "consistency",
    "units",
    "checked",
    "years",
)
CHECK_SHORT = {
    "filing": "Own filing",
    "core": "Core figures",
    "boundary": "Boundary",
    "assurance": "Assurance",
    "consistency": "Consistency",
}


def compliance_checks(
    session: Session, code: str, fy: str, indicators: IndicatorsConfig
) -> list[dict]:
    """What one company's filing for one year does and does not disclose, and whether its figures are
    consistent. Each check is pass, attention, fail or info. This is a disclosure check, not a legal
    finding of compliance."""
    label = {i.code: i.label for i in indicators.indicators}
    report = session.scalar(
        select(Report)
        .join(Company, Company.id == Report.company_id)
        .where(Company.code == code, Report.fy == fy)
    )
    checks: list[dict] = []

    def add(key: str, status: str, found: str) -> None:
        checks.append(
            {
                "key": key,
                "check": CHECK_TITLES[key],
                "status": status,
                "found": found,
                "why it matters": CHECK_WHY[key],
            }
        )

    years = list(
        session.scalars(
            select(Report.fy)
            .join(Company, Company.id == Report.company_id)
            .where(Company.code == code)
            .order_by(Report.fy)
        )
    )
    if report is None:
        add("filing", "fail", "No filing is loaded for this year.")
        add("years", "info", f"{len(years)} year(s) loaded: {', '.join(years) or 'none'}.")
        return checks
    if report.entry_method == "xbrl_comparative":
        add(
            "filing",
            "attention",
            "Taken from the prior-year column of a later filing. The filing as submitted that year is "
            "not loaded.",
        )
    else:
        add("filing", "pass", "Loaded from the company's own filing.")
    present = {
        indicator
        for (indicator,) in session.execute(
            select(IndicatorValue.indicator).where(IndicatorValue.report_id == report.id)
        )
    }
    missing = [label.get(c, c) for c in CORE_REPORTED if c not in present]
    n = len(CORE_REPORTED) - len(missing)
    if not missing:
        add("core", "pass", f"All {len(CORE_REPORTED)} figures are present.")
    else:
        status = "fail" if n == 0 else "attention"
        add("core", status, f"{n} of {len(CORE_REPORTED)} present. Missing: {', '.join(missing)}.")
    if report.boundary:
        add("boundary", "pass", f"Stated: {report.boundary}.")
    else:
        add("boundary", "attention", "The data loaded does not state the reporting boundary.")
    if report.assured is True:
        add("assurance", "pass", "The filing states that its figures are assured.")
    elif report.assured is False:
        add("assurance", "attention", "The filing states that its figures are not assured.")
    else:
        note = (
            " A prior-year column does not carry the assurance statement."
            if report.entry_method == "xbrl_comparative"
            else ""
        )
        add(
            "assurance",
            "attention",
            "No assurance statement is recorded in the data loaded." + note,
        )
    counts = flag_counts(session, fy).get(code, {"errors": 0, "warnings": 0})
    if counts["errors"]:
        rules = sorted(
            {
                rule
                for (rule,) in session.execute(
                    select(QualityFlag.rule)
                    .join(Company, Company.id == QualityFlag.company_id)
                    .where(
                        Company.code == code,
                        QualityFlag.severity == "error",
                        (QualityFlag.fy == fy) | QualityFlag.fy.is_(None),
                    )
                )
            }
        )
        add(
            "consistency",
            "fail",
            f"{counts['errors']} error flag(s): "
            + "; ".join(f"{r} ({RULE_NOTES.get(r, r)})" for r in rules)
            + ".",
        )
    elif counts["warnings"]:
        add("consistency", "attention", f"No errors, but {counts['warnings']} warning flag(s).")
    else:
        add("consistency", "pass", "No error or warning flags.")
    fixed = session.scalar(
        select(func.count(QualityFlag.id))
        .join(Company, Company.id == QualityFlag.company_id)
        .where(
            Company.code == code,
            QualityFlag.fy == fy,
            QualityFlag.rule == "xbrl_override_applied",
        )
    )
    add(
        "units",
        "info",
        f"{fixed} unit correction(s) were applied from the PDF." if fixed else "None were needed.",
    )
    quality = evidence_quality(session, code, fy)
    add(
        "checked",
        "info",
        f"{quality['checked']} of {quality['values']} values checked by a person.",
    )
    add("years", "info", f"{len(years)} year(s) loaded: {', '.join(years)}.")
    return checks


def compliance_summary(checks: list[dict]) -> dict[str, int]:
    graded = [c for c in checks if c["status"] != "info"]
    return {
        "passed": sum(c["status"] == "pass" for c in graded),
        "attention": sum(c["status"] == "attention" for c in graded),
        "failed": sum(c["status"] == "fail" for c in graded),
        "of": len(graded),
    }


def compliance_matrix(session: Session, fy: str, indicators: IndicatorsConfig) -> pd.DataFrame:
    """Every company against the disclosure checks for one year."""
    rows = []
    for code, sector in session.execute(
        select(Company.code, Sector.name)
        .join(Sector, Sector.id == Company.sector_id)
        .order_by(Sector.name, Company.code)
    ):
        checks = {c["key"]: c for c in compliance_checks(session, code, fy, indicators)}
        summary = compliance_summary(list(checks.values()))
        row = {"code": code, "sector": sector}
        for key, title in CHECK_SHORT.items():
            row[title] = checks[key]["status"] if key in checks else "n/a"
        row["passed"] = summary["passed"]
        row["of"] = summary["of"]
        rows.append(row)
    return pd.DataFrame(rows)


def _versus_lowest(high: float, low: float) -> str:
    ratio = high / low
    if ratio >= 3:
        return f"{ratio:,.0f} times the lowest"
    if ratio > 1.005:
        return f"{(ratio - 1) * 100:.0f}% above the lowest"
    return "about the same as the lowest"


def describe_query(
    frame: pd.DataFrame, names: Mapping[str, str], directions: Mapping[str, str | None]
) -> list[str]:
    """What a query result says, in sentences: the lowest and highest in the latest year, and the
    biggest movers when several years were asked for. Figures failing a data check are left out."""
    lines = []
    for metric, part in frame.groupby("metric", sort=False):
        unit = part["unit"].iloc[0]
        tag = {"lower": " (lower is better)", "higher": " (higher is better)"}.get(
            directions.get(metric), ""
        )
        years = sorted(part["fy"].unique())
        latest = part[(part["fy"] == years[-1]) & (part["data check"] == "")]
        if len(latest) == 1:
            r = latest.iloc[0]
            lines.append(
                f"{metric}{tag}: {names[r['code']]} had {fmt_number(r['value'])} {unit} in {years[-1]}."
            )
        elif len(latest) >= 2:
            lo = latest.loc[latest["value"].idxmin()]
            hi = latest.loc[latest["value"].idxmax()]
            versus = (
                f" ({names[hi['code']]} is {_versus_lowest(hi['value'], lo['value'])})"
                if lo["value"] > 0
                else ""
            )
            lines.append(
                f"{metric}{tag}, {years[-1]}: lowest is {names[lo['code']]} at "
                f"{fmt_number(lo['value'])} {unit}, "
                f"highest is {names[hi['code']]} at {fmt_number(hi['value'])} {unit}{versus}."
            )
        if len(years) < 2:
            continue
        movers = []
        for code, series in part[part["data check"] == ""].groupby("code"):
            ordered = series.sort_values("fy")
            if len(ordered) >= 2 and ordered["value"].iloc[0]:
                first, last = ordered.iloc[0], ordered.iloc[-1]
                movers.append(
                    (
                        code,
                        (last["value"] - first["value"]) / abs(first["value"]) * 100,
                        first["fy"],
                        last["fy"],
                    )
                )
        rises = sorted((m for m in movers if m[1] >= 1), key=lambda m: -m[1])
        falls = sorted((m for m in movers if m[1] <= -1), key=lambda m: m[1])
        bits = []
        if rises:
            bits.append(f"largest rise {names[rises[0][0]]} ({rises[0][1]:+.0f}%)")
        if falls:
            bits.append(f"largest fall {names[falls[0][0]]} ({falls[0][1]:+.0f}%)")
        if bits:
            lines.append(f"{metric}, {movers[0][2]} to {movers[0][3]}: " + "; ".join(bits) + ".")
        elif movers:
            lines.append(
                f"{metric}: no company moved by 1% or more between the first and last year chosen."
            )
    return lines
