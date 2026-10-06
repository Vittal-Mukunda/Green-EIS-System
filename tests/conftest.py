from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from fixture_alpha import build_alpha_world
from gauge.config import load_indicators, load_models, load_study
from gauge.db.session import init_db, make_engine, session_scope
from gauge.pipeline import run_all_dry
from gauge.registry import sync_registry
from gauge.render.runs import prepare_render
from gauge.rules.freeze import freeze
from gauge.stages import (
    stage_benchmarks,
    stage_build_rules,
    stage_compute_kpis,
    stage_ingest_manual,
    stage_standardize,
    stage_validate,
)
from gauge.synthetic_data import write_synthetic_manual_csv
from helpers import FAKE_AGENT

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def real_cfg():
    return load_study("config/study.yaml", root=REPO_ROOT)


@pytest.fixture
def dry_cfg():
    return load_study("config/study_dry.yaml", root=REPO_ROOT)


@pytest.fixture
def proj(tmp_path, monkeypatch) -> Path:
    """An isolated project root holding a copy of config/ and the prompt templates, with GAUGE_ROOT
    pointing at it.

    Anything that writes (DB, raw files, dry/ directory, docs) lands in tmp_path, never in the repo.
    """
    shutil.copytree(REPO_ROOT / "config", tmp_path / "config")
    shutil.copytree(REPO_ROOT / "registry" / "prompts", tmp_path / "registry" / "prompts")
    monkeypatch.setenv("GAUGE_ROOT", str(tmp_path))
    return tmp_path


@dataclass
class Db:
    cfg: object
    ind: object
    engine: object
    root: Path


@pytest.fixture
def db(proj):
    """Dry-config project with an initialised, registry-synced database, all inside tmp."""
    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    init_db(engine)
    with session_scope(engine) as session:
        sync_registry(session, cfg, load_models(cfg))
    yield Db(cfg=cfg, ind=load_indicators(cfg), engine=engine, root=proj)
    engine.dispose()


# ---- synthetic world: data pipeline done, no rules or runs yet ---------------------------
def make_world(proj, *, seed_templates: bool = True, config: str = "config/study_dry.yaml"):
    """The data pipeline on synthetic data, stopped before any rule exists or any run is made."""
    cfg = load_study(config)
    models, ind = load_models(cfg), load_indicators(cfg)
    engine = make_engine(cfg.database_url())
    init_db(engine)
    with session_scope(engine) as session:
        sync_registry(session, cfg, models)
    csv_path = cfg.path(cfg.paths.raw_data_dir) / "synthetic_manual_entry.csv"
    write_synthetic_manual_csv(cfg, ind, csv_path)
    for result in (
        stage_ingest_manual(engine, cfg, ind, csv_path, synthetic=True),
        stage_standardize(engine, ind),
        stage_validate(engine, cfg, ind),
        stage_compute_kpis(engine, cfg, ind),
        stage_benchmarks(engine, cfg, ind),
    ):
        assert result.status == "ok", result.detail
    if seed_templates:
        target = cfg.path(cfg.paths.prompts_registry_dir)
        shutil.copytree(proj / "registry" / "prompts", target, dirs_exist_ok=True)
    return SimpleNamespace(cfg=cfg, ind=ind, models=models, engine=engine, root=proj)


@pytest.fixture
def world(proj):
    w = make_world(proj)
    yield w
    w.engine.dispose()


@pytest.fixture
def ctx(world):
    """A rendering context with the T2 rule built and written."""
    assert stage_build_rules(world.engine, world.cfg, world.ind).status == "ok"
    with session_scope(world.engine) as session:
        return prepare_render(session, world.cfg, world.ind)


@pytest.fixture
def dry(proj):
    """The finished dry run: rules, prompts, freeze and mock runs all done."""
    run_all_dry(root=proj)
    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    yield SimpleNamespace(
        cfg=cfg, ind=load_indicators(cfg), models=load_models(cfg), engine=engine, root=proj
    )
    engine.dispose()


# ---- a frozen study on cursor/api-channel models with a fake agent ------------------------
MODELS_FAKE = """\
models:
  - {key: P1, role: primary, channel: cursor, vendor: "vendor-a", name: "gpt-fake-1"}
  - {key: P2, role: primary, channel: cursor, vendor: "vendor-b", name: "gem-fake.2"}
  - {key: P3, role: primary, channel: cursor, vendor: "vendor-c", name: "gpt-fake-1-mini"}
  - {key: P4, role: primary, channel: cursor, vendor: "vendor-d", name: "gpt-fake-1"}
  - key: B1
    role: baseline
    channel: api
    provider: openrouter
    vendor: "open-vendor"
    name: "a/free-one:free"
api: {temperature: 0, max_tokens: 1000, seed: 1}
cursor: {executables: ["fake-agent"]}
"""


@pytest.fixture
def fw(proj, monkeypatch):
    """A frozen synthetic study whose models are cursor/api channel (never called for real), a fake
    `agent` on the Cursor channel, and no runs yet."""
    (proj / "config/models_fake.yaml").write_text(MODELS_FAKE, encoding="utf-8")
    dry = (proj / "config/study_dry.yaml").read_text(encoding="utf-8")
    (proj / "config/study_fake.yaml").write_text(
        dry.replace("config/models_dry.yaml", "config/models_fake.yaml"), encoding="utf-8"
    )
    w = make_world(proj, config="config/study_fake.yaml")
    assert stage_build_rules(w.engine, w.cfg, w.ind).status == "ok"
    with session_scope(w.engine) as session:
        freeze(session, w.cfg, w.ind, w.models)

    script = proj / "fake_agent.py"
    script.write_text(FAKE_AGENT, encoding="utf-8")
    monkeypatch.setenv("FAKE_LOG", str(proj / "invocation.json"))
    monkeypatch.setenv("FAKE_AUTO", "1")
    for var in (
        "FAKE_REPLY",
        "FAKE_EXIT",
        "FAKE_STDERR",
        "FAKE_LEAVE",
        "FAKE_NO_LIST",
        "FAKE_SLEEP",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        "gauge.runner.cursor.resolve_executable",
        lambda params, which=None: [sys.executable, str(script)],
    )
    w.script = script
    w.codes = sorted(c for c in _codes(w))
    yield w
    w.engine.dispose()


def _codes(w):
    with session_scope(w.engine) as s:
        return list(prepare_render(s, w.cfg, w.ind).evidence.companies)


@pytest.fixture
def fixture_world(db):
    """Two sectors, seven companies and two fiscal years, every value chosen by hand
    (see tests/fixture_alpha.py)."""
    return build_alpha_world(db)
