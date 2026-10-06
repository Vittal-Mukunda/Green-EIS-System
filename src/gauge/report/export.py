"""`gauge export`: result tables as CSV (numbers) and one Markdown report, written to results_dir.

The report states what was computed and the mechanical outcome of each pre-defined check; it makes no
interpretive claim (the owner writes those). Results from mock runs carry a banner saying so.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from gauge.config import StudyConfig
from gauge.report.tables import all_tables, to_markdown, uses_mock_runs

MOCK_BANNER = (
    "> **MOCK DATA.** These tables come from a dry run (synthetic companies, MockRunner). The numbers "
    "exercise the code and say nothing about any real model or company."
)
INTRO = (
    "Pilot-scale and exploratory: 20 companies, 2 repetitions per model and condition, 4 primary "
    "models and one controlled baseline. Every interval is 95%: exact binomial for proportions, "
    "percentile bootstrap over companies (resamples as configured) for agreement statistics. "
    "Companies appear in both repetitions and conditions, so p-values are indicative only; Holm's "
    "correction is applied within each hypothesis family. The controlled baseline is reported next to "
    "the primary panel and never pooled with it. T2 is scored against the frozen rule; T3 has no "
    "correct value. No model scores another."
)

SECTIONS = [
    (
        "scorecard",
        "Model scorecard (per model and condition)",
        "T2 accuracy against the frozen rule, share of judgments valid, repeatability between "
        "repetition 1 and 2 (T2 agreement and Cohen's kappa; T3 quadratic-weighted kappa).",
    ),
    (
        "context_effects",
        "Effect of added context (C1 to C2, per model)",
        "Context distortion = share of (repetition, company) pairs whose T2 class differs between C1 and "
        "C2. T3 transitions are labelled by the T3 update rule.",
    ),
    (
        "agreement_between_models",
        "Agreement between models (primary panel, per condition)",
        "Krippendorff's alpha (nominal for T2, ordinal for T3), Fleiss' kappa for T2, and mean pairwise "
        "kappa, with percentile bootstrap intervals over companies; within-model kappa on the same scale.",
    ),
    (
        "attribute_agreement",
        "Attribute agreement analysis (T2, standard = frozen rule)",
        "Appraisers are the models, trials the repetitions. Percentages are over companies with all "
        "needed ratings valid; intervals are exact binomial.",
    ),
    ("hypotheses", "Hypotheses and the outcome of their pre-defined checks", ""),
    (
        "hypothesis_tests",
        "Test results behind the hypotheses (and the supplementary rating-shift test S1)",
        "",
    ),
    (
        "baseline_vs_panel",
        "Primary panel vs controlled baseline (descriptive differences, no tests)",
        "difference = baseline minus the mean of the primary panel.",
    ),
    (
        "position_effect",
        "Position effect (descriptive)",
        "Odds ratios per one position later in the prompt, with model and condition as fixed effects.",
    ),
    (
        "grounding",
        "Grounding of numeric claims and the automatic part of the error taxonomy",
        "Numeric claims are checked against the values printed in that model's prompt (within 1% after "
        "unit normalisation). Non-numeric claims and the interpretation/ambiguity categories await "
        "human annotation.",
    ),
    ("parse_failure_rates", "Parse-failure rates per model", ""),
    ("run_counts", "Runs logged", ""),
]


def _per_hypothesis(df) -> list[str]:
    """One compact table per hypothesis: the long table has columns that only one test fills."""
    if df.empty:
        return ["*(no rows)*", ""]
    out: list[str] = []
    for hypothesis, part in df.groupby("hypothesis", sort=False):
        keep = [c for c in part.columns if c != "hypothesis" and part[c].notna().any()]
        out += [f"**{hypothesis}**", "", to_markdown(part[keep].reset_index(drop=True)), ""]
    return out


def export_results(session: Session, cfg: StudyConfig) -> list[Path]:
    """Write one CSV per table and RESULTS.md; returns the paths."""
    out = cfg.results_path
    out.mkdir(parents=True, exist_ok=True)
    tables = all_tables(session)
    written: list[Path] = []
    for name, df in tables.items():
        path = out / f"{name}.csv"
        df.to_csv(path, index=False, lineterminator="\n")
        written.append(path)

    lines = ["# Results", ""]
    if uses_mock_runs(session):
        lines += [MOCK_BANNER, ""]
    lines += [INTRO, "", f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `gauge export`.", ""]
    for name, title, note in SECTIONS:
        lines += [f"## {title}", ""]
        if note:
            lines += [note, ""]
        if name == "hypothesis_tests":
            lines += _per_hypothesis(tables[name])
        else:
            lines += [to_markdown(tables[name]), ""]
    report = out / "RESULTS.md"
    report.write_bytes("\n".join(lines).encode("utf-8"))
    written.append(report)
    return written
