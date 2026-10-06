"""Whole-pipeline orchestration for `gauge all-dry` / `make all-dry`.

The stage list mirrors the CLI. Stages whose phase has not been built yet report `pending`
instead of silently passing, so a green dry run never overstates what exists. Each later phase
replaces a pending stage with a real one.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Engine, func, select

from gauge.analysiscmd import (
    stage_checklist,
    stage_evaluate,
    stage_export,
    stage_stats,
)
from gauge.config import (
    IndicatorsConfig,
    ModelsConfig,
    StudyConfig,
    load_indicators,
    load_models,
    load_study,
)
from gauge.db.models import Run, RunCompanyPosition
from gauge.db.session import init_db, make_engine, session_scope
from gauge.evaluate.standards import load_standards
from gauge.registry import sync_registry
from gauge.render.prompts import TEMPLATE_FILES
from gauge.render.runs import prepare_render, render_run_prompts
from gauge.runcmd import stage_parse
from gauge.runner.execute import execute_run
from gauge.runner.mock import MockRunner
from gauge.stages import (
    StageResult,
    stage_benchmarks,
    stage_build_rules,
    stage_compute_kpis,
    stage_freeze,
    stage_ingest_manual,
    stage_render,
    stage_standardize,
    stage_validate,
    stage_verify_frozen,
)
from gauge.synthetic import DRY_FORCED_ERRORS
from gauge.synthetic_data import write_synthetic_manual_csv

DRY_CONFIG = "config/study_dry.yaml"


class DryRunError(RuntimeError):
    """A dry run was asked to do something unsafe (non-mock model, path outside dry/), or a stage
    that must work on synthetic data failed."""


def _clear_readonly_and_retry(func, path, _exc) -> None:
    """rmtree hook: OneDrive marks the folders it manages read-only, and Windows refuses to remove
    a read-only directory. Clear the flag and retry once."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


# `onerror` is deprecated from Python 3.12, where `onexc` replaces it; both hooks take 3 arguments.
_RMTREE_HOOK = "onexc" if sys.version_info >= (3, 12) else "onerror"


def _reset_dry_dir(cfg: StudyConfig) -> None:
    """Delete the dry/ working directory. Refuses anything that is not <root>/dry."""
    dry = (cfg.root / "dry").resolve()
    for rel in (cfg.paths.runs_dir, cfg.paths.raw_data_dir, cfg.paths.rules_dir):
        if not cfg.path(rel).resolve().is_relative_to(dry):
            raise DryRunError(f"dry-run config path {rel!r} is outside {dry}; refusing to reset")
    if dry.exists():
        shutil.rmtree(dry, **{_RMTREE_HOOK: _clear_readonly_and_retry})
    dry.mkdir(parents=True)


def _assert_all_mock(models: ModelsConfig) -> None:
    offenders = [m.key for m in models.enabled() if m.channel != "mock"]
    if offenders:
        raise DryRunError(
            f"dry run needs mock-only models; non-mock: {offenders}. Cursor is never called."
        )


def _seed_dry_templates(cfg: StudyConfig) -> int:
    """Copy the real prompt templates into the dry registry, so the dry run renders, freezes and
    verifies the very templates the study will use."""
    source = cfg.root / "registry" / "prompts"
    target = cfg.path(cfg.paths.prompts_registry_dir)
    missing = [name for name in TEMPLATE_FILES if not (source / name).is_file()]
    if missing:
        raise DryRunError(f"prompt templates missing from {source}: {missing}")
    target.mkdir(parents=True, exist_ok=True)
    for name in TEMPLATE_FILES:
        shutil.copyfile(source / name, target / name)
    return len(TEMPLATE_FILES)


def _mock_runner(models: ModelsConfig, truth: dict[str, str] | None = None) -> MockRunner:
    """`truth` (company code -> rule class) is the mock's stand-in for "the model mostly applies the
    rule"; real runners have no such channel."""
    return MockRunner(
        error_rates={m.name: m.error_rate for m in models.enabled() if m.error_rate is not None},
        truth=truth,
        forced_errors=DRY_FORCED_ERRORS,
    )


def _mock_truth(engine: Engine, cfg: StudyConfig, indicators: IndicatorsConfig) -> dict[str, str]:
    with session_scope(engine) as session:
        return {c: r.t2_class for c, r in load_standards(session, cfg, indicators).t2.items()}


def _stage_run_mock(
    cfg: StudyConfig, indicators: IndicatorsConfig, models: ModelsConfig, engine: Engine
) -> StageResult:
    runner = _mock_runner(models, _mock_truth(engine, cfg, indicators))
    executed = skipped = 0
    with session_scope(engine) as session:
        ctx = prepare_render(session, cfg, indicators)
        for rp in render_run_prompts(cfg, indicators, models, ctx):
            prompt, system = rp.prompt.for_channel(rp.planned.channel)
            outcome = execute_run(session, cfg, runner, rp.planned, prompt, system_prompt=system)
            executed += not outcome.skipped
            skipped += outcome.skipped
        n_runs = session.scalar(select(func.count()).select_from(Run))
        n_pos = session.scalar(select(func.count()).select_from(RunCompanyPosition))
        n_ok = session.scalar(select(func.count()).select_from(Run).where(Run.status == "success"))
    raw_files = len(list(cfg.raw_dir.glob("*.txt")))
    return StageResult(
        "run (mock)",
        "ok",
        f"{executed} executed, {skipped} skipped; {n_runs} run rows ({n_ok} success), "
        f"{n_pos} company positions, {raw_files} raw files",
    )


def run_all_dry(
    config_path: str = DRY_CONFIG,
    log: Callable[[StageResult], None] | None = None,
    root: Path | None = None,
) -> list[StageResult]:
    """Run every built stage on synthetic data with the MockRunner; list the rest as pending."""
    log = log or (lambda _r: None)
    results: list[StageResult] = []

    def record(result: StageResult) -> None:
        results.append(result)
        log(result)

    cfg = load_study(config_path, root=root)
    models = load_models(cfg)
    indicators = load_indicators(cfg)
    _assert_all_mock(models)
    _reset_dry_dir(cfg)

    engine = make_engine(cfg.database_url())
    try:  # always release the SQLite file: an open handle blocks the next reset on Windows
        tables = init_db(engine)
        with session_scope(engine) as session:
            counts = sync_registry(session, cfg, models)
        record(
            StageResult(
                "init-db",
                "ok",
                f"{len(tables)} tables; registered {counts['sectors']} sectors, "
                f"{counts['models']} models, {counts['sdg_mappings']} SDG mappings",
            )
        )

        csv_path = cfg.path(cfg.paths.raw_data_dir) / "synthetic_manual_entry.csv"
        planted = write_synthetic_manual_csv(cfg, indicators, csv_path)
        record(StageResult("synthesize", "ok", f"{csv_path.name}: {len(planted)} defects planted"))

        def must_succeed(result: StageResult) -> None:
            record(result)
            if result.status == "error":
                raise DryRunError(f"stage {result.name} failed on synthetic data:\n{result.detail}")

        must_succeed(stage_ingest_manual(engine, cfg, indicators, csv_path, synthetic=True))
        must_succeed(stage_standardize(engine, indicators))
        must_succeed(stage_validate(engine, cfg, indicators))
        must_succeed(stage_compute_kpis(engine, cfg, indicators))
        must_succeed(stage_benchmarks(engine, cfg, indicators))

        _seed_dry_templates(cfg)
        must_succeed(stage_build_rules(engine, cfg, indicators))
        must_succeed(stage_render(engine, cfg, indicators, models))
        must_succeed(stage_freeze(engine, cfg, indicators, models))
        must_succeed(stage_verify_frozen(engine, cfg, indicators, models))

        record(_stage_run_mock(cfg, indicators, models, engine))

        truth = _mock_truth(engine, cfg, indicators)
        must_succeed(
            stage_parse(engine, cfg, indicators, runner=_mock_runner(models, truth), repair=True)
        )
        must_succeed(stage_evaluate(engine, cfg, indicators))
        must_succeed(stage_stats(engine, cfg, indicators))
        must_succeed(stage_checklist(engine, cfg, indicators, models))
        must_succeed(stage_export(engine, cfg))
    finally:
        engine.dispose()
    return results
