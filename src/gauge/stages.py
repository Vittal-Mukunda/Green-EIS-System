"""Data-pipeline stages, each returning a one-line StageResult.

Both the CLI commands and the dry run call these, so they exercise exactly the same code.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import Engine

from gauge.benchmark.compute import compute_benchmarks
from gauge.config import IndicatorsConfig, ModelsConfig, StudyConfig
from gauge.db.session import session_scope
from gauge.ingest.manual import IngestError, load_manual
from gauge.ingest.pool import load_pool
from gauge.ingest.xbrl_load import load_xbrl
from gauge.ingest.xbrl_map import load_overrides, load_xbrl_mapping
from gauge.kpi.engine import compute_kpis
from gauge.quality.validators import run_validators
from gauge.render.evidence import EvidenceError, load_evidence
from gauge.render.prompts import RenderError
from gauge.render.runs import prepare_render, render_run_prompts, write_prompt_files
from gauge.rules.build import (
    RuleFileError,
    build_t2_rule,
    build_t3_rule,
    t2_path,
    t3_path,
    write_rule,
)
from gauge.rules.freeze import (
    FreezeError,
    ensure_not_frozen,
    freeze,
    register_files,
    verify_frozen,
)
from gauge.standardize.run import NotStandardizedError, standardize_indicators


@dataclass
class StageResult:
    name: str
    status: str  # ok | pending | error
    detail: str
    data: dict = field(default_factory=dict)  # machine-readable counts


def stage_ingest_manual(
    engine: Engine,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    path: Path,
    *,
    retrieved_on: date | None = None,
    synthetic: bool = False,
) -> StageResult:
    try:
        with session_scope(engine) as session:
            s = load_manual(
                session, cfg, indicators, path, retrieved_on=retrieved_on, synthetic=synthetic
            )
    except IngestError as exc:
        return StageResult("ingest", "error", f"nothing loaded:\n{exc}")
    note = f"; {len(s.warnings)} warnings" if s.warnings else ""
    return StageResult(
        "ingest",
        "ok",
        f"{s.companies_created} new companies, {s.reports_touched} reports, "
        f"{s.values_written} values{note}",
    )


def stage_ingest_xbrl(
    engine: Engine,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    paths: list[Path],
    *,
    retrieved_on: date | None = None,
) -> StageResult:
    """Load BRSR XBRL filings (files or folders). Problems are listed per filing."""
    mapping = load_xbrl_mapping(cfg, indicators)
    overrides = load_overrides(cfg, indicators)
    pool = load_pool(cfg.root)
    with session_scope(engine) as session:
        s = load_xbrl(
            session, cfg, indicators, mapping, overrides, pool, paths, retrieved_on=retrieved_on
        )
    lines = [
        f"{len(s.outcomes)} filings: {s.reports_written} company-years written, "
        f"{s.skipped} skipped, {len(s.refused)} refused; {s.companies_created} new companies; "
        f"{s.restatements} restatement flags"
    ]
    for o in s.outcomes:
        label = o.name or o.path.name
        if o.refused:
            lines.append(f"  REFUSED {label}: {o.refused}")
        for fy, reason in o.skipped.items():
            lines.append(f"  SKIPPED {label} {fy}: {reason}")
        if o.kept:
            kept = ", ".join(o.kept)
            lines.append(f"  kept existing {label} {kept} (higher-priority report exists)")
    problem = bool(s.refused or s.skipped)
    return StageResult(
        "ingest",
        "error" if problem else "ok",
        "\n".join(lines),
        data={"written": s.reports_written, "skipped": s.skipped, "refused": len(s.refused)},
    )


def stage_standardize(engine: Engine, indicators: IndicatorsConfig) -> StageResult:
    with session_scope(engine) as session:
        s = standardize_indicators(session, indicators)
    detail = (
        f"{s.converted} converted, {s.already_canonical} already canonical, "
        f"{s.skipped_done} done before"
    )
    if s.errors:
        return StageResult(
            "standardize", "error", detail + f", {len(s.errors)} errors:\n" + "\n".join(s.errors)
        )
    return StageResult("standardize", "ok", detail)


def stage_validate(engine: Engine, cfg: StudyConfig, indicators: IndicatorsConfig) -> StageResult:
    try:
        with session_scope(engine) as session:
            summary = run_validators(session, cfg, indicators)
    except NotStandardizedError as exc:
        return StageResult("validate", "error", str(exc))
    by_rule = Counter(f.rule for f in summary.flags)
    rules = ", ".join(f"{rule}={n}" for rule, n in sorted(by_rule.items())) or "none"
    return StageResult(
        "validate",
        "ok",
        f"{summary.count('error')} errors, {summary.count('warning')} warnings ({rules})",
        data={"errors": summary.count("error"), "warnings": summary.count("warning")},
    )


def stage_compute_kpis(
    engine: Engine, cfg: StudyConfig, indicators: IndicatorsConfig
) -> StageResult:
    try:
        with session_scope(engine) as session:
            s = compute_kpis(session, cfg, indicators)
    except NotStandardizedError as exc:
        return StageResult("compute-kpis", "error", str(exc))
    return StageResult(
        "compute-kpis",
        "ok",
        f"{s.values_written} KPI values, {s.changes_computed} 2-year changes, "
        f"{len(s.flags)} KPI flags",
    )


def stage_benchmarks(engine: Engine, cfg: StudyConfig, indicators: IndicatorsConfig) -> StageResult:
    with session_scope(engine) as session:
        s = compute_benchmarks(session, cfg, [k.code for k in indicators.kpis])
    if s.no_included_companies:
        return StageResult(
            "benchmarks",
            "ok",
            "no companies are `included` yet; benchmarks need the sample selection (Phase 3)",
        )
    detail = f"{s.written} sector benchmarks"
    if s.skipped:
        detail += f"; {len(s.skipped)} skipped for n < 3 (e.g. {s.skipped[0]})"
    return StageResult("benchmarks", "ok", detail)


# ---- Phase 4: rules, prompts, freeze -----------------------------------------------------
def provisional_dir(cfg: StudyConfig) -> Path:
    """Where previews built from candidate companies go. Never the registry, never frozen."""
    return cfg.runs_dir / "provisional"


def stage_build_rules(
    engine: Engine,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    *,
    provisional: bool = False,
    force: bool = False,
) -> StageResult:
    """Write the T2 rule (with cut-points from the benchmarks) and the T3 update rule.

    `provisional` previews the T2 rule from candidate companies into runs/provisional/ and touches
    neither the registry nor the database.
    """
    try:
        with session_scope(engine) as session:
            if not provisional:
                ensure_not_frozen(session, cfg, force=force)
            evidence = load_evidence(
                session, cfg, indicators, provisional=provisional, with_trend=False
            )
            t2 = build_t2_rule(evidence, cfg, indicators)
            if provisional:
                path = provisional_dir(cfg) / "t2_v1.yaml"
                write_rule(t2, path)
                where = f"{path} (PROVISIONAL preview, not the registry)"
            else:
                write_rule(t2, t2_path(cfg))
                write_rule(build_t3_rule(evidence, indicators), t3_path(cfg))
                register_files(session, cfg)
                where = f"{t2_path(cfg)} and {t3_path(cfg)}"
    except (EvidenceError, RuleFileError, FreezeError) as exc:
        return StageResult("build-rules", "error", str(exc))
    sizes = sorted({next(iter(c.values())).n for c in t2.cut_points.values()})
    return StageResult(
        "build-rules",
        "ok",
        f"T2 cut-points for {len(t2.cut_points)} sectors x {len(t2.metrics)} KPIs "
        f"(n = {', '.join(map(str, sizes))}); wrote {where}",
        data={"provisional": provisional},
    )


def stage_render(
    engine: Engine,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    models: ModelsConfig,
    *,
    provisional: bool = False,
    conditions: tuple[str, ...] = ("C1", "C2"),
) -> StageResult:
    """Render the prompt of every planned run to runs/prompts/ (or runs/provisional/prompts/)."""
    try:
        with session_scope(engine) as session:
            ctx = prepare_render(
                session, cfg, indicators, provisional=provisional, with_trend="C2" in conditions
            )
            run_prompts = render_run_prompts(cfg, indicators, models, ctx, conditions=conditions)
    except RenderError as exc:
        return StageResult("render", "error", str(exc))
    folder = provisional_dir(cfg) / "prompts" if provisional else cfg.prompts_dir
    write_prompt_files(run_prompts, folder)
    sizes = [len(rp.prompt.combined) for rp in run_prompts]
    return StageResult(
        "render",
        "ok",
        f"{len(run_prompts)} prompts for {len(ctx.evidence.companies)} companies "
        f"({min(sizes):,}-{max(sizes):,} characters) written to {folder}; "
        "identity check passed" + ("; PROVISIONAL" if provisional else ""),
        data={"prompts": len(run_prompts)},
    )


def stage_freeze(
    engine: Engine,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    models: ModelsConfig,
    *,
    force: bool = False,
) -> StageResult:
    try:
        with session_scope(engine) as session:
            r = freeze(session, cfg, indicators, models, force=force)
    except FreezeError as exc:
        return StageResult("freeze", "error", str(exc))
    return StageResult(
        "freeze",
        "ok",
        f"{len(r.files)} files and {r.prompts} prompts ({r.companies} companies) recorded in "
        f"{r.manifest}",
    )


def stage_verify_frozen(
    engine: Engine, cfg: StudyConfig, indicators: IndicatorsConfig, models: ModelsConfig
) -> StageResult:
    """The runner's pre-flight check: files and every rendered prompt match the manifest."""
    with session_scope(engine) as session:
        problems = verify_frozen(cfg, session, indicators, models)
    if problems:
        return StageResult("verify-freeze", "error", "\n  ".join(["NOT intact:", *problems]))
    return StageResult("verify-freeze", "ok", "frozen files and all rendered prompts match")
