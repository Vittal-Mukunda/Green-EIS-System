from __future__ import annotations

import os
import stat
import subprocess
import sys

import pytest
import yaml
from sqlalchemy import func, select
from typer.testing import CliRunner

from gauge.cli import app
from gauge.config import load_study
from gauge.db.models import Company, Condition, Model, Run, RunCompanyPosition, Sector
from gauge.db.session import make_engine, session_scope
from gauge.pipeline import DryRunError, run_all_dry

SPEC_COMMANDS = [
    "init-db",
    "ingest",
    "standardize",
    "validate",
    "verify-sample",
    "compute-kpis",
    "benchmarks",
    "build-rules",
    "render",
    "freeze",
    "run",
    "import-manual",
    "parse",
    "evaluate",
    "stats",
    "checklist",
    "export",
    "dashboard",
]

cli = CliRunner()


def count(engine, table) -> int:
    with session_scope(engine) as s:
        return s.scalar(select(func.count()).select_from(table))


def test_help_lists_every_spec_command():
    result = cli.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in [*SPEC_COMMANDS, "all-dry"]:
        assert name in result.output, name


def test_run_requires_a_valid_mode():
    assert cli.invoke(app, ["run"]).exit_code != 0
    assert cli.invoke(app, ["run", "--mode", "mock"]).exit_code != 0  # mock is all-dry only


def test_init_db_creates_schema_and_registers_reference_rows(proj):
    result = cli.invoke(app, ["init-db"])
    assert result.exit_code == 0, result.output
    assert (proj / "data/processed/gauge.db").is_file()
    cfg = load_study("config/study.yaml")
    engine = make_engine(cfg.database_url())
    assert (
        count(engine, Sector) == 4 and count(engine, Condition) == 2 and count(engine, Model) == 6
    )
    with session_scope(engine) as s:  # placeholders are stored as-is, flagged by the run gate
        assert s.scalar(select(Model.name).where(Model.key == "P1")).startswith("TODO")
    engine.dispose()


def test_init_db_is_idempotent_and_picks_up_config_edits(proj):
    assert cli.invoke(app, ["init-db"]).exit_code == 0
    path = proj / "config/models.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '{key: P1, role: primary, channel: cursor, vendor: "TODO(owner): e.g. OpenAI", '
            'name: "TODO_FILL_FROM_CURSOR_LIST"}',
            '{key: P1, role: primary, channel: cursor, vendor: "OpenAI", name: "example-model"}',
        ),
        encoding="utf-8",
    )
    assert cli.invoke(app, ["init-db"]).exit_code == 0
    engine = make_engine(load_study("config/study.yaml").database_url())
    assert count(engine, Model) == 6
    with session_scope(engine) as s:
        assert s.scalar(select(Model.name).where(Model.key == "P1")) == "example-model"
    engine.dispose()


def test_init_db_ddl_only_writes_docs(proj):
    result = cli.invoke(app, ["init-db", "--ddl-only"])
    assert result.exit_code == 0
    assert (proj / "docs/schema.sql").is_file() and (proj / "docs/schema_postgres.sql").is_file()
    assert not (proj / "data/processed/gauge.db").exists()


def test_bad_config_is_reported_cleanly(proj):
    result = cli.invoke(app, ["--config", "config/missing.yaml", "init-db"])
    assert result.exit_code == 1 and "config error" in result.output


# ---- all-dry ------------------------------------------------------------------------------------
def test_all_dry_end_to_end(proj):
    result = cli.invoke(app, ["all-dry"])
    assert result.exit_code == 0, result.output
    assert "20 executed" in result.output and "20 run rows (20 success)" in result.output
    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    # 20 planned runs + 5 repair attempts (one for each defect the mock plants in a reply)
    assert count(engine, Company) == 6 and count(engine, Run) == 25
    assert count(engine, RunCompanyPosition) == 20 * 6  # repairs have no company positions
    assert len(list(cfg.raw_dir.glob("*.txt"))) == 25
    with session_scope(engine) as s:
        assert s.scalar(select(func.count()).select_from(Company).where(Company.is_synthetic)) == 6
        assert set(s.scalars(select(Run.mode))) == {"mock"}
    engine.dispose()
    # dry run must leave the real DB and real runs/ untouched
    assert not (proj / "data/processed/gauge.db").exists() and not (proj / "runs").exists()


def test_all_dry_can_be_repeated(proj):
    first = run_all_dry(root=proj)
    second = run_all_dry(root=proj)
    assert [r.detail for r in first] == [r.detail for r in second]  # clean reset: same result


def test_all_dry_runs_every_stage_and_leaves_none_pending(proj):
    results = {r.name: r.status for r in run_all_dry(root=proj)}
    assert set(results.values()) == {"ok"} and len(results) == 17
    for stage in (
        "init-db", "build-rules", "render", "freeze", "verify-freeze", "run (mock)", "parse",
        "evaluate", "stats", "checklist", "export",
    ):  # fmt: skip
        assert results[stage] == "ok"


def test_all_dry_never_spawns_a_process(proj, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry run must not spawn processes (Cursor is never called)")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    run_all_dry(root=proj)


def test_all_dry_refuses_non_mock_models(proj):
    result = cli.invoke(app, ["all-dry", "--config", "config/study.yaml"])
    assert result.exit_code == 1 and "mock" in result.output
    assert not (proj / "dry").exists()  # refused before touching the filesystem


def test_all_dry_refuses_paths_outside_dry(proj):
    data = yaml.safe_load((proj / "config/study_dry.yaml").read_text(encoding="utf-8"))
    data["paths"]["runs_dir"] = "runs"  # would have been wiped otherwise
    (proj / "config/evil_dry.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(DryRunError, match="outside"):
        run_all_dry("config/evil_dry.yaml", root=proj)


@pytest.mark.skipif(
    sys.platform != "win32", reason="read-only directories block rmdir on Windows only"
)
def test_all_dry_reset_survives_read_only_directories(proj):
    """OneDrive marks synced folders read-only; the dry-run reset must still delete them."""
    run_all_dry(root=proj)
    for directory in [p for p in (proj / "dry").rglob("*") if p.is_dir()]:
        os.chmod(directory, stat.S_IREAD)
    run_all_dry(root=proj)  # would raise PermissionError without the read-only handling
