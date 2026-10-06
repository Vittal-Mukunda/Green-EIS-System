"""`gauge stats`: attribute agreement is computed by `evaluate`; this adds the hypothesis tests H1-H6,
the supplementary rating-shift test and the position-effect models, and stores their rows.

It reads the judgments, the transitions and the claims that `gauge evaluate` stored, so run that first.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig, StudyConfig
from gauge.evaluate.frame import load_frame
from gauge.evaluate.metrics import EvalData, prepare
from gauge.evaluate.results import STATS_VERSION, replace_metrics
from gauge.evaluate.run import EvaluationError, load_claims, load_transitions
from gauge.evaluate.standards import StandardsError, load_standards
from gauge.stats.hypotheses import HypothesisResult, hypothesis_metrics, run_hypotheses
from gauge.stats.position import position_effects


@dataclass
class StatsSummary:
    hypotheses: list[HypothesisResult]
    metrics: int


def load_eval_data(session: Session, cfg: StudyConfig, indicators: IndicatorsConfig) -> EvalData:
    frame = load_frame(session)
    if frame.empty:
        raise EvaluationError("no parsed judgments yet: run `gauge run` and `gauge parse` first")
    try:
        standards = load_standards(session, cfg, indicators)
    except StandardsError as exc:
        raise EvaluationError(f"cannot compute the standards: {exc}") from exc
    return prepare(
        frame,
        standards,
        load_transitions(session),
        load_claims(session),
        resamples=cfg.stats.bootstrap_resamples,
        seed=cfg.runs.master_seed,
        ci=cfg.stats.ci_level,
    )


def run_statistics(
    session: Session, cfg: StudyConfig, indicators: IndicatorsConfig
) -> StatsSummary:
    data = load_eval_data(session, cfg, indicators)
    if {"C1", "C2"} <= set(data.conditions) and data.transitions.empty and data.standards.t3:
        raise EvaluationError("no transitions stored: run `gauge evaluate` before `gauge stats`")
    results = run_hypotheses(data, alpha=cfg.stats.alpha)
    rows = [*hypothesis_metrics(results), *position_effects(data)]
    return StatsSummary(results, replace_metrics(session, STATS_VERSION, rows))
