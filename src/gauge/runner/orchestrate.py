"""The resumable run loop (spec 4.8, hard rules 5, 6 and 11).

Runs go in plan order, one fresh call each, with a pause between calls. The loop stops cleanly,
never crashes mid-way, when a usage limit is hit, when repetition 2 is not yet allowed to start,
after repeated failures, or on Ctrl-C; every finished run is already committed, so running the
same command again resumes where it stopped (a run with a successful raw file is skipped).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, select

from gauge.config import StudyConfig
from gauge.db.models import Model, Run
from gauge.db.session import session_scope
from gauge.render.runs import RunPrompt
from gauge.runner.api import ApiConfigError
from gauge.runner.cursor import CursorLaunchError
from gauge.runner.execute import execute_run
from gauge.runner.plan import PlannedRun


@dataclass
class RunSummary:
    executed: int = 0
    skipped: int = 0
    failed: int = 0
    stopped: str | None = None  # why the loop ended early; None = every selected run is done
    usage_limit: bool = False
    limited: bool = False  # stopped because --limit runs were made
    lines: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.stopped is None and self.failed == 0


def repetition_gate(
    engine_session,
    planned: PlannedRun,
    selected: list[RunPrompt],
    gap_minutes: float,
    now: datetime,
) -> str | None:
    """Why `planned` may not start yet, or None. Repetition 2 must start at least `gap_minutes`
    after repetition 1 has ended (spec 4.7), on the same channel."""
    if planned.repetition < 2 or gap_minutes <= 0:
        return None
    previous = planned.repetition - 1
    ids = [
        rp.planned.run_id
        for rp in selected
        if rp.planned.channel == planned.channel and rp.planned.repetition == previous
    ]
    if not ids:  # the selection holds no earlier repetition: look at what the database has
        return _gate_from_database(engine_session, planned, previous, gap_minutes, now)
    rows = {r.run_id: r for r in engine_session.scalars(select(Run).where(Run.run_id.in_(ids)))}
    missing = [i for i in ids if i not in rows or rows[i].status != "success"]
    if missing:
        return (
            f"repetition {previous} is not finished ({len(missing)} run(s) missing, "
            f"first: {missing[0]}); finish it, then run the same command again"
        )
    ready = max(r.finished_utc for r in rows.values()) + timedelta(minutes=gap_minutes)
    if now < ready:
        return (
            f"repetition {planned.repetition} may start at {ready:%Y-%m-%d %H:%M} UTC "
            f"({gap_minutes:g} min after repetition {previous} ended); run the same command then"
        )
    return None


def _gate_from_database(session, planned: PlannedRun, previous: int, gap_minutes, now):
    finished = [
        r.finished_utc
        for r in session.scalars(
            select(Run)
            .join(Model, Model.id == Run.model_id)
            .where(
                Model.channel == planned.channel,
                Run.repetition == previous,
                Run.is_repair.is_(False),
                Run.status == "success",
            )
        )
    ]
    if not finished:
        return (
            f"repetition {previous} has not been run on this channel; run it first, then "
            f"repetition {planned.repetition} at least {gap_minutes:g} min later"
        )
    ready = max(finished) + timedelta(minutes=gap_minutes)
    if now < ready:
        return (
            f"repetition {planned.repetition} may start at {ready:%Y-%m-%d %H:%M} UTC "
            f"({gap_minutes:g} min after repetition {previous} ended); run the same command then"
        )
    return None


def run_pending(
    engine: Engine,
    cfg: StudyConfig,
    selected: list[RunPrompt],
    runner,
    *,
    force: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    log: Callable[[str], None] = lambda _msg: None,
    max_consecutive_failures: int = 2,
    max_runs: int | None = None,
) -> RunSummary:
    """Execute `selected` (already limited to one channel and in plan order)."""
    summary = RunSummary()
    executed_any = False
    consecutive_failures = 0
    total = len(selected)

    def say(text: str) -> None:
        summary.lines.append(text)
        log(text)

    for index, rp in enumerate(selected, start=1):
        planned = rp.planned
        raw = cfg.raw_dir / f"{planned.run_id}.txt"
        with session_scope(engine) as session:
            row = session.scalar(select(Run).where(Run.run_id == planned.run_id))
            done = row is not None and row.status == "success" and raw.is_file() and not force
            gate = None if done else repetition_gate(
                session, planned, selected, cfg.runs.rep2_min_gap_minutes, now()
            )  # fmt: skip
        if done:
            summary.skipped += 1
            say(f"[{index}/{total}] {planned.run_id}: already done, skipped")
            continue
        if gate:
            summary.stopped = gate
            break
        if max_runs is not None and summary.executed + summary.failed >= max_runs:
            summary.limited = True
            break
        if executed_any and cfg.runs.pause_seconds:
            sleep(cfg.runs.pause_seconds)  # hard rule 11
        try:
            with session_scope(engine) as session:
                prompt, system = rp.prompt.for_channel(planned.channel)
                outcome = execute_run(
                    session, cfg, runner, planned, prompt, system_prompt=system, force=force
                )
        except (CursorLaunchError, ApiConfigError) as exc:
            summary.stopped = f"{planned.run_id}: cannot start: {exc}"
            break
        except KeyboardInterrupt:
            summary.stopped = "interrupted (Ctrl-C); finished runs are kept"
            break
        executed_any = True
        say(f"[{index}/{total}] {planned.run_id} ({planned.model_name}): {outcome.status}")
        if outcome.status == "success":
            summary.executed += 1
            consecutive_failures = 0
        elif outcome.status == "usage_limit":
            summary.usage_limit = True
            summary.stopped = (
                f"usage limit reached at {planned.run_id}; wait for it to reset and run the same "
                "command again"
            )
            break
        else:
            summary.failed += 1
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                summary.stopped = (
                    f"{consecutive_failures} runs in a row failed (last: {planned.run_id}); "
                    "see runs/raw/ and the run's stderr, fix the cause, then run again"
                )
                break
    return summary
