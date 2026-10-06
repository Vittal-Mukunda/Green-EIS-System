"""The analysis notebook and the results skeleton: they must be current and must actually run."""

from __future__ import annotations

import os
import re
import sys

import nbformat
import pytest
from sqlalchemy import func, select

from gauge.config import load_study
from gauge.db.models import EvaluationResult, Judgment, Run
from gauge.db.session import make_engine, session_scope
from gauge.pipeline import run_all_dry
from gauge.report.tables import all_tables

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_notebook  # noqa: E402

INTERPRETIVE = (
    "better", "worse", "best", "greener", "proves", "shows that", "demonstrates", "thinks",
    "perspective", "significantly higher", "outperform",
)  # fmt: skip


def code_cells(nb):
    return [c for c in nb.cells if c.cell_type == "code"]


def test_the_notebook_in_the_repo_is_what_the_builder_makes(repo_root):
    built = build_notebook.build()
    nbformat.validate(built)
    on_disk = nbformat.read(repo_root / "notebooks" / "analysis.ipynb", as_version=4)
    assert nbformat.writes(on_disk).strip() == nbformat.writes(built).strip(), (
        "run `python scripts/build_notebook.py`"
    )


def test_the_notebook_is_valid_and_has_stable_cell_ids():
    nb = build_notebook.build()
    nbformat.validate(nb)
    ids = [c["id"] for c in nb.cells]
    assert len(set(ids)) == len(ids) and ids[0] == "cell-00"
    assert nbformat.writes(build_notebook.build()) == nbformat.writes(nb)  # deterministic


def test_the_notebook_text_makes_no_interpretive_claims():
    nb = build_notebook.build()
    for cell in nb.cells:
        text = cell.source.lower()
        if cell.cell_type == "markdown" or "print(" in text:
            for word in INTERPRETIVE:
                assert not re.search(rf"\b{re.escape(word)}\b", text), (word, cell.source[:60])


def test_the_notebook_only_reads_the_database(repo_root):
    source = "\n".join(c.source for c in code_cells(build_notebook.build()))
    for forbidden in (
        "session.add",
        ".commit(",
        "delete(",
        "save_annotation",
        "run_pending",
        "subprocess",
    ):
        assert forbidden not in source
    assert "load_study(CONFIG)" in source and "GAUGE_CONFIG" in source


def run_cells(nb, namespace=None):
    ns = namespace if namespace is not None else {}
    for i, cell in enumerate(code_cells(nb)):
        exec(compile(cell.source, f"cell-{i}", "exec"), ns)  # noqa: S102
    return ns


def counts(proj):
    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    try:
        with session_scope(engine) as s:
            return tuple(
                s.scalar(select(func.count()).select_from(m))
                for m in (Run, Judgment, EvaluationResult)
            )
    finally:
        engine.dispose()


def test_every_code_cell_runs_on_the_dry_run_and_writes_its_tables_and_figures(
    proj, monkeypatch, capsys
):
    run_all_dry(root=proj)
    before = counts(proj)
    monkeypatch.setenv("GAUGE_CONFIG", "config/study_dry.yaml")
    ns = run_cells(build_notebook.build())
    out = capsys.readouterr().out
    assert "MOCK DATA" in out and "Table 1." in out and "Table 15." in out
    folder = ns["OUT"]
    assert folder == proj / "dry" / "results" / "notebook"
    names = {p.name for p in folder.iterdir()}
    for table in list(all_tables.__code__.co_consts) and (
        "scorecard.csv", "context_effects.csv", "agreement_between_models.csv",
        "attribute_agreement.csv", "hypotheses.csv", "hypothesis_tests.csv", "baseline_vs_panel.csv",
        "position_effect.csv", "grounding.csv", "parse_failure_rates.csv", "run_counts.csv",
        "sample.csv", "selection_log.csv", "data_quality.csv", "verification.csv",
    ):  # fmt: skip
        assert table in names, table
    figs = sorted(n for n in names if n.endswith(".html"))
    assert figs == [f"fig{i}_{k}.html" for i, k in enumerate(
        ("t2_accuracy", "rating_shift", "transitions", "alpha_t2", "alpha_t3", "position"), start=1
    )]  # fmt: skip
    html = (folder / "fig1_t2_accuracy.html").read_text(encoding="utf-8")
    assert "plotly" in html.lower() and "T2 accuracy" in html
    assert counts(proj) == before  # the notebook changed nothing in the database


def test_the_notebook_tables_equal_the_exported_tables(proj, monkeypatch, capsys):
    import pandas as pd

    run_all_dry(root=proj)
    monkeypatch.setenv("GAUGE_CONFIG", "config/study_dry.yaml")
    ns = run_cells(build_notebook.build())
    capsys.readouterr()
    exported = pd.read_csv(proj / "dry" / "results" / "scorecard.csv")
    from_notebook = pd.read_csv(ns["OUT"] / "scorecard.csv")
    pd.testing.assert_frame_equal(exported, from_notebook)


def test_the_notebook_runs_on_a_database_with_no_results_yet(world, ctx, monkeypatch, capsys):
    monkeypatch.setenv("GAUGE_CONFIG", "config/study_dry.yaml")
    ns = run_cells(build_notebook.build())  # empty tables must not crash any cell
    assert "T" in ns and ns["T"]["scorecard"].empty
    capsys.readouterr()


# ---- the results skeleton ------------------------------------------------------------------------
def test_the_skeleton_covers_every_table_every_hypothesis_and_the_limitations(repo_root):
    text = (repo_root / "docs" / "RESULTS_SKELETON.md").read_text(encoding="utf-8")
    for name in (
        "sample.csv", "selection_log.csv", "data_quality.csv", "verification.csv", "scorecard.csv",
        "context_effects.csv", "baseline_vs_panel.csv", "parse_failure_rates.csv",
        "agreement_between_models.csv", "attribute_agreement.csv", "hypotheses.csv",
        "hypothesis_tests.csv", "position_effect.csv", "grounding.csv", "run_counts.csv",
    ):  # fmt: skip
        assert name in text, name
    for h in ("H1", "H2", "H3", "H4", "H5", "H6", "S1"):
        assert f"| {h}" in text
    for table in range(1, 16):
        assert f"Table {table}" in text or f"Tables {table}" in text or f"Table {table}," in text, (
            table
        )
    assert "[owner]" in text and "pilot-scale" in text.lower()
    assert "mapping indicates relevance, not achievement" in text


def test_the_skeleton_makes_no_interpretive_claims_about_results(repo_root):
    text = (repo_root / "docs" / "RESULTS_SKELETON.md").read_text(encoding="utf-8").lower()
    for word in ("significantly higher", "outperform", "proves", "we found", "the results show"):
        assert word not in text


@pytest.mark.parametrize("figure", ["fig1_t2_accuracy", "fig6_position"])
def test_figure_names_in_the_notebook_are_unique(figure):
    source = "\n".join(c.source for c in code_cells(build_notebook.build()))
    assert source.count(f'"{figure}"') == 1
