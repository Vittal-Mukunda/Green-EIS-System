"""The left sidebar: brand, grouped navigation, and the unit being worked on.

Navigation is a real `st.radio` (keyboard and screen-reader friendly, and its state is what
`?page=` reads and writes). CSS turns it into a grouped list: this module generates the per-page rules
(group headings and icons), because CSS cannot know which radio option is which page.
"""

from __future__ import annotations

from collections.abc import Callable

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
        f'<div class="eis-brand">{BRAND_MARK}<div><div class="eis-brand-name">GreenEIS</div>'
        '<div class="eis-brand-sub">Green Enterprise Information System</div></div></div>'
    )


def unit_block_html(unit: dict) -> str:
    """The unit being worked on: name, period, number of activities, and whether it is the example."""
    rows = [
        ("Unit", unit.get("name") or "not named"),
        ("Period", unit.get("period") or "none"),
        ("Activities", str(unit.get("activities", 0))),
    ]
    body = "".join(
        f'<div class="eis-pilot-row"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in rows
    )
    label = "Illustrative example" if unit.get("is_example") else "Current unit"
    return f'<div class="eis-pilot"><div class="eis-pilot-label">{esc(label)}</div>{body}</div>'


def render_sidebar(
    pages: list[str],
    unit: dict,
    notice: str | None,
    extra: Callable[[], None] | None = None,
) -> str:
    """Draw the sidebar and return the selected page. `extra` draws controls under the unit block."""
    with st.sidebar:
        render(sidebar_brand_html())
        page = st.radio("Page", pages, key="view", label_visibility="collapsed")
        render(unit_block_html(unit))
        if extra:
            extra()
        if notice:
            st.info(notice)
    return page


__all__ = ["GROUPS", "nav_css", "render_sidebar"]
