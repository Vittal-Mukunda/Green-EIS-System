"""`gauge evaluate`: score the parsed judgments against the rules (no LLM-as-judge).

Steps: load the standards (frozen T2 rule, T3 update rule, evidence) -> label the numeric claims in
every justification -> build the C1 -> C2 transitions and the disagreement flags -> compute every
metric -> store the metric rows. Everything it writes is derived and can be rebuilt; human
annotations are never deleted (see grounding.store_claims).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig, StudyConfig
from gauge.db.models import Claim, Condition, Judgment, Model, Run, TransitionResult
from gauge.evaluate.derived import build_flags, build_transitions
from gauge.evaluate.frame import load_frame, valid_only
from gauge.evaluate.grounding import (
    label_justification,
    mention_pattern,
    shown_values,
    store_claims,
)
from gauge.evaluate.metrics import compute_metrics, prepare
from gauge.evaluate.results import EVAL_VERSION, replace_metrics
from gauge.evaluate.standards import Standards, StandardsError, load_standards


class EvaluationError(RuntimeError):
    """There is nothing to evaluate yet, or the standards cannot be computed."""


@dataclass
class EvalSummary:
    judgments: int = 0
    valid: int = 0
    claims: int = 0
    transitions: int = 0
    flags: dict[str, int] = field(default_factory=dict)
    metrics: int = 0
    notes: list[str] = field(default_factory=list)


def build_claims(
    session: Session, frame: pd.DataFrame, standards: Standards, indicators: IndicatorsConfig
) -> int:
    """Label the claims of every valid justification against what its prompt showed."""
    patterns = mention_pattern(indicators)
    total = 0
    for row in valid_only(frame).itertuples():
        ce = standards.evidence.companies[row.company_code]
        shown = shown_values(ce, standards.evidence, standards.t2_rule, indicators, row.condition)
        results = label_justification(row.justification or "", patterns, shown)
        total += store_claims(session, int(row.judgment_id), results)
    return total


def load_transitions(session: Session) -> pd.DataFrame:
    from gauge.db.models import Company

    rows = session.execute(
        select(
            Model.key,
            Company.code,
            TransitionResult.repetition,
            TransitionResult.label,
            TransitionResult.expected_direction,
            TransitionResult.delta_rating,
            TransitionResult.trend_signal,
            TransitionResult.benchmark_signal,
            TransitionResult.t2_changed,
        )
        .join(Model, Model.id == TransitionResult.model_id)
        .join(Company, Company.id == TransitionResult.company_id)
        .where(TransitionResult.variant == "")
        .order_by(Model.key, TransitionResult.repetition, Company.code)
    ).all()
    return pd.DataFrame(
        rows,
        columns=[
            "model_key",
            "company_code",
            "repetition",
            "label",
            "expected",
            "delta",
            "trend_signal",
            "benchmark_signal",
            "t2_changed",
        ],
    )


def load_claims(session: Session) -> pd.DataFrame:
    rows = session.execute(
        select(Judgment.id, Model.key, Condition.code, Claim.claim_type, Claim.status)
        .join(Claim, Claim.judgment_id == Judgment.id)
        .join(Run, Run.id == Judgment.run_id)
        .join(Model, Model.id == Run.model_id)
        .join(Condition, Condition.id == Run.condition_id)
    ).all()
    return pd.DataFrame(
        rows, columns=["judgment_id", "model_key", "condition", "claim_type", "status"]
    )


def run_evaluation(session: Session, cfg: StudyConfig, indicators: IndicatorsConfig) -> EvalSummary:
    summary = EvalSummary()
    frame = load_frame(session)
    if frame.empty:
        raise EvaluationError("no parsed judgments yet: run `gauge run` and `gauge parse` first")
    try:
        standards = load_standards(session, cfg, indicators)
    except StandardsError as exc:
        raise EvaluationError(f"cannot compute the standards: {exc}") from exc
    unknown = set(frame["company_code"]) - set(standards.t2)
    if unknown:
        raise EvaluationError(f"judgments name companies outside the sample: {sorted(unknown)}")
    summary.judgments, summary.valid = len(frame), int(frame["valid"].sum())

    summary.claims = build_claims(session, frame, standards, indicators)
    if {"C1", "C2"} <= set(frame["condition"]) and standards.t3:
        summary.transitions = build_transitions(session, frame, standards)
    else:
        summary.notes.append(
            "no C1 -> C2 transitions: both conditions and the 3-year trend are needed"
        )
    summary.flags = build_flags(session, frame, standards)

    data = prepare(
        frame,
        standards,
        load_transitions(session),
        load_claims(session),
        resamples=cfg.stats.bootstrap_resamples,
        seed=cfg.runs.master_seed,
        ci=cfg.stats.ci_level,
    )
    summary.metrics = replace_metrics(session, EVAL_VERSION, compute_metrics(data))
    return summary
