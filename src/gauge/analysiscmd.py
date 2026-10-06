"""Stages behind `gauge evaluate`, `stats`, `checklist` and `export` (shared with the dry run)."""

from __future__ import annotations

from sqlalchemy import Engine

from gauge.config import IndicatorsConfig, ModelsConfig, StudyConfig
from gauge.db.session import session_scope
from gauge.evaluate.grounding import ClaimStoreError
from gauge.evaluate.run import EvaluationError, run_evaluation
from gauge.report.checklist import write_checklist
from gauge.report.export import export_results
from gauge.stages import StageResult
from gauge.stats.run import run_statistics


def stage_evaluate(engine: Engine, cfg: StudyConfig, indicators: IndicatorsConfig) -> StageResult:
    try:
        with session_scope(engine) as session:
            s = run_evaluation(session, cfg, indicators)
    except (EvaluationError, ClaimStoreError) as exc:
        return StageResult("evaluate", "error", str(exc))
    flags = ", ".join(f"{k}={v}" for k, v in sorted(s.flags.items())) or "none"
    detail = (
        f"{s.judgments} judgments ({s.valid} valid); {s.claims} claims labelled; "
        f"{s.transitions} C1->C2 transitions; flags: {flags}; {s.metrics} metric rows"
    )
    if s.notes:
        detail += "; " + "; ".join(s.notes)
    return StageResult("evaluate", "ok", detail, data={"metrics": s.metrics})


def stage_stats(engine: Engine, cfg: StudyConfig, indicators: IndicatorsConfig) -> StageResult:
    try:
        with session_scope(engine) as session:
            s = run_statistics(session, cfg, indicators)
    except EvaluationError as exc:
        return StageResult("stats", "error", str(exc))
    outcomes = ", ".join(f"{h.id} {h.outcome}" for h in s.hypotheses)
    return StageResult(
        "stats", "ok", f"{s.metrics} metric rows; {outcomes}", data={"metrics": s.metrics}
    )


def stage_checklist(
    engine: Engine, cfg: StudyConfig, indicators: IndicatorsConfig, models: ModelsConfig
) -> StageResult:
    with session_scope(engine) as session:
        path = write_checklist(session, cfg, models)
    return StageResult("checklist", "ok", f"wrote {path}")


def stage_export(engine: Engine, cfg: StudyConfig) -> StageResult:
    with session_scope(engine) as session:
        paths = export_results(session, cfg)
    return StageResult(
        "export", "ok", f"{len(paths)} files (CSV tables and RESULTS.md) in {cfg.results_path}"
    )
