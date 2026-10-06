"""The single repair attempt (spec 4.8) and its bookkeeping.

When a run's reply has invalid or missing companies, the run is repeated ONCE as a fresh session
(hard rule 2: no shared conversation) with the original prompt, unchanged, followed by a short
correction notice that says what was wrong. The repeat is logged as its own run,
`<run_id>__repair`, linked to the original. Only the companies that were invalid in the first reply
take their values from the repair; companies that were valid keep their first-attempt values, so
the repair never resamples (and so never disturbs the repeatability of) answers that were already
usable. A company still invalid afterwards stays `parse_failure`. There is no second attempt.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.config import StudyConfig
from gauge.db.models import Company, Condition, Judgment, Model, Run
from gauge.parse.judgments import read_raw, run_company_codes, store_judgments, validate_response
from gauge.runner.base import Runner
from gauge.runner.execute import execute_run
from gauge.runner.plan import PlannedRun

REPAIR_SUFFIX = "__repair"
MAX_LISTED = 5


def correction_notice(errors: dict[str, str]) -> str:
    """The text appended to the original prompt. States the problems, adds no new information."""
    unique = sorted(set(errors.values()))
    if len(unique) == 1:
        what = unique[0]
    else:
        shown = [f"- {code}: {msg}" for code, msg in sorted(errors.items())[:MAX_LISTED]]
        if len(errors) > MAX_LISTED:
            shown.append(f"- and {len(errors) - MAX_LISTED} more")
        what = "\n" + "\n".join(shown)
    return (
        "\n\n# Correction\n\n"
        f"A previous answer to this task could not be used: {what}\n\n"
        "Answer the whole task again from the beginning, following the instructions exactly. "
        "Return only the JSON array, with one object for every company in the evidence.\n"
    )


def planned_from_row(session: Session, run: Run) -> PlannedRun:
    """Rebuild the plan entry of a logged run (the repair reuses its model, seed and order)."""
    model = session.get(Model, run.model_id)
    condition = session.get(Condition, run.condition_id)
    return PlannedRun(
        run_id=run.run_id,
        model_key=model.key,
        model_name=model.name,
        role=model.role,
        channel=model.channel,
        condition=condition.code,
        repetition=run.repetition,
        seed=run.seed,
        order_index=0,
        min_gap_minutes=0.0,
        company_order=tuple(run_company_codes(session, run)),
    )


def failed_companies(session: Session, run: Run) -> dict[str, str]:
    """Company code -> first-attempt error, for the run's judgments that are still invalid."""
    rows = session.execute(
        select(Company.code, Judgment.parse_error)
        .join(Judgment, Judgment.company_id == Company.id)
        .where(Judgment.run_id == run.id, Judgment.parse_status == "parse_failure")
    )
    return {code: error or "invalid" for code, error in rows}


def _repair_row(session: Session, run: Run) -> Run | None:
    return session.scalar(select(Run).where(Run.repair_of_run_id == run.id))


def pending_repairs(session: Session, mode: str | None = None) -> list[Run]:
    """Successful original runs with invalid companies and no usable repair attempt yet."""
    out = []
    for run in session.scalars(
        select(Run).where(
            Run.is_repair.is_(False), Run.status == "success", Run.parse_status == "parse_failure"
        )
    ):
        repair = _repair_row(session, run)
        if repair is not None and repair.status == "success":
            continue  # the one attempt was made; apply_repairs finishes it
        if mode is None or run.mode == mode:
            out.append(run)
    return sorted(out, key=lambda r: r.run_id)


def apply_repair(
    session: Session, cfg: StudyConfig, original: Run, repair: Run, driver_labels: Sequence[str]
) -> bool:
    """Copy the repair's valid answers for the originally invalid companies into the original run's
    judgments and settle both parse statuses. Returns True if every company is now valid."""
    first_errors = failed_companies(session, original)
    codes = run_company_codes(session, original)
    check = validate_response(read_raw(cfg, repair), codes, driver_labels)
    store_judgments(session, original, check, only=list(first_errors), repaired_from=first_errors)
    still = {
        code: check.results[code].error or "invalid"
        for code in first_errors
        if check.results[code].judgment is None
    }
    for code, error in still.items():
        row = session.scalar(
            select(Judgment)
            .join(Company, Company.id == Judgment.company_id)
            .where(Judgment.run_id == original.id, Company.code == code)
        )
        row.parse_error = f"after repair: {error}"
    original.parse_status = "parse_failure" if still else "repaired"
    repair.parse_status = "parse_failure" if still else "ok"
    session.flush()
    return not still


def apply_repairs(
    session: Session, cfg: StudyConfig, driver_labels: Sequence[str]
) -> list[tuple[str, bool]]:
    """Finish every repair attempt that succeeded but is not yet applied (also after a manual
    import). Returns (original run_id, all valid) for each."""
    done = []
    for repair in session.scalars(
        select(Run).where(
            Run.is_repair.is_(True), Run.status == "success", Run.parse_status == "not_parsed"
        )
    ):
        original = session.get(Run, repair.repair_of_run_id)
        if original is None:
            continue
        done.append((original.run_id, apply_repair(session, cfg, original, repair, driver_labels)))
    return done


@dataclass
class RepairSummary:
    attempted: int = 0
    repaired: int = 0
    still_invalid: int = 0
    failed_calls: int = 0
    usage_limit: bool = False
    details: list[str] = field(default_factory=list)


def run_repairs(
    session: Session,
    cfg: StudyConfig,
    runner: Runner,
    driver_labels: Sequence[str],
    *,
    pause_seconds: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda _msg: None,
    only_run_ids: Sequence[str] | None = None,
) -> RepairSummary:
    """Make the one repair attempt for every run that needs it and has `runner`'s channel."""
    summary = RepairSummary()
    first = True
    for original in pending_repairs(session, runner.mode):
        if only_run_ids is not None and original.run_id not in only_run_ids:
            continue
        if not first and pause_seconds:
            sleep(pause_seconds)
        first = False
        errors = failed_companies(session, original)
        planned = planned_from_row(session, original)
        repair_planned = PlannedRun(
            **{**planned.__dict__, "run_id": original.run_id + REPAIR_SUFFIX}
        )
        prompt = (original.prompt_text or "") + correction_notice(errors)
        outcome = execute_run(
            session,
            cfg,
            runner,
            repair_planned,
            prompt,
            system_prompt=original.system_prompt_text,
            repair_of=original,
        )
        summary.attempted += 1
        if outcome.status == "usage_limit":
            summary.usage_limit = True
            log(f"usage limit reached during {repair_planned.run_id}; resume later")
            break
        if outcome.status != "success":
            summary.failed_calls += 1
            log(f"{repair_planned.run_id}: the call failed; it will be retried next time")
            continue
        repair = _repair_row(session, original)
        ok = apply_repair(session, cfg, original, repair, driver_labels)
        summary.repaired += ok
        summary.still_invalid += not ok
        summary.details.append(f"{original.run_id}: {'repaired' if ok else 'still invalid'}")
        log(summary.details[-1])
    return summary
