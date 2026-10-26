"""The interface components: what they say, what they escape, and the rules the design must keep.

The components are plain functions that return HTML, so they are tested without a browser; the pages that
use them are covered by test_ui_pages.py.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "dashboard"))

import vocab  # noqa: E402
from components import app_shell  # noqa: E402
from components.alerts import callout_html  # noqa: E402
from components.data_table import Column, Html, table_html  # noqa: E402
from components.empty_state import empty_state_html  # noqa: E402
from components.format import (  # noqa: E402
    fmt_figure,
    fmt_inr,
    fmt_number,
    fmt_pct,
    fmt_t,
    fmt_value,
)
from components.icons import PAGE_ICONS  # noqa: E402
from components.kpi_card import stat_strip_html  # noqa: E402
from components.markup import attrs, esc  # noqa: E402
from components.page_header import GROUPS, breadcrumb_html, group_of  # noqa: E402
from components.sidebar import nav_css, unit_block_html  # noqa: E402
from components.status_badge import (  # noqa: E402
    DATA_CLASSES,
    badge,
    data_class_badge,
    trust_band_badge,
)
from components.topbar import search_targets, status_html  # noqa: E402


# ---- escaping -----------------------------------------------------------------------------------
def test_text_is_escaped_everywhere_it_can_come_from_a_person():
    nasty = '<script>alert("x")</script>'
    assert "<script>" not in esc(nasty)
    assert "<script>" not in callout_html("info", nasty, nasty)
    assert "<script>" not in badge(nasty, tip=nasty)
    assert "<script>" not in empty_state_html(nasty, nasty)
    assert "<script>" not in stat_strip_html([(nasty, nasty, nasty)])
    assert "<script>" not in table_html([Column(nasty)], [[nasty]])
    assert "<script>" not in unit_block_html({"name": nasty, "period": nasty, "activities": 1})
    assert "<script>" not in status_html(nasty)


def test_attrs_skips_empty_values():
    assert attrs(cls="a", title="") == ' class="a"'
    assert attrs(data_tip="x") == ' data-tip="x"'


# ---- numbers ------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1234.5, "1,234"),
        (123.4, "123"),
        (12.34, "12.3"),
        (1.234, "1.23"),
        (0.1234, "0.123"),
        (0.000123, "0.00012"),
    ],
)
def test_numbers_are_readable_and_never_scientific(value, text):
    # 1234.5 rounds half to even under the f-string, so allow either neighbour
    got = fmt_number(value)
    assert got == text or got == "1,235"
    assert "e" not in got


def test_unit_and_percentage_formatting():
    assert fmt_figure(103.456, "%") == "103.5" and fmt_value(103.456, "%") == "103.5 %"
    assert fmt_value(float("nan"), "tCO2e") == "not available"
    assert fmt_t(38.966190955) == "38.97" and fmt_t(1204.51) == "1,204.51" and fmt_t(None) == "n/a"
    assert fmt_pct(0.4853323) == "48.5%" and fmt_pct(None) == "n/a"
    assert fmt_inr(4758.99) == "4,759" and fmt_inr(None) == "n/a"


# ---- data classes and badges --------------------------------------------------------------------
def test_each_data_class_has_a_word_an_icon_and_an_explanation():
    assert set(DATA_CLASSES) == {"measured", "estimated", "default"}
    for cls in DATA_CLASSES:
        html = data_class_badge(cls)
        label, _tone, glyph, tip = DATA_CLASSES[cls]
        assert label in html and glyph in html and 'data-tip="' in html and tip[:20] in html


def test_trust_bands_are_worded_not_only_coloured():
    for band, word in (("high", "High trust"), ("medium", "Medium trust"), ("low", "Low trust")):
        assert word in trust_band_badge(band)
    assert "Not available" in trust_band_badge("not available")


# ---- tables -------------------------------------------------------------------------------------
def test_table_aligns_numbers_marks_the_first_column_and_shows_missing_as_na():
    html = table_html(
        [Column("Activity"), Column("tCO2e", numeric=True, note="per period"), Column("Cost")],
        [["Coal", "18.91", None], ["Diesel", "5.47", Html("<b>ok</b>")]],
    )
    assert html.count("<tr>") == 3  # header + two rows
    assert 'class="firstcol num"' not in html and 'class="firstcol"' in html
    assert 'class="num"' in html and "per period" in html
    assert 'class="eis-na">n/a' in html and "<b>ok</b>" in html
    assert "<b>Coal</b>" in html


def test_table_refuses_rows_of_the_wrong_length():
    with pytest.raises(ValueError):
        table_html([Column("A"), Column("B")], [["only one"]])


def test_stat_strip_sets_its_column_count():
    html = stat_strip_html([("a", "1", "x"), ("b", "2", "y"), ("c", "3", "z")])
    assert "--n:3" in html and html.count("eis-kpi-value") == 3


# ---- shell, navigation --------------------------------------------------------------------------
def test_every_page_has_an_icon_a_group_and_a_note():
    for page in vocab.PAGES:
        assert page in PAGE_ICONS, page
        assert group_of(page) != "GreenEIS", page
        assert page in vocab.PAGE_NOTES, page
    assert set(PAGE_ICONS) == set(vocab.PAGES)


def test_the_sidebar_groups_follow_the_display_order():
    assert [p for pages in GROUPS.values() for p in pages] == list(vocab.PAGES)


def test_navigation_css_puts_a_heading_above_the_first_page_of_each_group_only():
    css = nav_css(list(vocab.PAGES))
    for heading in GROUPS:
        assert css.count(f'content:"{heading}"') == 1
    assert 'nth-child(1) [data-testid="stRadioOption"]::before{content:"home"}' in css
    subset = nav_css(["Summary", "About"])
    assert 'content:"Unit"' in subset and 'content:"Reference"' in subset
    assert 'content:"Study"' not in subset and 'content:"Overview"' not in subset


def test_the_breadcrumb_names_the_group_and_the_page():
    html = breadcrumb_html("Hotspots")
    assert "GreenEIS" in html and "Unit" in html and "Hotspots" in html
    assert 'aria-label="Breadcrumb"' in html


def test_search_only_offers_pages():
    targets = search_targets(["Summary", "About"])
    assert targets == {"Page · Summary": "Summary", "Page · About": "About"}


def test_slug_is_a_stable_address():
    assert (
        vocab.slug("What-if") == "what-if"
        and vocab.slug("Factors and method") == "factors-and-method"
    )
    assert len({vocab.slug(p) for p in vocab.PAGES}) == len(vocab.PAGES)


def test_the_unit_block_says_when_it_is_the_example():
    assert "Illustrative example" in unit_block_html(
        {"name": "X", "period": "p", "activities": 4, "is_example": True}
    )
    assert "Current unit" in unit_block_html({"name": "X", "period": "p", "activities": 4})


def test_the_status_dot_can_warn():
    assert "eis-dot warn" in status_html("example", "warn") and "eis-dot warn" not in status_html(
        "ok"
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
    emoji = re.compile("[\U0001f300-\U0001faff☀-➿]")
    root = pathlib.Path(__file__).resolve().parents[1] / "dashboard"
    for path in [
        *root.glob("*.py"),
        *(root / "components").glob("*.py"),
        *(root / "styles").glob("*.css"),
    ]:
        offending = emoji.findall(path.read_text(encoding="utf-8"))
        assert not offending, (path.name, offending)


def test_pages_do_not_write_css_or_html_structure_themselves():
    """Pages call components. Raw markup belongs in dashboard/components/."""
    root = pathlib.Path(__file__).resolve().parents[1] / "dashboard"
    for path in [
        root / "pages_public.py",
        root / "pages_unit.py",
        root / "pages_study.py",
        root / "pages_reference.py",
        root / "app.py",
    ]:
        text = path.read_text(encoding="utf-8")
        assert "<style" not in text and "unsafe_allow_html" not in text, path.name
        assert not re.search(r"""['"]<(div|span|table|h[1-6])\b""", text), path.name
