"""Execute one planned run and log it (hard rules 5 and 6).

Order of operations is fixed: call the runner, write the raw output to runs/raw/{run_id}.txt, and
only then update the DB row. Parsing happens later and never touches the raw file.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.config import StudyConfig
from gauge.db.models import Company, Condition, Model, Run, RunCompanyPosition
from gauge.runner.base import Runner, RunRequest
from gauge.runner.plan import PlannedRun


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Outcome:
    run_id: str
    skipped: bool
    status: str


def execute_run(
    session: Session,
    cfg: StudyConfig,
    runner: Runner,
    planned: PlannedRun,
    prompt: str,
    *,
    system_prompt: str | None = None,
    force: bool = False,
    repair_of: Run | None = None,
) -> Outcome:
    """Run `planned` once. A run whose DB row is `success` and whose raw file exists is skipped
    unless `force` is set. With `repair_of`, `planned` is the repair attempt of that run (its
    run_id is `<original>__repair`): it is logged as a repair and has no company positions."""
    raw_path = cfg.raw_dir / f"{planned.run_id}.txt"
    row = session.scalar(select(Run).where(Run.run_id == planned.run_id))
    if row is not None and row.status == "success" and raw_path.is_file() and not force:
        return Outcome(planned.run_id, skipped=True, status="success")

    model = session.scalar(select(Model).where(Model.key == planned.model_key))
    condition = session.scalar(select(Condition).where(Condition.code == planned.condition))
    if model is None or condition is None:
        raise LookupError("model/condition not registered: run `gauge init-db` first")
    if row is None:
        row = Run(
            run_id=planned.run_id,
            model_id=model.id,
            condition_id=condition.id,
            repetition=planned.repetition,
            seed=planned.seed,
            mode=runner.mode,
            is_repair=repair_of is not None,
            repair_of_run_id=repair_of.id if repair_of is not None else None,
        )
        session.add(row)
        session.flush()
        if repair_of is None:
            _record_positions(session, row, planned)

    request = RunRequest(
        run_id=planned.run_id,
        model=planned.model_name,
        condition=planned.condition,
        repetition=planned.repetition,
        seed=planned.seed,
        prompt=prompt,
        system_prompt=system_prompt,
        is_repair=repair_of is not None,
    )
    result = runner.run(request)

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(result.stdout, encoding="utf-8", newline="")  # raw first, parse later

    row.mode = runner.mode
    row.started_utc, row.finished_utc = result.started_utc, result.finished_utc
    row.cli_version = result.cli_version
    row.command = json.dumps(result.command)
    row.prompt_text, row.prompt_sha256 = prompt, sha256_text(prompt)
    row.system_prompt_text = system_prompt
    row.system_prompt_sha256 = sha256_text(system_prompt) if system_prompt else None
    row.raw_path = raw_path.relative_to(cfg.root).as_posix()
    row.stdout, row.stderr = result.stdout, result.stderr
    row.exit_code, row.duration_s = result.exit_code, result.duration_s
    if result.extra.get("usage_limit"):
        row.status = "usage_limit"  # the caller stops cleanly; the run is retried on resume
    else:
        row.status = "success" if result.exit_code == 0 and result.stdout.strip() else "failed"
    for attr in (
        "temperature",
        "top_p",
        "max_tokens",
        "api_seed",
        "provider_model",
        "request_json",
        "response_json",
        "rate_limit_headers",
    ):
        if attr in result.extra:
            setattr(row, attr, result.extra[attr])
    session.flush()
    return Outcome(planned.run_id, skipped=False, status=row.status)


def _record_positions(session: Session, row: Run, planned: PlannedRun) -> None:
    """Log each company's 1-based position in this run's prompt (position-effect analysis)."""
    by_code = {c.code: c.id for c in session.scalars(select(Company))}
    for position, code in enumerate(planned.company_order, start=1):
        if code in by_code:
            session.add(
                RunCompanyPosition(run_id=row.id, company_id=by_code[code], position=position)
            )
