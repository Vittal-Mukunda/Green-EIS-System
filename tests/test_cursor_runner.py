"""The Cursor CLI channel, tested against a FAKE `agent` (a small Python script).

The real Cursor CLI is never started, and nothing here proves anything about its real behaviour:
see docs/RUNNER.md."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from gauge.config import CursorParams
from gauge.db.models import Run
from gauge.db.session import session_scope
from gauge.runner.base import RunRequest
from gauge.runner.cursor import (
    CursorLaunchError,
    CursorRunner,
    argv_length,
    argv_limit,
    model_is_listed,
    resolve_executable,
    sandbox_entries,
    strip_ansi,
    sweep_sandbox,
)
from gauge.runner.execute import execute_run
from gauge.runner.plan import PlannedRun
from helpers import FAKE_AGENT

PROMPT = 'Instructions: "quote" and ₹ crore | a | b |\nsecond line with  double  spaces\n'


@pytest.fixture
def fake(tmp_path, monkeypatch):
    script = tmp_path / "fake_agent.py"
    script.write_text(FAKE_AGENT, encoding="utf-8")
    log = tmp_path / "invocation.json"
    monkeypatch.setenv("FAKE_LOG", str(log))
    for var in (
        "FAKE_LEAVE",
        "FAKE_SLEEP",
        "FAKE_STDERR",
        "FAKE_REPLY",
        "FAKE_EXIT",
        "FAKE_NO_LIST",
    ):
        monkeypatch.delenv(var, raising=False)
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    def make(**params) -> CursorRunner:
        return CursorRunner(
            CursorParams(**params), sandbox, executable=[sys.executable, str(script)]
        )

    make.log = lambda: json.loads(log.read_text(encoding="utf-8"))
    make.sandbox = sandbox
    make.script = script
    return make


def request(prompt=PROMPT, model="gpt-fake-1", **kw) -> RunRequest:
    return RunRequest("P1_C1_r1", model, "C1", 1, 5, prompt, **kw)


# ---- the command ---------------------------------------------------------------------------------
def test_only_documented_flags_are_used_and_the_prompt_is_the_last_argument(fake):
    runner = fake()
    result = runner.run(request())
    seen = fake.log()
    assert seen["argv"] == [
        "-p",
        "--output-format",
        "text",
        "--mode",
        "ask",
        "--model",
        "gpt-fake-1",
        "--workspace",
        str(fake.sandbox),
        PROMPT,
    ]
    assert result.exit_code == 0 and result.stdout == '[{"company_code": "X"}]'


def test_the_process_runs_inside_the_empty_sandbox_never_the_project(fake, repo_root):
    fake().run(request())
    seen = fake.log()
    assert Path(seen["cwd"]).resolve() == fake.sandbox.resolve()
    assert seen["sandbox_at_start"] == []  # hard rule 1: nothing was there to read
    assert Path(seen["cwd"]).resolve() != repo_root.resolve()
    assert sandbox_entries(fake.sandbox) == []


def test_the_logged_command_replaces_the_prompt_by_its_length_and_hash(fake):
    result = fake().run(request())
    last = result.command[-1]
    assert last.startswith(f"<prompt: {len(PROMPT)} chars, sha256 ")
    assert PROMPT not in " ".join(result.command)
    assert result.command[-2] == str(fake.sandbox) and "--workspace" in result.command


def test_stdin_transport_sends_the_prompt_on_stdin_and_not_in_the_command(fake):
    result = fake(prompt_transport="stdin").run(request())
    seen = fake.log()
    assert seen["stdin"] == PROMPT and PROMPT not in seen["argv"]
    assert seen["argv"][-1] == str(fake.sandbox)  # the last argument is now --workspace's value
    assert result.command[-1] == f"<stdin: prompt of {len(PROMPT)} chars>"


def test_extra_args_are_appended_before_the_prompt(fake):
    fake(extra_args=["--some-verified-flag"]).run(request())
    argv = fake.log()["argv"]
    assert argv[-2:] == ["--some-verified-flag", PROMPT]


def test_the_cli_version_is_read_once_and_logged(fake):
    runner = fake()
    assert runner.version() == "9.9.9-fake"
    assert runner.run(request()).cli_version == "9.9.9-fake"
    assert sandbox_entries(fake.sandbox) == []


def test_a_fresh_process_per_run_means_no_session_flags(fake):
    fake().run(request())
    argv = fake.log()["argv"]
    assert not {"--resume", "--continue", "resume", "-c"} & set(argv)


# ---- refusing to start ---------------------------------------------------------------------------
def test_a_non_empty_sandbox_stops_the_run_before_any_process(fake):
    (fake.sandbox / "notes.txt").write_text("a project file", encoding="utf-8")
    with pytest.raises(CursorLaunchError, match="not empty"):
        fake().run(request())
    assert not Path(fake.script.parent / "invocation.json").exists()  # nothing was started


def test_a_prompt_too_long_for_the_command_line_is_refused_before_any_process(fake):
    runner = fake(argv_limit_chars=2000)
    with pytest.raises(CursorLaunchError, match="over the 2,000 limit") as exc:
        runner.run(request(prompt="x" * 5000))
    assert "--mode manual" in str(exc.value) and "stdin" in str(exc.value)
    assert not Path(fake.script.parent / "invocation.json").exists()


def test_the_same_long_prompt_passes_over_stdin(fake):
    result = fake(argv_limit_chars=2000, prompt_transport="stdin").run(request(prompt="y" * 50000))
    assert result.exit_code == 0 and fake.log()["stdin"] == "y" * 50000


@pytest.mark.parametrize(
    "executable, expected",
    [("agent.exe", 30000), ("agent.CMD", 7500), ("agent.bat", 7500), ("/usr/bin/agent", 30000)],
)
def test_cmd_shims_get_the_shorter_limit(executable, expected):
    assert argv_limit([executable, "-p"], CursorParams()) == expected


def test_argv_length_counts_quoting():
    assert argv_length(["a", "b c"]) == len('a "b c"')


def test_a_system_prompt_is_not_accepted_on_this_channel(fake):
    with pytest.raises(CursorLaunchError, match="no system prompt"):
        fake().run(request(system_prompt="SYSTEM"))


def test_a_missing_executable_says_how_to_proceed():
    params = CursorParams(executables=["agent", "cursor-agent"])
    with pytest.raises(CursorLaunchError, match="manual mode needs no CLI"):
        resolve_executable(params, which=lambda name: None)
    seen = []

    def which(name):
        seen.append(name)
        return "C:/tools/cursor-agent.exe" if name == "cursor-agent" else None

    assert resolve_executable(params, which=which) == ["C:/tools/cursor-agent.exe"]
    assert seen == ["agent", "cursor-agent"]  # in the configured order


# ---- the sandbox is left as found ----------------------------------------------------------------
def test_whatever_the_cli_leaves_in_the_sandbox_is_removed_and_noted(fake, monkeypatch):
    monkeypatch.setenv("FAKE_LEAVE", ".cursor")
    runner = fake()
    result = runner.run(request())
    assert sandbox_entries(fake.sandbox) == []
    assert "removed 2 item(s)" in result.stderr and ".cursor" in result.stderr
    assert "stray.txt" in result.stderr
    runner.run(request())  # so the next run may start


def test_sweep_removes_files_directories_and_nested_content(tmp_path):
    box = tmp_path / "box"
    (box / "a" / "b").mkdir(parents=True)
    (box / "a" / "b" / "f.txt").write_text("x", encoding="utf-8")
    (box / "top.txt").write_text("x", encoding="utf-8")
    assert sweep_sandbox(box) == ["a", "top.txt"] and sandbox_entries(box) == []


# ---- failures and limits -------------------------------------------------------------------------
@pytest.mark.parametrize(
    "stderr, exit_code, limited",
    [
        ("You've hit your usage limit. Upgrade your plan.", 1, True),
        ("Error: rate limit exceeded, too many requests", 1, True),
        ("quota exhausted", 2, True),
        ("Error: model not found", 1, False),
        ("segmentation fault", 139, False),
    ],
)
def test_usage_limit_wording_is_detected_only_when_the_call_failed(
    fake, monkeypatch, stderr, exit_code, limited
):
    monkeypatch.setenv("FAKE_STDERR", stderr)
    monkeypatch.setenv("FAKE_EXIT", str(exit_code))
    monkeypatch.setenv("FAKE_REPLY", "")
    result = fake().run(request())
    assert result.exit_code == exit_code and result.extra.get("usage_limit", False) is limited
    assert stderr in result.stderr


def test_a_good_reply_that_mentions_limits_is_not_a_usage_limit(fake, monkeypatch):
    monkeypatch.setenv("FAKE_REPLY", '[{"justification": "the rate limit is not an issue"}]')
    assert "usage_limit" not in fake().run(request()).extra


def test_a_timeout_is_reported_with_exit_code_124(fake, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "5")
    result = fake(timeout_seconds=1).run(request())
    assert result.exit_code == 124 and "timed out after 1 s" in result.stderr


def test_unreadable_model_list_is_none_and_listing_matches_whole_names(fake, monkeypatch):
    runner = fake()
    listing = runner.list_models()
    assert model_is_listed("gpt-fake-1", listing) and model_is_listed("gem-fake.2", listing)
    assert not model_is_listed("gpt-fake", listing)  # a prefix is not the model
    assert not model_is_listed("fake-1", listing)
    assert "\x1b" not in strip_ansi(listing)
    monkeypatch.setenv("FAKE_NO_LIST", "1")
    assert runner.list_models() is None
    assert sandbox_entries(fake.sandbox) == []


@pytest.mark.parametrize(
    "name, listing, expected",
    [
        ("gpt-5", "gpt-5 - GPT-5\ngpt-5-mini - mini", True),
        ("gpt-5", "gpt-5-mini - mini\ngpt-5.1 - newer", False),
        ("gpt-5", "* gpt-5 (current)", True),
        ("o3", "gpt-o3x\nxo3", False),
        ("sonnet-4", "claude/sonnet-4", False),
    ],
)
def test_model_listing_match_is_by_whole_token(name, listing, expected):
    assert model_is_listed(name, listing) is expected


# ---- through execute_run (rule 5 logging) --------------------------------------------------------
def test_a_cli_run_is_logged_with_every_rule_5_field(db, fake):
    from gauge.synthetic import seed_synthetic_companies

    with session_scope(db.engine) as s:
        seed_synthetic_companies(s, db.cfg)
    codes = db.cfg.masked_codes()
    planned = PlannedRun(
        "P1_C1_r1", "P1", "gpt-fake-1", "primary", "cursor", "C1", 1, 5, 0, 0.0, tuple(codes)
    )
    runner = fake()
    with session_scope(db.engine) as s:
        outcome = execute_run(s, db.cfg, runner, planned, PROMPT)
    assert outcome.status == "success"
    with session_scope(db.engine) as s:
        row = s.scalar(select(Run).where(Run.run_id == "P1_C1_r1"))
        assert row.mode == "cli" and row.cli_version == "9.9.9-fake" and row.exit_code == 0
        assert row.prompt_text == PROMPT and len(row.prompt_sha256) == 64
        command = json.loads(row.command)
        assert command[:3] == [sys.executable, str(fake.script), "-p"] and "--mode" in command
        assert PROMPT not in row.command and "sha256" in command[-1]
        assert row.stdout == '[{"company_code": "X"}]' and row.duration_s >= 0
        assert row.system_prompt_text is None
    raw = db.cfg.raw_dir / "P1_C1_r1.txt"
    assert raw.read_text(encoding="utf-8") == '[{"company_code": "X"}]'
    assert sandbox_entries(fake.sandbox) == []


def test_a_failing_cli_run_is_logged_as_failed_and_a_limit_as_usage_limit(db, fake, monkeypatch):
    from gauge.synthetic import seed_synthetic_companies

    with session_scope(db.engine) as s:
        seed_synthetic_companies(s, db.cfg)
    codes = tuple(db.cfg.masked_codes())

    def planned(run_id):
        return PlannedRun(
            run_id, "P1", "gpt-fake-1", "primary", "cursor", "C1", 1, 5, 0, 0.0, codes
        )

    monkeypatch.setenv("FAKE_EXIT", "1")
    monkeypatch.setenv("FAKE_REPLY", "")
    monkeypatch.setenv("FAKE_STDERR", "model not found")
    with session_scope(db.engine) as s:
        assert execute_run(s, db.cfg, fake(), planned("P1_C1_r1"), PROMPT).status == "failed"
    monkeypatch.setenv("FAKE_STDERR", "usage limit reached")
    with session_scope(db.engine) as s:
        assert execute_run(s, db.cfg, fake(), planned("P1_C1_r1"), PROMPT).status == "usage_limit"
    with session_scope(db.engine) as s:
        row = s.scalar(select(Run).where(Run.run_id == "P1_C1_r1"))
        assert row.status == "usage_limit" and row.exit_code == 1  # the same row, retried
