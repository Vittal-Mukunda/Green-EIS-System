"""The run loop, the pre-flight checks, manual mode and the run / parse / smoke commands.

Everything is driven by a fake `agent` script, canned runners and a mocked HTTP transport: no real
model, CLI or network is used anywhere in this file.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
from sqlalchemy import select
from typer.testing import CliRunner

from gauge.cli import app
from gauge.db.models import Judgment, Run
from gauge.db.session import session_scope
from gauge.parse.repair import REPAIR_SUFFIX
from gauge.render.runs import prepare_render
from gauge.rules.freeze import manifest_path
from gauge.runcmd import (
    import_manual,
    manual_instructions,
    manual_repair_files,
    select_runs,
    stage_parse,
)
from gauge.runner.cursor import CursorLaunchError, CursorRunner, sandbox_entries
from gauge.runner.factory import preflight
from gauge.runner.orchestrate import run_pending
from helpers import CannedRunner, good_item, good_reply

cli = CliRunner()
FAKE_CFG = ["--config", "config/study_fake.yaml"]


def selected(w, mode="cli", only=None):
    with session_scope(w.engine) as s:
        ctx = prepare_render(s, w.cfg, w.ind)
        return select_runs(w.cfg, w.ind, w.models, ctx, mode, only)


def runs_in_db(w, *where):
    with session_scope(w.engine) as s:
        return list(s.scalars(select(Run).where(*where).order_by(Run.run_id)))


# ---- run_pending ---------------------------------------------------------------------------------
def test_each_channel_gets_its_own_runs_in_plan_order(fw):
    cli_runs, api_runs, manual_runs = selected(fw), selected(fw, "api"), selected(fw, "manual")
    assert len(cli_runs) == 16 and len(api_runs) == 4
    assert [r.planned.run_id for r in cli_runs] == [r.planned.run_id for r in manual_runs]
    assert {r.planned.channel for r in cli_runs} == {"cursor"}
    assert {r.planned.model_key for r in api_runs} == {"B1"}
    orders = [r.planned.order_index for r in cli_runs]
    assert orders == sorted(orders)
    only = selected(fw, "cli", ["P1", "P3"])
    assert {r.planned.model_key for r in only} == {"P1", "P3"} and len(only) == 8


def test_a_full_run_executes_in_order_with_a_pause_between_calls_only(fw):
    fw.cfg.runs.pause_seconds = 20
    sleeps = []
    runner = CannedRunner(default=good_reply(fw.codes, fw.ind.driver_labels))
    plan = selected(fw)
    summary = run_pending(fw.engine, fw.cfg, plan, runner, sleep=sleeps.append)
    assert summary.complete and summary.executed == 16 and summary.skipped == 0
    assert [c.run_id for c in runner.calls] == [r.planned.run_id for r in plan]
    assert (
        sleeps == [20.0] * 15
    )  # hard rule 11: between calls, not before the first or after the last
    first = runner.calls[0]
    assert (
        first.system_prompt is None and first.prompt == plan[0].prompt.combined
    )  # Cursor: one message
    assert first.model == plan[0].planned.model_name and first.seed == plan[0].planned.seed
    assert len(runs_in_db(fw, Run.status == "success")) == 16


def test_the_api_channel_receives_the_system_prompt_separately(fw):
    runner = CannedRunner(default=good_reply(fw.codes, fw.ind.driver_labels))
    plan = selected(fw, "api")
    run_pending(fw.engine, fw.cfg, plan, runner)
    call, rp = runner.calls[0], plan[0]
    assert call.system_prompt == rp.prompt.system and call.prompt == rp.prompt.user
    with session_scope(fw.engine) as s:
        row = s.scalar(select(Run).where(Run.run_id == rp.planned.run_id))
        assert row.system_prompt_text == rp.prompt.system and len(row.system_prompt_sha256) == 64


def test_a_second_invocation_resumes_and_skips_finished_runs(fw):
    runner = CannedRunner(default=good_reply(fw.codes, fw.ind.driver_labels))
    plan = selected(fw)
    run_pending(fw.engine, fw.cfg, plan, runner, max_runs=5)
    assert len(runner.calls) == 5
    again = run_pending(fw.engine, fw.cfg, plan, runner)
    assert again.skipped == 5 and again.executed == 11 and len(runner.calls) == 16
    final = run_pending(fw.engine, fw.cfg, plan, runner)
    assert final.skipped == 16 and final.executed == 0 and len(runner.calls) == 16
    forced = run_pending(fw.engine, fw.cfg, plan[:2], runner, force=True)
    assert forced.executed == 2 and len(runner.calls) == 18


def test_a_limit_stops_after_that_many_calls_without_being_an_error(fw):
    runner = CannedRunner(default=good_reply(fw.codes, fw.ind.driver_labels))
    summary = run_pending(fw.engine, fw.cfg, selected(fw), runner, max_runs=3)
    assert (
        summary.executed == 3 and summary.limited and summary.stopped is None and summary.complete
    )


def test_a_usage_limit_stops_cleanly_and_a_later_call_resumes(fw):
    plan = selected(fw)
    ids = [r.planned.run_id for r in plan]
    runner = CannedRunner(
        default=good_reply(fw.codes, fw.ind.driver_labels), usage_limit_on={ids[3]}
    )
    summary = run_pending(fw.engine, fw.cfg, plan, runner)
    assert summary.usage_limit and summary.executed == 3 and not summary.complete
    assert "usage limit reached at " + ids[3] in summary.stopped
    assert len(runner.calls) == 4  # nothing was attempted after the limit
    assert {r.run_id: r.status for r in runs_in_db(fw)}[ids[3]] == "usage_limit"
    runner.usage_limit_on.clear()
    done = run_pending(fw.engine, fw.cfg, plan, runner)
    assert (
        done.complete and done.skipped == 3 and done.executed == 13
    )  # the limited run was retried


def test_repeated_failures_stop_the_loop_instead_of_burning_quota(fw):
    runner = CannedRunner(default=None)  # every reply is empty
    summary = run_pending(fw.engine, fw.cfg, selected(fw), runner)
    assert summary.failed == 2 and len(runner.calls) == 2
    assert "2 runs in a row failed" in summary.stopped and not summary.complete


def test_a_success_between_failures_resets_the_failure_count(fw):
    plan = selected(fw)
    ids = [r.planned.run_id for r in plan]
    good = good_reply(fw.codes, fw.ind.driver_labels)
    replies = {i: good for i in ids}
    replies[ids[0]] = replies[ids[2]] = ""  # fail, ok, fail, ok ...
    summary = run_pending(fw.engine, fw.cfg, plan[:6], CannedRunner(replies))
    assert summary.failed == 2 and summary.executed == 4 and summary.stopped is None


def test_a_launch_problem_is_a_clean_stop_not_a_crash(fw):
    class Broken:
        mode = "cli"

        def run(self, request):
            raise CursorLaunchError("the sandbox is not empty")

    summary = run_pending(fw.engine, fw.cfg, selected(fw), Broken())
    assert "cannot start: the sandbox is not empty" in summary.stopped and summary.executed == 0


def test_ctrl_c_keeps_finished_runs(fw):
    class Interrupt(CannedRunner):
        def run(self, request):
            if len(self.calls) == 2:
                raise KeyboardInterrupt
            return super().run(request)

    runner = Interrupt(default=good_reply(fw.codes, fw.ind.driver_labels))
    summary = run_pending(fw.engine, fw.cfg, selected(fw), runner)
    assert summary.executed == 2 and "interrupted" in summary.stopped
    assert len(runs_in_db(fw, Run.status == "success")) == 2


# ---- repetition 2 must wait ----------------------------------------------------------------------
def test_repetition_2_waits_for_the_gap_after_repetition_1(fw):
    fw.cfg.runs.rep2_min_gap_minutes = 60
    plan = selected(fw)
    runner = CannedRunner(default=good_reply(fw.codes, fw.ind.driver_labels))
    start = datetime.now(UTC)
    blocked = run_pending(fw.engine, fw.cfg, plan, runner, now=lambda: start)
    assert blocked.executed == 8  # all of repetition 1, then it must wait
    assert (
        "repetition 2 may start at" in blocked.stopped
        and "60 min after repetition 1" in blocked.stopped
    )
    assert not blocked.complete
    soon = run_pending(fw.engine, fw.cfg, plan, runner, now=lambda: start + timedelta(minutes=30))
    assert soon.executed == 0 and "may start at" in soon.stopped
    later = run_pending(fw.engine, fw.cfg, plan, runner, now=lambda: start + timedelta(minutes=61))
    assert later.complete and later.executed == 8 and later.skipped == 8


def test_repetition_2_cannot_start_before_repetition_1_exists(fw):
    fw.cfg.runs.rep2_min_gap_minutes = 60
    rep2 = [r for r in selected(fw) if r.planned.repetition == 2]
    runner = CannedRunner(default=good_reply(fw.codes, fw.ind.driver_labels))
    summary = run_pending(fw.engine, fw.cfg, rep2, runner)
    assert (
        summary.executed == 0 and "repetition 1 has not been run on this channel" in summary.stopped
    )


def test_the_gap_is_not_enforced_when_it_is_zero(fw):
    assert fw.cfg.runs.rep2_min_gap_minutes == 0
    runner = CannedRunner(default=good_reply(fw.codes, fw.ind.driver_labels))
    rep2 = [r for r in selected(fw) if r.planned.repetition == 2]
    assert run_pending(fw.engine, fw.cfg, rep2, runner).executed == 8


# ---- pre-flight ----------------------------------------------------------------------------------
def cursor_runner(fw, models=None):
    models = models or fw.models
    return CursorRunner(
        models.cursor, fw.cfg.sandbox_dir, executable=[sys.executable, str(fw.script)]
    )


def run_preflight(fw, models=None, mode="cli", runner=None, client=None):
    models = models or fw.models
    plan = selected(fw, mode)
    runner = (
        runner if runner is not None else (cursor_runner(fw, models) if mode == "cli" else None)
    )
    with session_scope(fw.engine) as s:
        return preflight(s, fw.cfg, fw.ind, models, mode, plan, runner=runner, http_client=client)


def test_preflight_passes_on_a_frozen_study_with_a_working_cli(fw):
    report = run_preflight(fw)
    assert report.ok, report.problems
    assert any("9.9.9-fake" in line for line in report.info)
    assert any("longest prompt" in line and "argv" in line for line in report.info)


def test_preflight_refuses_an_unfrozen_study(fw):
    manifest_path(fw.cfg).unlink()
    assert run_preflight(fw).problems[0].startswith("not frozen")


def test_preflight_refuses_a_changed_template(fw):
    path = fw.cfg.path(fw.cfg.paths.prompts_registry_dir) / "system_v1.md"
    path.write_bytes(path.read_bytes() + b"\nsneaky\n")
    assert any("system_v1.md: changed since the freeze" in p for p in run_preflight(fw).problems)


def test_preflight_refuses_placeholder_model_names(fw):
    models = fw.models.model_copy(deep=True)
    models.models[0].name = "TODO_FILL_FROM_CURSOR_LIST"
    problems = run_preflight(fw, models).problems
    assert any("P1" in p and "placeholder" in p for p in problems)


def test_preflight_refuses_a_model_the_cli_does_not_list(fw):
    models = fw.models.model_copy(deep=True)
    models.models[1].name = "not-a-listed-model"
    assert (
        "P2: 'not-a-listed-model' is not in the Cursor CLI model list"
        in run_preflight(fw, models).problems
    )


def test_preflight_needs_a_readable_model_list(fw, monkeypatch):
    monkeypatch.setenv("FAKE_NO_LIST", "1")
    assert any("model list could not be read" in p for p in run_preflight(fw).problems)


def test_preflight_refuses_a_sandbox_that_is_not_empty(fw):
    fw.cfg.sandbox_dir.mkdir(parents=True, exist_ok=True)
    (fw.cfg.sandbox_dir / "leftover.txt").write_text("x", encoding="utf-8")
    assert any("must be empty before a run" in p for p in run_preflight(fw).problems)


def test_preflight_refuses_prompts_that_cannot_be_passed_on_the_command_line(fw):
    models = fw.models.model_copy(deep=True)
    models.cursor.argv_limit_chars = 2000
    assert any("over the 2,000 limit" in p for p in run_preflight(fw, models).problems)
    models.cursor.prompt_transport = "stdin"
    assert run_preflight(fw, models).ok


def test_preflight_for_the_api_needs_a_key_and_a_listed_free_model(fw, monkeypatch):
    listing = {"data": [{"id": "a/free-one:free"}]}
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=listing))
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert any(
        "OPENROUTER_API_KEY is not set" in p
        for p in run_preflight(fw, mode="api", client=client).problems
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    ok = run_preflight(fw, mode="api", client=client)
    assert ok.ok and "a/free-one:free is listed on openrouter" in ok.info[0]
    gone = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []}))
    )
    assert any(
        "not in OpenRouter's current model list" in p
        for p in run_preflight(fw, mode="api", client=gone).problems
    )


# ---- manual mode ---------------------------------------------------------------------------------
def write_reply(fw, run_id, items, mtime=None):
    path = fw.cfg.manual_inbox_dir / f"{run_id}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(items if isinstance(items, str) else json.dumps(items), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_manual_instructions_name_the_run_model_and_files(fw):
    plan = selected(fw, "manual")
    with session_scope(fw.engine) as s:
        blocks, done = manual_instructions(s, fw.cfg, plan)
    assert done == 0 and len(blocks) == 16
    first = plan[0].planned
    assert f"Run {first.run_id}" in blocks[0] and first.model_name in blocks[0]
    assert "NEW Cursor chat in an empty folder" in blocks[0]
    prompt_file = fw.cfg.prompts_dir / f"{first.run_id}.md"
    assert prompt_file.read_bytes().decode("utf-8") == plan[0].prompt.combined
    assert (fw.cfg.prompts_dir / "index.csv").is_file()
    assert f"manual_inbox/{first.run_id}.txt" in blocks[0]


def test_importing_replies_logs_them_like_any_other_run(fw):
    plan = selected(fw, "manual")
    good = good_reply(fw.codes, fw.ind.driver_labels)
    ts = 1_790_000_000
    for rp in plan[:2]:
        write_reply(fw, rp.planned.run_id, good, mtime=ts)
    summary = import_manual(fw.engine, fw.cfg, fw.ind, fw.models)
    assert summary.imported == 2 and summary.problems == [] and summary.failed == 0
    rows = runs_in_db(fw)
    assert len(rows) == 2
    for row, rp in zip(rows, sorted(plan[:2], key=lambda r: r.planned.run_id), strict=True):
        assert row.mode == "manual" and row.cli_version == "manual" and row.status == "success"
        assert json.loads(row.command) == ["manual-import", f"{row.run_id}.txt"]
        assert row.prompt_text == rp.prompt.combined and row.system_prompt_text is None
        assert row.started_utc == row.finished_utc == datetime.fromtimestamp(ts, UTC)
        assert (fw.cfg.raw_dir / f"{row.run_id}.txt").read_text(encoding="utf-8") == json.dumps(
            good
        )
    again = import_manual(fw.engine, fw.cfg, fw.ind, fw.models)
    assert again.imported == 0 and again.skipped == 2
    with session_scope(fw.engine) as s:
        blocks, done = manual_instructions(s, fw.cfg, plan)
    assert done == 2 and len(blocks) == 14


def test_import_reports_what_it_cannot_use_and_never_guesses(fw):
    plan = selected(fw, "manual")
    write_reply(fw, plan[0].planned.run_id, "")
    write_reply(fw, "NOT_A_RUN", "[]")
    write_reply(fw, "B1_C1_r1", "[]")  # the baseline is not a manual run
    (fw.cfg.manual_inbox_dir / "notes.md").write_text("hello", encoding="utf-8")
    (fw.cfg.manual_inbox_dir / "README.txt").write_text("ignored", encoding="utf-8")
    summary = import_manual(fw.engine, fw.cfg, fw.ind, fw.models)
    text = "\n".join(summary.problems)
    assert summary.imported == 0 and summary.failed == 1
    assert "NOT_A_RUN.txt: not a planned manual run" in text
    assert "B1_C1_r1.txt: not a planned manual run" in text
    assert "notes.md: ignored" in text and "README" not in text
    assert f"{plan[0].planned.run_id}.txt: the reply file is empty" in text


def test_import_refuses_a_placeholder_model_name_and_a_changed_freeze(fw):
    plan = selected(fw, "manual")
    write_reply(fw, plan[0].planned.run_id, good_reply(fw.codes, fw.ind.driver_labels))
    models = fw.models.model_copy(deep=True)
    for m in models.models:
        m.name = "TODO_FILL_FROM_CURSOR_LIST" if m.key == plan[0].planned.model_key else m.name
    summary = import_manual(fw.engine, fw.cfg, fw.ind, models)
    assert summary.imported == 0 and "placeholder" in summary.problems[0]
    path = fw.cfg.path(fw.cfg.paths.prompts_registry_dir) / "c1_user_v1.md"
    path.write_bytes(path.read_bytes() + b"\nedit\n")
    blocked = import_manual(fw.engine, fw.cfg, fw.ind, fw.models)
    assert blocked.imported == 0 and "frozen files do not match" in blocked.problems[0]


def test_the_manual_repair_round_trip(fw):
    plan = selected(fw, "manual")
    rid = plan[0].planned.run_id
    labels = fw.ind.driver_labels
    bad = good_reply(fw.codes, labels)
    bad[3]["t3_rating"] = 8
    write_reply(fw, rid, bad)
    write_reply(fw, rid + REPAIR_SUFFIX, good_reply(fw.codes, labels))
    early = import_manual(fw.engine, fw.cfg, fw.ind, fw.models)
    assert early.imported == 1 and early.repairs_imported == 0
    assert any("run `gauge parse` first" in p for p in early.problems)

    assert stage_parse(fw.engine, fw.cfg, fw.ind).status == "ok"
    with session_scope(fw.engine) as s:
        blocks = manual_repair_files(s, fw.cfg)
    assert len(blocks) == 1 and f"{rid}{REPAIR_SUFFIX}.txt" in blocks[0]
    repair_prompt = (fw.cfg.prompts_dir / f"{rid}{REPAIR_SUFFIX}.md").read_bytes().decode("utf-8")
    assert repair_prompt.startswith(plan[0].prompt.combined) and "# Correction" in repair_prompt
    assert "t3_rating" in repair_prompt  # it says what was wrong

    done = import_manual(fw.engine, fw.cfg, fw.ind, fw.models)
    assert done.repairs_imported == 1 and done.problems == []
    result = stage_parse(fw.engine, fw.cfg, fw.ind)
    assert "1 earlier repairs applied" in result.detail
    with session_scope(fw.engine) as s:
        assert s.scalar(select(Run.parse_status).where(Run.run_id == rid)) == "repaired"
        n_ok = len(list(s.scalars(select(Judgment).where(Judgment.parse_status == "ok"))))
    assert n_ok == 6
    repeat = import_manual(fw.engine, fw.cfg, fw.ind, fw.models)
    assert repeat.repairs_imported == 0 and repeat.skipped == 2


# ---- the commands --------------------------------------------------------------------------------
def test_run_cli_executes_a_limited_batch_then_resumes(fw):
    first = cli.invoke(app, [*FAKE_CFG, "run", "--mode", "cli", "--yes", "--limit", "3"])
    assert first.exit_code == 0, first.output
    assert "Cursor CLI:" in first.output and "3 executed, 0 skipped, 0 failed" in first.output
    rows = runs_in_db(fw)
    assert (
        len(rows) == 3
        and {r.mode for r in rows} == {"cli"}
        and {r.cli_version for r in rows} == {"9.9.9-fake"}
    )
    assert sandbox_entries(fw.cfg.sandbox_dir) == []
    rest = cli.invoke(app, [*FAKE_CFG, "run", "--mode", "cli", "--yes"])
    assert rest.exit_code == 0 and "13 executed, 3 skipped" in rest.output
    parsed = cli.invoke(app, [*FAKE_CFG, "parse"])
    assert parsed.exit_code == 0 and "16 runs parsed (0 with invalid companies)" in parsed.output
    assert "P1" in parsed.output and "final %" in parsed.output


def test_run_cli_asks_before_spending_quota(fw):
    declined = cli.invoke(app, [*FAKE_CFG, "run", "--mode", "cli"], input="n\n")
    assert declined.exit_code == 1 and "use real model calls" in declined.output
    assert runs_in_db(fw) == []


def test_run_cli_refuses_when_preflight_fails(fw, monkeypatch):
    monkeypatch.setenv("FAKE_NO_LIST", "1")
    result = cli.invoke(app, [*FAKE_CFG, "run", "--mode", "cli", "--yes"])
    assert result.exit_code == 1 and "NOT starting" in result.output
    assert "model list could not be read" in result.output and runs_in_db(fw) == []


def test_run_cli_exit_code_3_means_stopped_early(fw, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "1")
    monkeypatch.setenv("FAKE_REPLY", "")
    monkeypatch.setenv("FAKE_STDERR", "You have hit your usage limit")
    result = cli.invoke(app, [*FAKE_CFG, "run", "--mode", "cli", "--yes"])
    assert result.exit_code == 3 and "usage limit reached at" in result.output
    assert [r.status for r in runs_in_db(fw)] == ["usage_limit"]


def test_run_only_limits_the_models(fw):
    result = cli.invoke(app, [*FAKE_CFG, "run", "--mode", "cli", "--yes", "--only", "P2"])
    assert result.exit_code == 0 and "4 executed" in result.output
    assert {r.run_id.split("_")[0] for r in runs_in_db(fw)} == {"P2"}
    unknown = cli.invoke(app, [*FAKE_CFG, "run", "--mode", "cli", "--yes", "--only", "ZZ"])
    assert unknown.exit_code == 1 and "no planned runs" in unknown.output


def test_run_refuses_an_unfrozen_study(fw):
    manifest_path(fw.cfg).unlink()
    result = cli.invoke(app, [*FAKE_CFG, "run", "--mode", "cli", "--yes"])
    assert result.exit_code == 1 and "not frozen" in result.output and runs_in_db(fw) == []


def test_run_api_without_a_key_refuses_before_any_call(fw, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = cli.invoke(app, [*FAKE_CFG, "run", "--mode", "api", "--yes"])
    assert result.exit_code == 1 and "OPENROUTER_API_KEY is not set" in result.output


def test_run_manual_prints_instructions_and_import_manual_ingests(fw):
    shown = cli.invoke(app, [*FAKE_CFG, "run", "--mode", "manual", "--only", "P1"])
    assert shown.exit_code == 0 and "4 manual run(s) to do, 0 already imported" in shown.output
    assert "Paste the whole of" in shown.output and "gpt-fake-1" in shown.output
    rid = selected(fw, "manual", ["P1"])[0].planned.run_id
    write_reply(fw, rid, good_reply(fw.codes, fw.ind.driver_labels))
    imported = cli.invoke(app, [*FAKE_CFG, "import-manual"])
    assert (
        imported.exit_code == 0
        and "1 runs imported" in imported.output
        and "next: gauge parse" in imported.output
    )
    after = cli.invoke(app, [*FAKE_CFG, "run", "--mode", "manual", "--only", "P1"])
    assert "3 manual run(s) to do, 1 already imported" in after.output


def test_import_manual_exit_code_reflects_problems(fw):
    write_reply(fw, "NOT_A_RUN", "[]")
    result = cli.invoke(app, [*FAKE_CFG, "import-manual"])
    assert result.exit_code == 1 and "not a planned manual run" in result.output


def test_parse_repair_through_the_cli_channel(fw, monkeypatch):
    plan = selected(fw)
    bad = good_reply(fw.codes, fw.ind.driver_labels)
    bad[0]["t2_class"] = "Maybe"
    runner = CannedRunner(
        {plan[0].planned.run_id: bad}, default=good_reply(fw.codes, fw.ind.driver_labels)
    )
    runner.mode = "cli"  # the runs are logged as made through the Cursor CLI
    run_pending(fw.engine, fw.cfg, plan[:2], runner)
    shown = cli.invoke(app, [*FAKE_CFG, "parse"])
    assert shown.exit_code == 0 and "1 run(s) still need a repair" in shown.output
    # the repair goes through the (fake) Cursor CLI, which answers validly for every company
    fixed = cli.invoke(app, [*FAKE_CFG, "parse", "--repair", "--mode", "cli", "--yes"])
    assert fixed.exit_code == 0 and "1 repair attempts (1 fully repaired)" in fixed.output
    rows = {r.run_id: r for r in runs_in_db(fw)}
    repair = rows[plan[0].planned.run_id + REPAIR_SUFFIX]
    assert repair.is_repair and repair.mode == "cli" and repair.status == "success"
    assert rows[plan[0].planned.run_id].parse_status == "repaired"


def test_parse_repair_needs_a_mode(fw):
    result = cli.invoke(app, [*FAKE_CFG, "parse", "--repair"])
    assert result.exit_code != 0


def test_parse_repair_manual_writes_prompt_files(fw):
    plan = selected(fw, "manual")
    rid = plan[0].planned.run_id
    bad = good_reply(fw.codes, fw.ind.driver_labels)
    del bad[1]
    write_reply(fw, rid, bad)
    assert cli.invoke(app, [*FAKE_CFG, "import-manual"]).exit_code == 0
    result = cli.invoke(app, [*FAKE_CFG, "parse", "--repair", "--mode", "manual"])
    assert result.exit_code == 0 and "1 repair prompt(s) written" in result.output
    assert (fw.cfg.prompts_dir / f"{rid}{REPAIR_SUFFIX}.md").is_file()
    none = cli.invoke(app, [*FAKE_CFG, "parse", "--repair", "--mode", "manual"])
    assert "1 repair prompt(s) written" in none.output  # still pending until a reply is imported


# ---- the smoke test ------------------------------------------------------------------------------
def test_smoke_runs_one_call_on_synthetic_data_and_touches_no_run_table(fw):
    result = cli.invoke(app, [*FAKE_CFG, "smoke", "--channel", "cli", "--model", "P1", "--yes"])
    assert result.exit_code == 0, result.output
    assert "SMOKE TEST PASSED" in result.output and "valid companies 2/2" in result.output
    assert "transport argv" in result.output and "2 synthetic companies" in result.output
    saved = sorted((fw.cfg.runs_dir / "smoke").glob("P1_*.txt"))
    assert len(saved) == 1 and json.loads(saved[0].read_text(encoding="utf-8"))[0]["company_code"]
    assert runs_in_db(fw) == []  # nothing entered the study's run table
    assert sandbox_entries(fw.cfg.sandbox_dir) == []


def test_smoke_reports_a_bad_reply_as_a_failure(fw, monkeypatch):
    monkeypatch.setenv("FAKE_REPLY", "Sorry, I cannot do that.")
    result = cli.invoke(app, [*FAKE_CFG, "smoke", "--channel", "cli", "--model", "P2", "--yes"])
    assert (
        result.exit_code == 1
        and "SMOKE TEST FAILED" in result.output
        and "JSON found: False" in result.output
    )


def test_smoke_can_try_the_stdin_transport_without_editing_the_config(fw):
    result = cli.invoke(
        app,
        [*FAKE_CFG, "smoke", "--channel", "cli", "--model", "P1", "--transport", "stdin", "--yes"],
    )
    assert result.exit_code == 0 and "transport stdin" in result.output
    seen = json.loads((fw.root / "invocation.json").read_text(encoding="utf-8"))
    assert "## " in seen["stdin"] and seen["argv"][-1] == str(fw.cfg.sandbox_dir)


def test_smoke_refuses_unknown_models_wrong_channels_and_unlisted_names(fw):
    base = [*FAKE_CFG, "smoke", "--yes"]
    assert cli.invoke(app, [*base, "--channel", "cli", "--model", "ZZ"]).exit_code == 1
    wrong = cli.invoke(app, [*base, "--channel", "cli", "--model", "B1"])
    assert wrong.exit_code == 1 and "is not a cursor-channel model" in wrong.output
    bad_transport = cli.invoke(
        app, [*base, "--channel", "cli", "--model", "P1", "--transport", "pipe"]
    )
    assert bad_transport.exit_code != 0


def test_smoke_asks_first(fw):
    declined = cli.invoke(
        app, [*FAKE_CFG, "smoke", "--channel", "cli", "--model", "P1"], input="n\n"
    )
    assert declined.exit_code == 1 and "Make ONE real call" in declined.output
    assert not (fw.cfg.runs_dir / "smoke").exists()


def test_the_real_config_cannot_be_smoke_tested_until_names_are_filled_in(proj):
    result = cli.invoke(app, ["smoke", "--channel", "cli", "--model", "P1", "--yes"])
    assert result.exit_code == 1 and "fill in the exact model name" in result.output


def test_good_item_helper_matches_the_schema():
    from gauge.schemas import CompanyJudgment

    assert CompanyJudgment.model_validate(good_item("AAA-01")).t3_rating == 3
    assert SimpleNamespace(a=1).a == 1  # keeps the import used by fixtures above
