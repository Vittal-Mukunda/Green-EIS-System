"""Library behind `gauge run`, `import-manual` and `parse` (the CLI only parses options).

Kept out of cli.py so the dry run, the tests and the commands exercise the same code.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig, ModelsConfig, StudyConfig
from gauge.db.models import Run
from gauge.db.session import session_scope
from gauge.parse.judgments import parse_run
from gauge.parse.rates import parse_rates, rates_table
from gauge.parse.repair import (
    REPAIR_SUFFIX,
    apply_repairs,
    correction_notice,
    failed_companies,
    pending_repairs,
    planned_from_row,
    run_repairs,
)
from gauge.render.prompts import RenderError
from gauge.render.runs import RunPrompt, prepare_render, render_run_prompts, write_prompt_files
from gauge.rules.freeze import verify_frozen
from gauge.runner.execute import execute_run
from gauge.runner.factory import CHANNEL_OF_MODE
from gauge.runner.manual import INSTRUCTIONS, InboxRunner, scan_inbox
from gauge.runner.plan import PlannedRun
from gauge.stages import StageResult


def select_runs(
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    models: ModelsConfig,
    ctx,
    mode: str,
    only: Iterable[str] | None = None,
) -> list[RunPrompt]:
    """The planned runs served by `mode` (channel), in plan order, optionally limited to models."""
    channel = CHANNEL_OF_MODE[mode]
    wanted = {k.strip() for k in only} if only else None
    return [
        rp
        for rp in render_run_prompts(cfg, indicators, models, ctx)
        if rp.planned.channel == channel and (wanted is None or rp.planned.model_key in wanted)
    ]


def done_run_ids(session: Session, cfg: StudyConfig, runs: Iterable[RunPrompt]) -> set[str]:
    ids = [rp.planned.run_id for rp in runs]
    rows = session.scalars(select(Run).where(Run.run_id.in_(ids), Run.status == "success"))
    return {r.run_id for r in rows if (cfg.raw_dir / f"{r.run_id}.txt").is_file()}


# ---- manual mode -------------------------------------------------------------------------
def manual_instructions(
    session: Session, cfg: StudyConfig, runs: list[RunPrompt]
) -> tuple[list[str], int]:
    """(instruction blocks for the runs still to do, number already done). Also writes the prompt
    files of every selected run so they can be pasted."""
    write_prompt_files(runs, cfg.prompts_dir)
    done = done_run_ids(session, cfg, runs)
    cfg.manual_inbox_dir.mkdir(parents=True, exist_ok=True)
    blocks = []
    for rp in runs:
        p = rp.planned
        if p.run_id in done:
            continue
        blocks.append(
            INSTRUCTIONS.format(
                run_id=p.run_id,
                model_key=p.model_key,
                model_name=p.model_name,
                condition=p.condition,
                repetition=p.repetition,
                prompt_path=(cfg.prompts_dir / f"{p.run_id}.md").relative_to(cfg.root).as_posix(),
                inbox_path=(cfg.manual_inbox_dir / f"{p.run_id}.txt")
                .relative_to(cfg.root)
                .as_posix(),
            )
        )
    return blocks, len(done)


def manual_repair_files(session: Session, cfg: StudyConfig) -> list[str]:
    """Write `runs/prompts/<run_id>__repair.md` for every manual run that needs its repair attempt;
    returns the instruction blocks."""
    blocks = []
    for run in pending_repairs(session, "manual"):
        planned = planned_from_row(session, run)
        text = (run.prompt_text or "") + correction_notice(failed_companies(session, run))
        path = cfg.prompts_dir / f"{run.run_id}{REPAIR_SUFFIX}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        blocks.append(
            INSTRUCTIONS.format(
                run_id=run.run_id + REPAIR_SUFFIX,
                model_key=planned.model_key,
                model_name=planned.model_name,
                condition=planned.condition,
                repetition=planned.repetition,
                prompt_path=path.relative_to(cfg.root).as_posix(),
                inbox_path=(cfg.manual_inbox_dir / f"{run.run_id}{REPAIR_SUFFIX}.txt")
                .relative_to(cfg.root)
                .as_posix(),
            )
        )
    return blocks


@dataclass
class ImportSummary:
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    repairs_imported: int = 0
    problems: list[str] = field(default_factory=list)


def import_manual(
    engine: Engine,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    models: ModelsConfig,
) -> ImportSummary:
    """Ingest the replies in runs/manual_inbox/ with the same logging as every other channel."""
    summary = ImportSummary()
    with session_scope(engine) as session:
        problems = verify_frozen(cfg, session, indicators, models)
        if problems:
            summary.problems += [f"frozen files do not match: {p}" for p in problems]
            return summary
        try:
            ctx = prepare_render(session, cfg, indicators)
        except RenderError as exc:
            summary.problems.append(str(exc))
            return summary
        planned = {
            rp.planned.run_id: rp for rp in select_runs(cfg, indicators, models, ctx, "manual")
        }

    listing = scan_inbox(cfg.manual_inbox_dir)
    for name in listing.ignored:
        summary.problems.append(f"{name}: ignored (replies must be named <run_id>.txt)")
    runner = InboxRunner(cfg.manual_inbox_dir)

    for run_id in listing.originals:
        rp = planned.get(run_id)
        if rp is None:
            summary.problems.append(f"{run_id}.txt: not a planned manual run")
            continue
        if models_placeholder(models, rp.planned.model_key):
            summary.problems.append(
                f"{run_id}: the model name in config/models.yaml is a placeholder; fill it in "
                "so the log names the model you used"
            )
            continue
        with session_scope(engine) as session:
            prompt, system = rp.prompt.for_channel("cursor")
            outcome = execute_run(session, cfg, runner, rp.planned, prompt, system_prompt=system)
        if outcome.skipped:
            summary.skipped += 1
        elif outcome.status == "success":
            summary.imported += 1
        else:
            summary.failed += 1
            summary.problems.append(f"{run_id}.txt: the reply file is empty")

    for original_id in listing.repairs:
        with session_scope(engine) as session:
            original = session.scalar(select(Run).where(Run.run_id == original_id))
            if original is None or original.status != "success":
                summary.problems.append(
                    f"{original_id}{REPAIR_SUFFIX}.txt: import {original_id}.txt first"
                )
                continue
            already = session.scalar(
                select(Run).where(Run.repair_of_run_id == original.id, Run.status == "success")
            )
            if already is not None:
                summary.skipped += 1
                continue
            if original.parse_status != "parse_failure":
                summary.problems.append(
                    f"{original_id}{REPAIR_SUFFIX}.txt: run `gauge parse` first (or the run needs "
                    "no repair)"
                )
                continue
            planned_repair = PlannedRun(
                **{
                    **planned_from_row(session, original).__dict__,
                    "run_id": original_id + REPAIR_SUFFIX,
                }  # fmt: skip
            )
            prompt = (original.prompt_text or "") + correction_notice(
                failed_companies(session, original)
            )
            outcome = execute_run(
                session,
                cfg,
                runner,
                planned_repair,
                prompt,
                system_prompt=original.system_prompt_text,
                repair_of=original,
            )
        if outcome.skipped:
            summary.skipped += 1
        elif outcome.status == "success":
            summary.repairs_imported += 1
        else:
            summary.failed += 1
    return summary


def models_placeholder(models: ModelsConfig, key: str) -> bool:
    return any(m.key == key and m.is_placeholder for m in models.models)


# ---- parse -------------------------------------------------------------------------------
def stage_parse(
    engine: Engine,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    *,
    runner=None,
    repair: bool = False,
    pause_seconds: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda _msg: None,
) -> StageResult:
    """Parse new replies, finish repairs that were made, and (with a runner) make the one repair
    attempt for each run that still has invalid companies. Reports parse-failure rates."""
    labels = indicators.driver_labels
    parsed = bad_runs = 0
    with session_scope(engine) as session:
        for run in session.scalars(
            select(Run).where(
                Run.is_repair.is_(False), Run.status == "success", Run.parse_status == "not_parsed"
            )
        ):
            outcome = parse_run(session, cfg, run, labels)
            parsed += 1
            bad_runs += outcome.n_bad > 0
        applied = apply_repairs(session, cfg, labels)
        attempted = repaired = 0
        stopped = ""
        if repair and runner is not None:
            r = run_repairs(
                session,
                cfg,
                runner,
                labels,
                pause_seconds=pause_seconds,
                sleep=sleep,
                log=log,
            )
            attempted, repaired = r.attempted, r.repaired
            stopped = " (stopped: usage limit)" if r.usage_limit else ""
        waiting = len(pending_repairs(session, runner.mode if runner is not None else None))
        rates = parse_rates(session)
    if not rates:
        return StageResult("parse", "ok", "no runs to parse yet")
    detail = (
        f"{parsed} runs parsed ({bad_runs} with invalid companies); "
        f"{len(applied)} earlier repairs applied; {attempted} repair attempts "
        f"({repaired} fully repaired){stopped}; {waiting} run(s) still need a repair\n"
        + rates_table(rates)
    )
    return StageResult(
        "parse",
        "ok",
        detail,
        data={"parsed": parsed, "waiting": waiting, "attempted": attempted},
    )
