"""The dashboard under Streamlit's AppTest: every view renders, the name toggle works, the audit
search filters, and annotation is the only thing that writes."""

from __future__ import annotations

import sys

import pytest
from sqlalchemy import func, select
from streamlit.testing.v1 import AppTest

from gauge.config import load_study
from gauge.db.models import Annotation, Claim, Run
from gauge.db.session import make_engine, session_scope
from gauge.pipeline import run_all_dry

EIS_PAGES = [
    "Home",
    "Sectors",
    "KPI scorecard",
    "Companies",
    "Compare companies",
    "Query and chart",
    "Compliance check",
    "Data quality register",
    "Sources and filings",
    "Data verification",
    "Metrics guide",
    "About",
]
PAGES = [
    *EIS_PAGES,
    "Model reliability scorecard",
    "C1 vs C2",
    "Disagreement queue",
    "Annotation",
    "Audit trail",
]


def _run_app(monkeypatch, repo_root, config: str) -> AppTest:
    monkeypatch.setattr(sys, "argv", ["app.py", "--config", config])
    return AppTest.from_file(str(repo_root / "dashboard" / "app.py"), default_timeout=120).run()


def go(at: AppTest, page: str) -> AppTest:
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


@pytest.fixture
def app(proj, repo_root, monkeypatch):
    run_all_dry(root=proj)
    return _run_app(monkeypatch, repo_root, "config/study_dry.yaml")


def db_count(proj, model):
    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    try:
        with session_scope(engine) as s:
            return s.scalar(select(func.count()).select_from(model))
    finally:
        engine.dispose()


def test_the_first_page_is_home_and_companies_are_shown_by_name(app):
    assert not app.exception
    assert app.sidebar.radio[0].options == PAGES and app.sidebar.radio[0].value == "Home"
    go(app, "Companies")
    options = app.selectbox(key="company_pick").options
    assert len(options) == 6 and all(o.startswith("Synthetic ") for o in options)  # real names
    assert any("mapping indicates relevance, not achievement" in c.value for c in app.caption)
    assert any("Pilot-scale" in c.value for c in app.caption)


def test_the_name_toggle_shows_masked_codes_only_when_asked(app):
    go(app, "Companies")
    app.sidebar.toggle[0].set_value(False).run()
    assert not app.exception
    assert all(" " not in o for o in app.selectbox(key="company_pick").options)  # codes
    app.sidebar.toggle[0].set_value(True).run()
    assert all(o.startswith("Synthetic ") for o in app.selectbox(key="company_pick").options)


@pytest.mark.parametrize("page", PAGES)
def test_every_view_renders_on_the_dry_run(app, page):
    go(app, page)
    assert any("MOCK DATA" in w.value for w in app.warning) or page in (*EIS_PAGES, "Annotation")


def test_the_company_page_shows_tables_and_the_sdg_caption(app):
    go(app, "Companies")
    assert len(app.dataframe) >= 4  # KPIs, benchmarks, indicators, SDG (flags when present)
    app.selectbox(key="company_pick").set_value(app.selectbox(key="company_pick").options[3]).run()
    assert not app.exception


def test_the_scorecard_separates_the_baseline_from_the_primary_panel(app):
    go(app, "Model reliability scorecard")
    text = " ".join(m.value for m in app.markdown)
    assert "Primary panel" in text and "never pooled" in text
    assert len(app.dataframe) >= 5


def test_the_c1_c2_view_has_the_agreement_table(app):
    go(app, "C1 vs C2")
    assert any("Agreement between models" in m.value for m in app.markdown)


def test_the_disagreement_queue_opens_a_flag_with_evidence_and_all_outputs(app):
    go(app, "Disagreement queue")
    assert app.selectbox  # a flag to open
    texts = " ".join(m.value for m in app.markdown)
    assert "Evidence and every model's output" in texts or "Shown under C1" in texts
    assert "Shown under C2" in texts and "Model outputs" in texts


def test_the_audit_trail_filters_and_exports(app):
    go(app, "Audit trail")
    assert len(app.dataframe[0].value) == 25
    app.text_input[0].set_value("P1_C2").run()
    assert len(app.dataframe[0].value) == 2
    app.text_input[0].set_value("no-such-text").run()
    assert len(app.dataframe[0].value) == 0
    app.text_input[0].set_value("").run()
    run_ids = app.selectbox(key="audit_run").options
    app.selectbox(key="audit_run").set_value(run_ids[0]).run()
    assert not app.exception and len(app.expander) >= 2  # prompt and output of the run


def test_annotation_needs_a_name_then_saves_one_label_and_moves_on(app, proj):
    go(app, "Annotation")
    assert any("Enter your name" in i.value for i in app.info)
    assert db_count(proj, Annotation) == 0
    app.text_input(key="annotator").set_value("alice").run()
    assert not app.exception
    caption_before = next(c.value for c in app.caption if "claims left for alice" in c.value)
    assert caption_before.startswith(f"{db_count(proj, Claim)} claims left")
    app.radio(key="claim_label").set_value("unsupported").run()
    app.button(key="save_claim").click().run()
    assert not app.exception
    assert db_count(proj, Annotation) == 1
    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    try:
        with session_scope(engine) as s:
            saved = s.scalars(select(Annotation)).one()
            assert (saved.annotator, saved.kind, saved.label) == (
                "alice",
                "claim_support",
                "unsupported",
            )
            assert saved.claim_id is not None and saved.judgment_id is not None
    finally:
        engine.dispose()
    after = next(c.value for c in app.caption if "claims left for alice" in c.value)
    assert after.startswith(f"{db_count(proj, Claim) - 1} claims left")


def test_the_taxonomy_tab_labels_a_judgment_and_reports_agreement(app, proj):
    go(app, "Annotation")
    app.text_input(key="annotator").set_value("bob").run()
    app.radio(key="taxonomy_label").set_value("legitimate_ambiguity").run()
    app.button(key="save_taxonomy").click().run()
    assert not app.exception
    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    try:
        with session_scope(engine) as s:
            row = s.scalars(select(Annotation).where(Annotation.kind == "taxonomy")).one()
            assert row.annotator == "bob" and row.label == "legitimate_ambiguity"
            assert row.judgment_id is not None and row.claim_id is None
    finally:
        engine.dispose()
    assert any(
        "fewer than two annotators" in w.value for w in app.get("markdown") + app.get("text")
    )


def test_the_dashboard_never_changes_runs_or_creates_a_missing_database(
    app, proj, repo_root, monkeypatch
):
    before = db_count(proj, Run)
    for page in PAGES:
        go(app, page)
    assert db_count(proj, Run) == before  # reading every view changed nothing


def test_dashboard_does_not_create_a_missing_database(proj, repo_root, monkeypatch):
    at = _run_app(monkeypatch, repo_root, "config/study.yaml")
    assert not at.exception
    assert "gauge init-db" in at.warning[0].value
    assert not (proj / "data" / "processed" / "gauge.db").exists()


def test_views_say_what_to_run_when_nothing_is_evaluated_yet(world, ctx, repo_root, monkeypatch):
    at = _run_app(monkeypatch, repo_root, "config/study_dry.yaml")
    for page in ("Model reliability scorecard", "C1 vs C2", "Disagreement queue"):
        go(at, page)
        assert any("gauge" in i.value for i in at.info), page
    go(at, "Audit trail")
    assert any("No runs logged yet" in i.value for i in at.info)
