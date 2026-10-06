"""Write notebooks/analysis.ipynb: every table and figure of the paper, from the database only.

    python scripts/build_notebook.py

The notebook imports from src/gauge, reads the database (never writes it, never calls a model) and
saves each table as CSV and each figure as a self-contained HTML file in <results>/notebook/. Its text
describes what a table or figure is; it makes no interpretive claim (the owner writes those, see
docs/RESULTS_SKELETON.md). `GAUGE_CONFIG` selects the study (default config/study.yaml; use
config/study_dry.yaml for the synthetic dry run).
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat as nbf

SETUP = '''\
import os

import pandas as pd

from gauge.config import load_indicators, load_study
from gauge.db.session import make_engine, session_scope
from gauge.evaluate.frame import load_frame
from gauge.evaluate.results import load_metrics
from gauge.report import figures, tables
from gauge.viewdata import annotator_agreement

try:
    from IPython.display import display
except ImportError:  # run outside Jupyter
    display = print

CONFIG = os.environ.get("GAUGE_CONFIG", "config/study.yaml")
cfg = load_study(CONFIG)
indicators = load_indicators(cfg)
engine = make_engine(cfg.database_url())
OUT = cfg.results_path / "notebook"
OUT.mkdir(parents=True, exist_ok=True)

with session_scope(engine) as s:
    T = tables.all_tables(s)
    T["sample"] = tables.sample_description(s, cfg.study.analysis_fy)
    T["selection_log"] = tables.selection_log(s)
    T["data_quality"] = tables.data_quality(s)
    T["verification"] = tables.verification_summary(s)
    frame = load_frame(s)
    mock = tables.uses_mock_runs(s)
    kappa = {kind: annotator_agreement(s, kind) for kind in ("claim_support", "taxonomy")}

if mock:
    print("MOCK DATA: dry-run numbers exercise the code and say nothing about any real model or company.")


def table(name, title):
    """Show a table, and save its numbers as CSV."""
    df = T[name]
    df.to_csv(OUT / f"{name}.csv", index=False, lineterminator="\\n")
    print(title)
    display(df)


def figure(make, data, name):
    """Build `make(data)`, show it and save it as a self-contained HTML file; skip if `data` is empty."""
    if data is None or len(data) == 0:
        print(f"{name}: no data yet")
        return
    fig = make(data)
    fig.write_html(OUT / f"{name}.html", include_plotlyjs="cdn")
    fig.show()
'''

CELLS: list[tuple[str, str]] = [
    (
        "markdown",
        "# Analysis notebook\n\n"
        "Imports from `src/gauge`, reads the database only, and produces every table and figure of "
        "the paper. Each table is saved as CSV and each figure as HTML under the results folder "
        "(`notebook/`). The text here only says what each item is; interpretation is the owner's "
        "(see `docs/RESULTS_SKELETON.md`). Pilot-scale and exploratory.",
    ),
    ("code", SETUP),
    ("markdown", "## Data"),
    ("code", 'table("sample", "Table 1. The study sample by sector, analysis-year reports")'),
    ("code", 'table("selection_log", "Table 2. Companies excluded, with the reason")'),
    (
        "code",
        'table("data_quality", "Table 3. Data-quality flags by rule (flags never change data)")',
    ),
    ("code", 'table("verification", "Table 4. The 10% verification sample against the filings")'),
    ("markdown", "## Model behaviour"),
    (
        "code",
        'table("scorecard", "Table 5. Model scorecard: T2 accuracy, valid share, repeatability")',
    ),
    (
        "code",
        'card = T["scorecard"]\n'
        'primary = card[card["role"] == "primary"] if len(card) else card\n'
        'title = "T2 accuracy against the rule (primary panel), 95% interval"\n'
        'figure(lambda d: figures.interval_bar(d, "model", "t2_accuracy", "condition", title),\n'
        '       primary, "fig1_t2_accuracy")',
    ),
    ("code", 'table("context_effects", "Table 6. Effect of added context (C1 to C2), per model")'),
    ("code", 'figure(figures.rating_shift_figure, frame[frame["valid"]], "fig2_rating_shift")'),
    ("code", 'figure(figures.transition_stack, T["context_effects"], "fig3_transitions")'),
    ("markdown", "## Agreement"),
    (
        "code",
        'table("agreement_between_models", "Table 7. Agreement between models (primary panel), '
        'bootstrap 95% intervals")',
    ),
    (
        "code",
        'alphas = (("t2_alpha_nominal", "fig4_alpha_t2"), ("t3_alpha_ordinal", "fig5_alpha_t3"))\n'
        "for column, name in alphas:\n"
        '    between = T["agreement_between_models"]\n'
        '    figure(lambda d, c=column: figures.interval_bar(d, "condition", c, None, c), between, name)',
    ),
    (
        "code",
        'table("attribute_agreement", "Table 8. Attribute agreement analysis against the T2 rule")',
    ),
    ("markdown", "## Hypotheses"),
    (
        "code",
        'table("hypotheses", "Table 9. Hypotheses: metric, test, falsification condition and the '
        'mechanical outcome")',
    ),
    ("code", 'table("hypothesis_tests", "Table 10. Test results behind the hypotheses")'),
    ("markdown", "## Controlled baseline, position, grounding, reporting"),
    (
        "code",
        'table("baseline_vs_panel", "Table 11. Primary panel vs controlled baseline (descriptive)")',
    ),
    ("code", 'table("position_effect", "Table 12. Position effect (descriptive)")'),
    ("code", 'figure(figures.tercile_figure, T["position_effect"], "fig6_position")'),
    (
        "code",
        'table("grounding", "Table 13. Grounding of numeric claims and automatic error taxonomy")',
    ),
    ("code", 'print("Annotator agreement (Cohen\'s kappa):")\ndisplay(pd.DataFrame(kappa).T)'),
    ("code", 'table("parse_failure_rates", "Table 14. Parse-failure rates per model")'),
    ("code", 'table("run_counts", "Table 15. Runs logged")'),
]


def build() -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    nb.cells = [
        nbf.v4.new_markdown_cell(text) if kind == "markdown" else nbf.v4.new_code_cell(text)
        for kind, text in CELLS
    ]
    for i, cell in enumerate(nb.cells):
        cell["id"] = f"cell-{i:02d}"  # stable ids: rebuilding gives an identical file
    return nb


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target = root / "notebooks" / "analysis.ipynb"
    nb = build()
    nbf.validate(nb)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(nbf.writes(nb) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {target} ({len(nb.cells)} cells)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
