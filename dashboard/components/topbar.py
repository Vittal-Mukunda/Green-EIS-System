"""The top bar: brand, page search, data status, help.

Search jumps to a page. It only navigates; it never queries data. There is no user system in this
application, so there is no account menu.
"""

from __future__ import annotations

import streamlit as st

from .icons import BRAND_MARK
from .markup import esc, render
from .navigation import open_page

SEARCH_KEY = "eis_search"


def search_targets(pages: list[str]) -> dict[str, str]:
    """Label -> page for everything the search can open."""
    return {f"Page · {page}": page for page in pages}


def _jump(targets: dict[str, str]) -> None:
    choice = st.session_state.get(SEARCH_KEY)
    st.session_state[SEARCH_KEY] = None
    page = targets.get(choice)
    if page:
        open_page(page)


def status_html(text: str, tone: str = "") -> str:
    """The data status, e.g. 'Illustrative example · not real data'. `tone` is '' or 'warn'."""
    dot = "eis-dot warn" if tone == "warn" else "eis-dot"
    return f'<div class="eis-status"><span class="{dot}"></span><span>{esc(text)}</span></div>'


def render_topbar(pages: list[str], status_text: str, status_tone: str = "") -> None:
    with st.container(key="eis-topbar"):
        brand, search, state, help_col = st.columns(
            [2.4, 3.2, 4.2, 1.1], vertical_alignment="center"
        )
        with brand:
            render(
                f'<div class="eis-topbar-brand">{BRAND_MARK}<div><div class="eis-topbar-title">GreenEIS</div>'
                '<div class="eis-topbar-sub">Green Enterprise Information System</div></div></div>'
            )
        with search:
            targets = search_targets(pages)
            with st.container(key="eis-search"):
                st.selectbox(
                    "Search",
                    list(targets),
                    index=None,
                    placeholder="Search pages",
                    key=SEARCH_KEY,
                    label_visibility="collapsed",
                    on_change=_jump,
                    args=(targets,),
                )
        with state:
            render(status_html(status_text, status_tone))
        with help_col:
            target = next((p for p in ("About", "Factors and method") if p in pages), None)
            if target:
                with st.container(key="eis-help"):
                    st.button(
                        "Help",
                        key="eis_help_button",
                        icon=":material/help:",
                        on_click=open_page,
                        args=(target,),
                        help=f"Open {target}",
                    )
