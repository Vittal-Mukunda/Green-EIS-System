"""The interface components: what they say, what they escape, and the rules the redesign must keep.

The components are plain functions that return HTML, so they are tested without a browser; the pages
that use them are covered by the AppTest suites (test_pages.py, test_dashboard.py, test_eis_views.py).
"""

from __future__ import annotations

import re
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "dashboard"))

from components import app_shell  # noqa: E402
from components.alerts import callout_html  # noqa: E402
from components.comparison_table import (  # noqa: E402
    Cell,
    MatrixColumn,
    MatrixGroup,
    MatrixRow,
    position_cell_html,
    scorecard_html,
)
from components.data_quality_table import (  # noqa: E402
    exceptions_html,
    movements_html,
    register_table_html,
)
from components.empty_state import empty_state_html  # noqa: E402
from components.evidence_card import (  # noqa: E402
    Check,
    Evidence,
    check_groups_html,
    evidence_card_html,
)
from components.icons import PAGE_ICONS  # noqa: E402
from components.markup import esc  # noqa: E402
from components.page_header import GROUPS, breadcrumb_html, group_of  # noqa: E402
from components.people import People  # noqa: E402
from components.provenance import Step, chain_html, formula_words  # noqa: E402
from components.sidebar import nav_css  # noqa: E402
from components.status_badge import POSITIONS, badge, position_chip  # noqa: E402
from components.topbar import fmt_date, search_targets  # noqa: E402

from gauge import vocab  # noqa: E402

POSITION_WORDS = {
    "Better third",
    "Middle third",
    "Weaker third",
    "No clear difference",
    "Data check",
    "Too few to place",
}


def _visible(html: str) -> str:
    """The text a person reads: tags and tooltip attributes removed."""
    return re.sub(r"<[^>]+>", " ", html)


# ---- positions are words, never ratings ---------------------------------------------------------
def test_a_position_uses_only_the_six_agreed_words():
    assert {label for label, _ in POSITIONS.values()} == POSITION_WORDS


@pytest.mark.parametrize("band", list(POSITIONS))
def test_every_position_chip_and_cell_carries_its_word_so_colour_is_never_the_only_signal(band):
    label = POSITIONS[band][0]
    assert label in position_chip(band)
    assert label in position_cell_html(Cell("12.3", band, "2 of 5"))


def test_a_data_check_is_never_given_a_rank():
    cell = _visible(position_cell_html(Cell("103.5", "data check", "")))
    chip = _visible(position_chip("data check"))
    assert "Data check" in cell and " of " not in cell
    assert "rank" not in chip.lower() and "#1" not in chip


def test_the_interface_never_calls_a_position_a_rating_or_a_score():
    html = "".join(position_chip(b) for b in POSITIONS) + "".join(
        position_cell_html(Cell("1", b, "1 of 5")) for b in POSITIONS
    )
    for forbidden in ("rating", "ESG score", "good company", "bad company"):
        assert forbidden.lower() not in _visible(html).lower()


def test_a_missing_figure_says_so_instead_of_leaving_a_blank():
    assert "not loaded" in position_cell_html(Cell(empty=True))


# ---- escaping -----------------------------------------------------------------------------------
def test_text_from_the_data_is_escaped_wherever_it_is_drawn():
    nasty = "<script>alert(1)</script> & Co"
    assert "<script>" not in esc(nasty)
    row = MatrixRow(nasty, nasty, [Cell("1", "better third", "1 of 5", nasty)])
    html = scorecard_html([MatrixGroup(nasty, [row])], [MatrixColumn(nasty, nasty, nasty)])
    assert "<script>" not in html and "&amp; Co" in html
    assert "<script>" not in callout_html("info", nasty, nasty)
    assert "<script>" not in empty_state_html(nasty, nasty)
    assert "<script>" not in badge(nasty, "warn", tip=nasty)
    assert "<script>" not in evidence_card_html(nasty, [Evidence("ok", nasty, esc(nasty))], nasty)
    assert "<script>" not in check_groups_html([(nasty, [Check("pass", nasty, nasty, nasty)])])
    assert "<script>" not in chain_html([Step("insights", nasty, nasty, nasty, esc(nasty))])


# ---- exception lists ----------------------------------------------------------------------------
def test_an_exception_is_a_figure_to_check_and_not_a_verdict_on_the_company():
    html = exceptions_html(
        [
            {
                "code": "CEM-03",
                "fy": "FY2025-26",
                "who": "J.K. Cement Limited",
                "what": "Waste recovery rate",
                "value": "103.5",
                "unit": "%",
                "why": "Waste recovered exceeds waste generated.",
            }
        ]
    )
    assert "Data check" in html and "103.5" in html and "FY2025-26" in html
    for forbidden in ("misreport", "fraud", "violat", "breach"):
        assert forbidden not in html.lower()


def test_movement_bars_saturate_so_one_outlier_does_not_flatten_the_rest():
    big = {
        "who": "A",
        "what": "m",
        "change": 3635.0,
        "movement": "better",
        "prev": "1",
        "now": "2",
        "unit": "%",
    }
    small = {**big, "who": "B", "change": 10.0}
    html = movements_html([big, small])
    widths = [float(w) for w in re.findall(r"width:([0-9.]+)%", html)]
    assert widths == [50.0, 5.0]  # the outlier fills its half, a 10% move is a tenth of a half
    assert "+3635.0%" in html  # the label stays exact


def test_the_register_row_shows_status_reviewer_and_date_or_says_none():
    row = {
        "code": "CEM-03",
        "sector": "Cement",
        "fy": "FY2025-26",
        "metric": "Waste recovery rate",
        "reported": "103.5 %",
        "rule": "recovered_le_generated",
        "severity": "error",
        "issue": "waste recovered exceeds waste generated",
        "status": "Needs verification",
        "tone": "warn",
        "reviewer": None,
        "verified_on": None,
    }
    html = register_table_html(pd.DataFrame([row]), lambda code: "J.K. Cement Limited")
    assert "103.5 %" in html and "Needs verification" in html
    assert "not yet reviewed" in html and "J.K. Cement Limited" in html
    done = {
        **row,
        "status": "Reviewed: matches filing",
        "tone": "ok",
        "reviewer": "Dana",
        "verified_on": "2026-10-04",
    }
    html = register_table_html(pd.DataFrame([done]), lambda code: code)
    assert "Dana" in html and "2026-10-04" in html and "not yet reviewed" not in html


# ---- shell, navigation --------------------------------------------------------------------------
def test_every_page_has_an_icon_and_a_group():
    for page in vocab.DASHBOARD_VIEWS:
        assert page in PAGE_ICONS, page
        assert group_of(page) != "Green EIS", page


def test_the_sidebar_groups_follow_the_display_order():
    order = [p for pages in list(GROUPS.values())[:4] for p in pages]
    assert order == list(vocab.EIS_VIEWS)


def test_navigation_css_puts_a_heading_above_the_first_page_of_each_group_only():
    css = nav_css(list(vocab.DASHBOARD_VIEWS))
    for heading in ("Overview", "Analysis", "Assurance", "Reference", "Model evaluation"):
        assert css.count(f'content:"{heading}"') == 1
    assert 'nth-child(1) [data-testid="stRadioOption"]::before{content:"home"}' in css
    subset = nav_css(["Home", "Sources and filings"])
    assert 'content:"Overview"' in subset and 'content:"Assurance"' in subset
    assert 'content:"Analysis"' not in subset


def test_the_breadcrumb_names_the_group_and_the_page():
    html = breadcrumb_html("Data quality register")
    assert "Green EIS" in html and "Assurance" in html and "Data quality register" in html
    assert 'aria-label="Breadcrumb"' in html


def test_search_offers_pages_sectors_and_companies_and_follows_the_names_switch():
    directory = pd.DataFrame(
        [
            {
                "code": "CEM-01",
                "name": "UltraTech Cement Limited",
                "symbol": "ULTRACEMCO",
                "sector": "Cement",
            },
            {
                "code": "ITS-01",
                "name": "Infosys Limited",
                "symbol": "INFY",
                "sector": "IT Services",
            },
        ]
    )
    pages = ["Home", "Sectors", "Companies"]
    real = search_targets(pages, People(directory, True), ["Cement", "IT Services"])
    assert real["Page · Sectors"] == ("page", "Sectors")
    assert real["Sector · Cement"] == ("sector", "Cement")
    assert real["Company · UltraTech Cement Limited · Cement"] == ("company", "CEM-01")
    masked = search_targets(pages, People(directory, False), ["Cement"])
    assert "Company · CEM-01 · Cement" in masked and not any("UltraTech" in k for k in masked)
    assert not any(
        k.startswith("Company") for k in search_targets(["Home"], People(directory, True), [])
    )


@pytest.mark.parametrize(
    ("iso", "text"),
    [("2026-10-02", "2 Oct 2026"), ("2026-01-15", "15 Jan 2026"), (None, "date not recorded")],
)
def test_dates_are_written_for_people(iso, text):
    assert fmt_date(iso) == text


# ---- provenance ---------------------------------------------------------------------------------
def test_the_formula_shown_is_the_configured_one_with_labels():
    labels = {
        "water_consumption": "Water consumption",
        "revenue_from_operations": "Revenue from operations",
    }
    assert formula_words("water_consumption / revenue_from_operations", labels) == (
        "Water consumption / Revenue from operations"
    )


def test_the_chain_draws_each_step_in_order():
    steps = [
        Step("insights", "KPI", "8.42", "x"),
        Step("fingerprint", "SHA-256 fingerprint", "", "", "abcd"),
    ]
    html = chain_html(steps)
    assert (
        html.index("KPI") < html.index("SHA-256 fingerprint") and html.count("eis-step-body") == 2
    )


# ---- stylesheets --------------------------------------------------------------------------------
def test_the_stylesheets_contain_no_tag_like_text_because_st_html_drops_the_whole_style_block():
    css = "".join(
        (app_shell.STYLES / name).read_text(encoding="utf-8") for name in app_shell.SHEETS
    )
    assert not re.search(r"<[/\w!]", css)


def test_every_stylesheet_uses_tokens_rather_than_hard_coded_brand_colours():
    theme = (app_shell.STYLES / "theme.css").read_text(encoding="utf-8")
    for token in (
        "--accent",
        "--bg",
        "--surface",
        "--border",
        "--text",
        "--radius",
        "--shadow-sm",
        "--font",
        "--control-h",
    ):
        assert f"{token}:" in theme
    components = (app_shell.STYLES / "components.css").read_text(encoding="utf-8")
    assert components.count("var(--") > 100


def test_the_interface_uses_no_emoji():
    import pathlib

    emoji = re.compile("[\U0001f300-\U0001faff☀-➿]")
    root = pathlib.Path(__file__).resolve().parents[1] / "dashboard"
    for path in [
        *root.glob("*.py"),
        *(root / "components").glob("*.py"),
        *(root / "styles").glob("*.css"),
    ]:
        offending = emoji.findall(path.read_text(encoding="utf-8"))
        # the check marks used in the plain-text STATUS_TEXT of the data tables are typographic, not emoji
        offending = [c for c in offending if c not in "✔✖ℹ▲"]
        assert not offending, (path.name, offending)
