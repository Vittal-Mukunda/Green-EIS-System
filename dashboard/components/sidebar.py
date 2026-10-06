"""The left sidebar: brand, grouped navigation, the pilot dataset, and the display switch.

Navigation is a real `st.radio` (keyboard and screen-reader friendly, and its state is what
`?page=` reads and writes). CSS turns it into a grouped list: this module generates the per-page rules
(group headings and icons), because CSS cannot know which radio option is which page.
"""

from __future__ import annotations

import streamlit as st

from .icons import BRAND_MARK, PAGE_ICONS
from .markup import esc, render
from .page_header import GROUPS, group_of

NAV = '[data-testid="stSidebar"] [data-testid="stRadioGroup"] > div:nth-child({n})'


def nav_css(pages: list[str]) -> str:
    """Icon for every page, and a group heading above the first page of each group. The look of the
    heading and the icon is in layout.css; only the per-page content is generated here."""
    rules, previous = [], None
    for n, page in enumerate(pages, start=1):
        sel = NAV.format(n=n)
        rules.append(
            f'{sel} [data-testid="stRadioOption"]::before{{content:"{PAGE_ICONS.get(page, "circle")}"}}'
        )
        group = group_of(page)
        if group != previous:
            rules.append(f'{sel}::before{{content:"{group}";display:block}}')
            previous = group
    return "\n".join(rules)


def sidebar_brand_html() -> str:
    return (
        f'<div class="eis-brand">{BRAND_MARK}<div><div class="eis-brand-name">Green EIS</div>'
        '<div class="eis-brand-sub">Green Executive Information System</div></div></div>'
    )


def pilot_block_html(companies: int, sectors: int, latest_fy: str | None) -> str:
    rows = [
        ("Companies", str(companies)),
        ("Sectors", str(sectors)),
        ("Latest year loaded", latest_fy or "none"),
    ]
    body = "".join(
        f'<div class="eis-pilot-row"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in rows
    )
    return f'<div class="eis-pilot"><div class="eis-pilot-label">Pilot dataset</div>{body}</div>'


def render_sidebar(
    pages: list[str], pilot: dict, notice: str | None, captions: bool = False
) -> tuple[str, bool]:
    """Draw the sidebar and return (selected page, show real company names)."""
    with st.sidebar:
        render(sidebar_brand_html())
        page = st.radio("Page", pages, key="view", label_visibility="collapsed")
        render(pilot_block_html(pilot["companies"], pilot["sectors"], pilot["latest_fy"]))
        real_names = st.toggle(
            "Show real company names",
            value=True,
            help="Switch off to see the masked codes (CEM-01, STL-04 ...) that the models saw.",
        )
        if notice:
            st.info(notice)
    return page, real_names


__all__ = ["GROUPS", "nav_css", "render_sidebar"]
