"""One icon family for the whole interface: Material Symbols (Rounded), the font Streamlit already
loads. An icon is a ligature, so `icon("home")` is the text "home" drawn as a glyph. Icons are
decorative (aria-hidden); the words beside them carry the meaning.
"""

from __future__ import annotations

from .markup import esc

# page -> icon, used by the sidebar and the home page
PAGE_ICONS = {
    "Home": "home",
    "Sectors": "stacks",
    "KPI scorecard": "grid_view",
    "Companies": "apartment",
    "Compare companies": "compare_arrows",
    "Query and chart": "query_stats",
    "Compliance check": "fact_check",
    "Data quality register": "rule",
    "Sources and filings": "folder_open",
    "Data verification": "verified",
    "Metrics guide": "functions",
    "About": "info",
    "Model reliability scorecard": "monitoring",
    "C1 vs C2": "difference",
    "Disagreement queue": "forum",
    "Annotation": "edit_note",
    "Audit trail": "history",
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
