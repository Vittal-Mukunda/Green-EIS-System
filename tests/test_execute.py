from __future__ import annotations

import json
from datetime import UTC

import pytest
from sqlalchemy import select

from gauge.config import load_models, load_study
from gauge.db.models import Company, Run, RunCompanyPosition
from gauge.db.session import init_db, make_engine, session_scope
from gauge.registry import sync_registry
from gauge.runner.base import RunResult
from gauge.runner.execute import execute_run, sha256_text
from gauge.runner.mock import MockRunner
from gauge.runner.plan import plan_runs
from gauge.synthetic import placeholder_prompt, seed_synthetic_companies


@pytest.fixture
def world(proj):
    cfg = load_study("config/study_dry.yaml")
    models = load_models(cfg)
    engine = make_engine(cfg.database_url())
    init_db(engine)
    with session_scope(engine) as session:
        sync_registry(session, cfg, models)
        seed_synthetic_companies(session, cfg)
    plan = plan_runs(cfg, models, cfg.masked_codes())
    yield cfg, engine, plan
    engine.dispose()


def prompt_for(planned) -> str:
    return placeholder_prompt(planned.condition, list(planned.company_order))


def test_execute_logs_every_rule_5_field(world):
    cfg, engine, plan = world
    planned = plan[0]
    prompt = prompt_for(planned)
    with session_scope(engine) as session:
        outcome = execute_run(session, cfg, MockRunner(), planned, prompt)
    assert not outcome.skipped and outcome.status == "success"

    raw = cfg.raw_dir / f"{planned.run_id}.txt"
    assert raw.is_file()
    with session_scope(engine) as session:
        row = session.scalar(select(Run).where(Run.run_id == planned.run_id))
        assert row.stdout == raw.read_text(encoding="utf-8")  # raw file == logged stdout
        assert row.raw_path == f"dry/runs/raw/{planned.run_id}.txt"
        assert row.prompt_text == prompt and row.prompt_sha256 == sha256_text(prompt)
        assert row.seed == planned.seed and row.repetition == planned.repetition
        assert row.mode == "mock" and row.exit_code == 0 and row.duration_s == 0.0
        assert json.loads(row.command)[0] == "mock-runner"
        assert row.cli_version and row.stderr == ""
        assert row.started_utc.tzinfo is not None
        assert row.started_utc.utcoffset().total_seconds() == 0 and row.started_utc.tzinfo == UTC
        assert row.finished_utc >= row.started_utc


def test_company_positions_are_logged_from_the_prompt_order(world):
    cfg, engine, plan = world
    planned = plan[3]
    with session_scope(engine) as session:
        execute_run(session, cfg, MockRunner(), planned, prompt_for(planned))
    with session_scope(engine) as session:
        run = session.scalar(select(Run).where(Run.run_id == planned.run_id))
        rows = session.execute(
            select(Company.code, RunCompanyPosition.position)
            .join(Company, Company.id == RunCompanyPosition.company_id)
            .where(RunCompanyPosition.run_id == run.id)
            .order_by(RunCompanyPosition.position)
        ).all()
    assert [code for code, _ in rows] == list(planned.company_order)
    assert [pos for _, pos in rows] == list(range(1, 7))


def test_second_call_is_skipped_and_force_reruns(world):
    cfg, engine, plan = world
    planned = plan[0]
    prompt = prompt_for(planned)
    raw = cfg.raw_dir / f"{planned.run_id}.txt"
    with session_scope(engine) as session:
        execute_run(session, cfg, MockRunner(), planned, prompt)
    first_mtime = raw.stat().st_mtime_ns

    class Exploding:
        mode = "mock"

        def run(self, request):
            raise AssertionError("an existing successful run must not be executed again")

    with session_scope(engine) as session:
        again = execute_run(session, cfg, Exploding(), planned, prompt)
    assert again.skipped and raw.stat().st_mtime_ns == first_mtime

    with session_scope(engine) as session:
        forced = execute_run(session, cfg, MockRunner(), planned, prompt, force=True)
        assert not forced.skipped
        assert session.scalar(select(Run).where(Run.run_id == planned.run_id)) is not None
        assert len(session.scalars(select(Run)).all()) == 1  # re-run updates the row, no duplicate


def test_failed_run_keeps_raw_output_and_is_retried(world):
    cfg, engine, plan = world
    planned = plan[0]

    class Failing:
        mode = "mock"

        def run(self, request):
            now = MockRunner().run(request).started_utc
            return RunResult(
                stdout="partial",
                stderr="usage limit reached",
                exit_code=1,
                duration_s=1.5,
                command=["x"],
                cli_version="v",
                started_utc=now,
                finished_utc=now,
            )

    with session_scope(engine) as session:
        outcome = execute_run(session, cfg, Failing(), planned, prompt_for(planned))
    assert outcome.status == "failed"
    assert (cfg.raw_dir / f"{planned.run_id}.txt").read_text(encoding="utf-8") == "partial"

    with session_scope(engine) as session:
        retry = execute_run(session, cfg, MockRunner(), planned, prompt_for(planned))
    assert not retry.skipped and retry.status == "success"


def test_unregistered_model_is_an_error(proj):
    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    init_db(engine)  # schema only: no sync_registry
    plan = plan_runs(cfg, load_models(cfg), cfg.masked_codes())
    with pytest.raises(LookupError, match="init-db"), session_scope(engine) as session:
        execute_run(session, cfg, MockRunner(), plan[0], "p")
    engine.dispose()
