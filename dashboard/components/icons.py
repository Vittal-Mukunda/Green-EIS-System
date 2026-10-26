"""One icon family for the whole interface: Material Symbols (Rounded), the font Streamlit already
loads. An icon is a ligature, so `icon("home")` is the text "home" drawn as a glyph. Icons are
decorative (aria-hidden); the words beside them carry the meaning.
"""

from __future__ import annotations

from greeneis import gaps

from .markup import esc

# page -> icon, used by the sidebar and the home page
GAP_ICONS = {
    1: "database",
    2: "verified",
    3: "whatshot",
    4: "payments",
    5: "tune",
    6: "build",
    7: "description",
}

PAGE_ICONS = {
    "Study": "menu_book",
    **{gaps.get(n).nav_label: glyph for n, glyph in GAP_ICONS.items()},
    "Overall Findings": "fact_check",
    "References": "library_books",
    "Data entry": "edit_note",
    "Summary": "dashboard",
    "Hotspots": "whatshot",
    "What-if": "tune",
    "Report": "description",
    "Study results": "science",
    "Factors and method": "functions",
    "About": "info",
}

# status -> icon (always shown with a word)
STATUS_ICONS = {
    "pass": "check_circle",
    "ok": "check_circle",
    "attention": "warning",
    "warn": "warning",
    "fail": "cancel",
    "danger": "cancel",
    "info": "info",
    "na": "remove_circle",
}


def icon(name: str, size: str = "", fill: bool = False) -> str:
    """An inline icon. `size` is "", "sm" or "lg"."""
    classes = " ".join(c for c in ("eis-icon", size, "fill" if fill else "") if c)
    return f'<span class="{classes}" aria-hidden="true">{esc(name)}</span>'


# The product mark: a leaf glyph in a rounded square. (st.html strips inline SVG, so the mark uses the
# icon font like every other icon.)
BRAND_MARK = (
    '<span class="eis-mark" aria-hidden="true"><span class="eis-icon fill">eco</span></span>'
)
