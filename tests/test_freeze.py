"""Freezing (hard rule 7), the build-rules / render / freeze commands, and sample prompts."""

from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import select, update
from typer.testing import CliRunner

from gauge.cli import app
from gauge.db.models import Company, KpiValue, PromptTemplate, Rule
from gauge.db.session import session_scope
from gauge.rules.build import t2_path, t3_path
from gauge.rules.freeze import (
    FreezeError,
    assert_frozen_ok,
    freeze,
    manifest_path,
    verify_frozen,
)
from gauge.stages import stage_build_rules, stage_freeze

cli = CliRunner()
DRY = ["--config", "config/study_dry.yaml"]


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_world(w, **kw):
    with session_scope(w.engine) as session:
        return freeze(session, w.cfg, w.ind, w.models, **kw)


def touch(path, extra: str = "\n<!-- edited -->\n") -> None:
    path.write_bytes(path.read_bytes() + extra.encode("utf-8"))


# ---- the manifest --------------------------------------------------------------------------------
def test_manifest_lists_every_frozen_file_and_every_prompt(dry):
    manifest = json.loads(manifest_path(dry.cfg).read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 1 and manifest["frozen_utc"].endswith("+00:00")
    assert set(manifest["files"]) == {
        "dry/registry/rules/t2_v1.yaml",
        "dry/registry/rules/t3_update_v1.yaml",
        "dry/registry/prompts/system_v1.md",
        "dry/registry/prompts/c1_user_v1.md",
        "dry/registry/prompts/c2_user_v1.md",
        "config/indicators.yaml",
    }
    for key, digest in manifest["files"].items():
        assert sha(dry.root / key) == digest, key
    assert len(manifest["prompts"]) == 20 and len(manifest["companies"]) == 6
    for run_id, entry in manifest["prompts"].items():
        assert entry["condition"] == run_id.split("_")[1]
        assert sorted(entry["company_order"]) == manifest["companies"]
        assert len({entry["sha256"], entry["system_sha256"], entry["user_sha256"]}) == 3
    orders = {tuple(e["company_order"]) for e in manifest["prompts"].values()}
    assert len(orders) > 1  # the shuffled orders are part of what is frozen


def test_manifest_prompt_hashes_match_the_prompt_files(dry):
    manifest = json.loads(manifest_path(dry.cfg).read_text(encoding="utf-8"))
    for run_id, entry in manifest["prompts"].items():
        assert sha(dry.cfg.prompts_dir / f"{run_id}.md") == entry["sha256"]


def test_freeze_stamps_and_stores_the_rule_and_template_rows(dry):
    with session_scope(dry.engine) as session:
        rules = {r.rule_id: r for r in session.scalars(select(Rule))}
        templates = {t.name: t for t in session.scalars(select(PromptTemplate))}
    assert set(rules) == {"t2_v1", "t3_update_v1"}
    assert rules["t2_v1"].kind == "T2" and rules["t3_update_v1"].kind == "T3_UPDATE"
    for r, path in ((rules["t2_v1"], t2_path(dry.cfg)), (rules["t3_update_v1"], t3_path(dry.cfg))):
        assert r.frozen_utc is not None and r.sha256 == sha(path)
        assert r.content == path.read_text(encoding="utf-8")
    assert set(templates) == {"system_v1", "c1_user_v1", "c2_user_v1"}
    assert all(t.frozen_utc is not None for t in templates.values())
    assert templates["system_v1"].condition_id is None  # shared by both conditions
    assert templates["c1_user_v1"].condition_id != templates["c2_user_v1"].condition_id


# ---- verification --------------------------------------------------------------------------------
def test_an_intact_freeze_verifies(dry):
    assert verify_frozen(dry.cfg) == []
    with session_scope(dry.engine) as session:
        assert verify_frozen(dry.cfg, session, dry.ind, dry.models) == []
        assert_frozen_ok(dry.cfg, session, dry.ind, dry.models)


def test_not_frozen_is_reported(world):
    assert verify_frozen(world.cfg)[0].startswith("not frozen")
    with pytest.raises(FreezeError, match="not frozen"):
        assert_frozen_ok(world.cfg)


@pytest.mark.parametrize(
    "relative",
    [
        "dry/registry/prompts/system_v1.md",
        "dry/registry/prompts/c1_user_v1.md",
        "dry/registry/prompts/c2_user_v1.md",
        "dry/registry/rules/t2_v1.yaml",
        "dry/registry/rules/t3_update_v1.yaml",
        "config/indicators.yaml",
    ],
)
def test_any_changed_frozen_file_is_detected(dry, relative):
    touch(dry.root / relative, "\n# edited\n")
    problems = verify_frozen(dry.cfg)
    assert problems == [f"{relative}: changed since the freeze"]
    with pytest.raises(FreezeError, match="changed since the freeze"):
        assert_frozen_ok(dry.cfg)


def test_a_deleted_frozen_file_is_detected(dry):
    (dry.root / "dry/registry/prompts/c2_user_v1.md").unlink()
    assert verify_frozen(dry.cfg) == ["dry/registry/prompts/c2_user_v1.md: frozen file is missing"]


def test_changed_data_is_caught_through_the_rendered_prompts(dry):
    """No frozen file changed, but a KPI the prompts show did: the prompt hashes differ."""
    with session_scope(dry.engine) as session:
        company = session.scalar(select(Company).order_by(Company.code))
        session.execute(
            update(KpiValue)
            .where(KpiValue.company_id == company.id, KpiValue.fy == "FY2024-25")
            .where(KpiValue.kpi == "energy_intensity")
            .values(value=KpiValue.value * 2)
        )
    assert verify_frozen(dry.cfg) == []  # files alone cannot see it
    with session_scope(dry.engine) as session:
        problems = verify_frozen(dry.cfg, session, dry.ind, dry.models)
    assert len(problems) == 20 and all("rendered prompt differs" in p for p in problems)


def test_changed_benchmarks_are_caught_as_a_stale_rule(dry):
    with session_scope(dry.engine) as session:
        session.execute(
            update(KpiValue)
            .where(KpiValue.kpi == "emissions_intensity", KpiValue.fy == "FY2024-25")
            .values(value=KpiValue.value * 3)
        )
        from gauge.benchmark.compute import compute_benchmarks

        compute_benchmarks(session, dry.cfg, [k.code for k in dry.ind.kpis])
    with session_scope(dry.engine) as session:
        (problem,) = verify_frozen(dry.cfg, session, dry.ind, dry.models)
    assert "cannot re-render the prompts" in problem and "build-rules" in problem


def test_enabling_a_disabled_model_later_needs_no_refreeze(dry):
    """`freeze` plans disabled models too, so S1-style optional runs stay covered."""
    models = dry.models.model_copy(deep=True)
    models.models[-1].enabled = False  # as if the optional model were off at freeze time
    with session_scope(dry.engine) as session:
        assert verify_frozen(dry.cfg, session, dry.ind, models) == []


# ---- refusing ------------------------------------------------------------------------------------
def test_freeze_needs_the_rule_files(world):
    with pytest.raises(FreezeError, match="T2 rule file missing"):
        freeze_world(world)


def test_freeze_refuses_a_stale_rule(world):
    assert stage_build_rules(world.engine, world.cfg, world.ind).status == "ok"
    path = t2_path(world.cfg)
    path.write_bytes(path.read_bytes().replace(b"n: 3", b"n: 4", 1))
    with pytest.raises(FreezeError, match="does not match the current benchmarks"):
        freeze_world(world)


def test_freeze_refuses_a_real_sample_with_gaps(world):
    assert stage_build_rules(world.engine, world.cfg, world.ind).status == "ok"
    with session_scope(world.engine) as session:
        for c in session.scalars(select(Company)):
            c.is_synthetic = False
    with pytest.raises(FreezeError, match="would print as 'not reported'"):
        freeze_world(world)
    assert not manifest_path(world.cfg).exists()


def test_freeze_refuses_provisional_data(world):
    """Only `included` companies are ever frozen: candidates give no evidence."""
    assert stage_build_rules(world.engine, world.cfg, world.ind).status == "ok"
    with session_scope(world.engine) as session:
        for c in session.scalars(select(Company)):
            c.selection_status = "candidate"
    with pytest.raises(FreezeError, match="no `included` companies"):
        freeze_world(world)


def test_refreezing_needs_force_while_no_run_exists(world):
    assert stage_build_rules(world.engine, world.cfg, world.ind).status == "ok"
    first = freeze_world(world)
    with pytest.raises(FreezeError, match="already frozen"):
        freeze_world(world)
    again = freeze_world(world, force=True)  # no run exists yet: allowed
    assert again.manifest == first.manifest and again.files == first.files


def test_freezing_never_changes_once_runs_exist(dry):
    with pytest.raises(FreezeError, match="runs exist"):
        freeze_world(dry, force=True)  # the dry run executed mock runs
    result = stage_freeze(dry.engine, dry.cfg, dry.ind, dry.models, force=True)
    assert result.status == "error" and "runs exist" in result.detail


def test_rules_can_be_rebuilt_after_the_freeze_only_with_force(world):
    assert stage_build_rules(world.engine, world.cfg, world.ind).status == "ok"
    freeze_world(world)
    refused = stage_build_rules(world.engine, world.cfg, world.ind)
    assert refused.status == "error" and "frozen" in refused.detail and "--force" in refused.detail
    assert stage_build_rules(world.engine, world.cfg, world.ind, force=True).status == "ok"


def test_rules_can_never_be_rebuilt_once_runs_exist(dry):
    result = stage_build_rules(dry.engine, dry.cfg, dry.ind, force=True)
    assert result.status == "error" and "runs exist" in result.detail


def test_provisional_rules_never_touch_the_registry(dry):
    before = (sha(t2_path(dry.cfg)), sha(manifest_path(dry.cfg)))
    result = stage_build_rules(dry.engine, dry.cfg, dry.ind, provisional=True)
    assert result.status == "ok" and "PROVISIONAL" in result.detail
    assert (dry.cfg.runs_dir / "provisional" / "t2_v1.yaml").is_file()
    assert (sha(t2_path(dry.cfg)), sha(manifest_path(dry.cfg))) == before
    assert verify_frozen(dry.cfg) == []


# ---- CLI -----------------------------------------------------------------------------------------
def test_cli_commands_need_a_database(proj):
    for command in (["build-rules"], ["render"], ["freeze"], ["freeze", "--verify"]):
        result = cli.invoke(app, command)
        assert result.exit_code == 1 and "database not found" in result.output


def test_cli_freeze_verify_reports_a_change(dry):
    ok = cli.invoke(app, [*DRY, "freeze", "--verify"])
    assert ok.exit_code == 0 and "match" in ok.output
    touch(dry.root / "dry/registry/prompts/system_v1.md")
    bad = cli.invoke(app, [*DRY, "freeze", "--verify"])
    assert bad.exit_code == 1 and "system_v1.md: changed since the freeze" in bad.output


def test_cli_freeze_refuses_twice(dry):
    result = cli.invoke(app, [*DRY, "freeze"])
    assert result.exit_code == 1 and "already frozen" in result.output


def test_cli_build_rules_and_render_after_freeze(dry):
    refused = cli.invoke(app, [*DRY, "build-rules"])
    assert refused.exit_code == 1 and "frozen" in refused.output
    preview = cli.invoke(app, [*DRY, "build-rules", "--provisional"])
    assert preview.exit_code == 0 and "PROVISIONAL" in preview.output
    rendered = cli.invoke(app, [*DRY, "render", "--condition", "C1"])
    assert rendered.exit_code == 0 and "10 prompts for 6 companies" in rendered.output
    assert "identity check passed" in rendered.output


def test_cli_provisional_render_goes_to_its_own_folder(dry):
    result = cli.invoke(app, [*DRY, "render", "--provisional", "--condition", "C1"])
    assert result.exit_code == 0 and "PROVISIONAL" in result.output
    folder = dry.cfg.runs_dir / "provisional" / "prompts"
    assert (folder / "index.csv").is_file()
    assert len(list(folder.glob("*.md"))) == 10  # 5 models x 2 repetitions, C1 only
    assert verify_frozen(dry.cfg) == []


def test_cli_render_sample_writes_one_prompt_per_condition(dry, tmp_path):
    out = tmp_path / "sample.md"
    result = cli.invoke(app, [*DRY, "render", "--sample", "--out", str(out)])
    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Sample prompts") and "SYNTHETIC DATA" in text
    assert "### C1" in text and "### C2" in text and text.count("~~~~") == 4
    assert "Context for" in text and "SHA-256" in text


def test_cli_render_sample_for_c1_only_needs_no_trends(dry, tmp_path):
    out = tmp_path / "c1.md"
    result = cli.invoke(
        app, [*DRY, "render", "--sample", "--condition", "C1", "--provisional", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert "### C1" in text and "### C2" not in text and "Context for" not in text


def test_cli_render_refuses_when_the_rule_is_stale(dry):
    path = t2_path(dry.cfg)
    path.write_bytes(path.read_bytes().replace(b"n: 3", b"n: 4", 1))
    result = cli.invoke(app, [*DRY, "render"])
    assert result.exit_code == 1 and "build-rules" in result.output
