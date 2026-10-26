"""The Study page, the seven analysis pages, Overall Findings and References, run through AppTest.

Literals about the real ASI 2023-24 results were read by hand from outputs/study_asi_2023-24.json and
outputs/gap_evidence_asi_2023-24.json (not recomputed): 24,154 factories; median error 6% (Estimated) and
75% (Default); Default 90th percentile 599%; nominal 90% interval covering 78%; top hotspot kept 96% of
2,411 factories; priority rule on 67 factories; 13 of 56 CSTEP cells flagged; coal 12.7% of emissions and
5.1% of spend; 257 of 2,442 multi-fuel factories where the biggest cost item is not the biggest emitter;
19,014 small factories with spend on a line that carries no quantity (18,235 on petrol, diesel and oil).
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "dashboard"))

import gap_data  # noqa: E402
import vocab  # noqa: E402

from greeneis import gaps, references  # noqa: E402
from greeneis.study import synthetic  # noqa: E402
from greeneis.study.run import run_study, write  # noqa: E402
from test_ui_pages import DASHBOARD, html, run, text  # noqa: E402


def charts(at) -> str:
    """The figures' own data and labels (a chart's text is not in the page's markup)."""
    return " ".join(c.proto.spec for c in at.get("plotly_chart"))


# ---- Study page ---------------------------------------------------------------------------------
def test_the_study_page_has_every_gap_and_each_required_part():
    at = run("Study", example=False)
    assert not at.exception, [e.value for e in at.exception]
    t = text(at)
    for g in gaps.GAPS:
        assert f"Gap {g.number}: {g.title}" in t, g.id
    for part in (
        "Originating study",
        "Citation",
        "What did the study investigate?",
        "What did the study find?",
        "What is the research gap, in very simple words?",
        "Why does the gap matter?",
        "What does GreenEIS do?",
        "Evidence available in this project",
        "Analysis status",
    ):
        assert t.count(f'<div class="q">{part}</div>') == len(gaps.GAPS), part
    # no invented gap: the Study page names exactly the registry's seven
    assert len(re.findall(r"Gap \d: ", t)) == len(gaps.GAPS)


def test_each_explore_button_opens_the_right_analysis_page():
    at = run("Study", example=False)
    buttons = [b for b in at.button if b.label == "Explore this analysis →"]
    assert len(buttons) == len(gaps.GAPS)
    for g, button in zip(gaps.GAPS, buttons, strict=True):
        assert button.key == f"go_study_{g.slug}", g.id
        at = run("Study", example=False)
        next(b for b in at.button if b.key == f"go_study_{g.slug}").click().run()
        assert at.session_state["view"] == g.nav_label, g.id
        assert not at.exception
        assert f"Gap {g.number}. {g.title}" in html(at), g.id


# ---- analysis pages -----------------------------------------------------------------------------
@pytest.mark.parametrize("g", gaps.GAPS, ids=lambda g: g.id)
def test_every_analysis_page_has_parts_a_to_h(g):
    at = run(g.nav_label, example=False)
    assert not at.exception, [e.value for e in at.exception]
    t = text(at)
    for part in (
        "A. Research question",
        "B. Academic context",
        "C. Data and scope",
        "D. Methodology",
        "E. Real-data results",
        "F. Findings and interpretation",
        "G. Contribution to the research gap",
        "H. Limitations and reproducibility",
    ):
        assert part in t, (g.id, part)
    assert g.status_text in t and g.title in t
    assert "does not certify" in t.lower()  # the standing estimate note


def test_gap_1_shows_what_the_returns_do_and_do_not_hold():
    at = run(vocab.gap_page(1), example=False)
    t = text(at)
    assert "24,154" in t and "68,641" in t
    assert "19,014" in t and "18,235" in t
    assert "spend only" in charts(at) and "Petrol, diesel and oil" in t
    assert "not metered" in t


def test_gap_2_shows_the_ranges_are_wrong_and_the_cstep_cells_disagree():
    t = text(run(vocab.gap_page(2), example=False))
    assert "599%" in t and "78%" in t
    assert "56 published emission figures" in t and "43 agree" in t and "13 do not" in t
    assert "we do not correct it" in t.lower()
    assert "110 MtCO2e" in t and "105 MtCO2e" in t
    assert "Supported" in t and "uncalibrated" in t.lower()


def test_gap_3_reports_the_priority_rule_as_weak_and_the_textile_cut_as_exploratory():
    t = text(run(vocab.gap_page(3), example=False))
    assert "96%" in t and "67 factories" in t
    assert "Textile factories only" in t and "1,105" in t and "exploratory" in t.lower()
    assert "Insufficient data" in t  # textile H5


def test_gap_4_shows_spend_against_emissions_for_real_fuels():
    at = run(vocab.gap_page(4), example=False)
    t = text(at)
    assert "87.3%" in charts(at) and "82.7%" in charts(at)  # electricity: spend and emission share
    assert "12.7%" in t and "5.1%" in t  # coal: emissions and spend share
    assert "257" in t and "2,442" in t and "10.5%" in t
    assert "INR 8,835 crore" in t


def test_gap_5_is_factor_arithmetic_and_says_no_unit_result_is_shown():
    at = run(vocab.gap_page(5), example=False)
    t = text(at)
    assert "No unit-level result is shown" in t
    assert "cannot be analysed with the data in hand" in t
    assert "48%" in t and "31%" in t  # coal and LPG break-even, worked by hand in test_gap_registry
    assert "Method check" in t and "not a result" in t


@pytest.mark.parametrize("n", [6, 7])
def test_gaps_6_and_7_say_the_data_cannot_answer_the_question(n):
    t = text(run(vocab.gap_page(n), example=False))
    assert "cannot be analysed with the data in hand" in t
    assert "Insufficient data" in t


def test_the_originating_paper_is_not_claimed_for_gaps_without_one():
    t = text(run(vocab.gap_page(4), example=False))
    assert "no originating paper verified" in t.lower()
    t = text(run(vocab.gap_page(1), example=False))
    assert "How this relates to the originating paper" in t


# ---- Overall Findings ---------------------------------------------------------------------------
def test_overall_findings_has_the_matrix_and_every_section():
    at = run("Overall Findings", example=False)
    assert not at.exception, [e.value for e in at.exception]
    t = text(at)
    for part in (
        "A. Executive summary",
        "B. Research coverage",
        "C. Consolidated findings matrix",
        "D. Key quantitative findings",
        "E. Cross-gap insights",
        "F. Contributions and unresolved questions",
        "G. Evidence traceability",
    ):
        assert part in t, part
    for column in (
        "Gap",
        "Research gap",
        "Originating paper",
        "Research question",
        "Data and method",
        "Key finding",
        "Supporting evidence",
        "Status",
        "Limitation",
        "View analysis",
    ):
        assert "<th" in t and f">{column}" in t, column
    assert t.count('href="?page=gap-') >= 2 * len(
        gaps.GAPS
    )  # a link per gap in the matrix and the trace
    for g in gaps.GAPS:
        assert f"?page={vocab.slug(g.nav_label)}" in t, g.id


def test_numbers_agree_between_the_analysis_pages_and_overall_findings():
    findings_text = text(run("Overall Findings", example=False))
    gap_text = {n: text(run(vocab.gap_page(n), example=False)) for n in (1, 2, 3, 4)}
    study_text = text(run("Study", example=False))
    # the same figure, worded the same, wherever a page reports it
    for needle, pages in {
        "24,154": (findings_text, gap_text[1]),
        "599%": (findings_text, gap_text[2]),
        "96%": (findings_text, gap_text[3]),
        "67 factories": (findings_text, gap_text[3], study_text),
        "257 of 2,442": (findings_text, gap_text[4], study_text),
        "19,014": (findings_text, gap_text[1]),
    }.items():
        for page in pages:
            assert needle in page, needle


def test_overall_findings_counts_come_from_the_registry():
    t = text(run("Overall Findings", example=False))
    partial = [g.id for g in gaps.GAPS if g.status == "partial"]
    assert ", ".join(partial) in t  # G1, G2, G3, G4
    assert "none yet" in t  # nothing is 'addressed with evidence'
    assert "Companies" in t and "no company reports are used" in t


def test_cross_gap_insights_claim_no_link_the_data_do_not_support():
    t = text(run("Overall Findings", example=False))
    assert "not connected to the others by data" in t
    assert "not independent confirmations" in t


# ---- References ---------------------------------------------------------------------------------
def test_the_references_page_lists_every_registry_entry_once():
    at = run("References", example=False)
    assert not at.exception, [e.value for e in at.exception]
    h = html(at)
    for ref in references.REFERENCES:
        assert h.count(f'id="{references.anchor(ref.key)}"') == 1, ref.key
    assert "Not used in this project" in text(at)
    assert "BRSR" in text(at) and "SDG" in text(
        at
    )  # the categories left empty are named, not padded


def test_every_citation_link_on_every_page_points_at_a_real_reference():
    keys = {r.key for r in references.REFERENCES}
    seen = set()
    for page in ["Study", *vocab.ANALYSIS_PAGES, "Overall Findings"]:
        found = re.findall(r"\?page=references#ref-([a-z0-9_]+)", html(run(page, example=False)))
        assert found, page
        assert set(found) <= keys, (page, set(found) - keys)
        seen |= set(found)
    # every source the gap registry names is cited by at least one page
    registry = {s.ref for g in gaps.GAPS for s in g.sources}
    assert registry <= seen | {"refdoc"}, registry - seen


def test_the_references_page_marks_unverified_sources():
    t = text(run("References", example=False))
    assert "Unverified: check before citing" in t and "Read in the original" in t
    assert "Cited on: Gap" in t


# ---- data integrity -----------------------------------------------------------------------------
def test_a_synthetic_result_is_never_shown_on_a_research_page(tmp_path, monkeypatch):
    out = tmp_path / "pub"
    result = run_study(synthetic.generate(300, 2), "synthetic", "invented", seed=2, n_boot=100)
    write(result, out / gap_data.MAIN_FILE)
    monkeypatch.setattr(gap_data, "OUTPUTS", out)
    for page in (vocab.gap_page(1), vocab.gap_page(2), "Overall Findings"):
        at = run(page, example=False)
        assert not at.exception, page
        assert "SYNTHETIC" not in text(at) and "24,154" not in text(at), page
        assert "not available" in text(at).lower(), page


def test_pages_say_so_when_the_result_files_are_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(gap_data, "OUTPUTS", tmp_path / "nothing")
    for page in ["Study", *vocab.ANALYSIS_PAGES, "Overall Findings", "References"]:
        at = run(page, example=False)
        assert not at.exception, (page, [e.value for e in at.exception])
    assert "not available" in text(run(vocab.gap_page(4), example=False)).lower()


def test_the_data_entry_page_is_not_in_the_navigation():
    at = run("Study", example=False)
    options = list(at.sidebar.radio[0].options)
    assert options == list(vocab.PAGES)
    for gone in (
        "Data entry",
        "Summary",
        "Hotspots",
        "What-if",
        "Report",
        "Study results",
        "About",
    ):
        assert gone not in options
    assert (DASHBOARD / "legacy_app.py").is_file()  # the code is kept, only the navigation changed
