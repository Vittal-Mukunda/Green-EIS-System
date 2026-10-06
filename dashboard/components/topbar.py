"""The top bar: brand, global search, dataset status, help.

Search jumps to a page, a sector or a company. It only navigates; it never queries the data, so it
needs no query language. There is no user system in this application, so there is no account menu.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from .icons import BRAND_MARK
from .markup import esc, render
from .navigation import open_company, open_page, open_sector

SEARCH_KEY = "eis_search"


def fmt_date(iso: str | date | None) -> str:
    """2026-10-02 as 2 Oct 2026; an unrecorded date as 'date not recorded'."""
    if not iso:
        return "date not recorded"
    try:
        d = iso if isinstance(iso, date) else date.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    return f"{d.day} {d.strftime('%b %Y')}"


def search_targets(pages: list[str], people, sectors: list[str]) -> dict[str, tuple[str, str]]:
    """Label -> (kind, value) for everything the search can open."""
    targets: dict[str, tuple[str, str]] = {}
    for page in pages:
        targets[f"Page · {page}"] = ("page", page)
    if "Sectors" in pages:
        for sector in sectors:
            targets[f"Sector · {sector}"] = ("sector", sector)
    if "Companies" in pages:
        for code in people.codes:
            targets[f"Company · {people.label(code)} · {people.sector(code)}"] = ("company", code)
    return targets


def _jump(targets: dict[str, tuple[str, str]]) -> None:
    choice = st.session_state.get(SEARCH_KEY)
    st.session_state[SEARCH_KEY] = None
    kind, value = targets.get(choice, (None, None))
    if kind == "page":
        open_page(value)
    elif kind == "sector":
        open_sector(value)
    elif kind == "company":
        open_company(value)


def status_html(latest_fy: str | None, retrieved_on, filings: int) -> str:
    return (
        '<div class="eis-status"><span class="eis-dot"></span>'
        f"<span>Pilot dataset · {esc(latest_fy or 'no filings')} · {filings} filings · "
        f"retrieved {esc(fmt_date(retrieved_on))}</span></div>"
    )


def render_topbar(pages: list[str], people, sectors: list[str], status: dict) -> None:
    with st.container(key="eis-topbar"):
        brand, search, state, help_col = st.columns(
            [2.4, 3.2, 4.2, 1.1], vertical_alignment="center"
        )
        with brand:
            render(
                f'<div class="eis-topbar-brand">{BRAND_MARK}<div><div class="eis-topbar-title">Green EIS</div>'
                '<div class="eis-topbar-sub">Green Executive Information System</div></div></div>'
            )
        with search:
            targets = search_targets(pages, people, sectors)
            with st.container(key="eis-search"):
                st.selectbox(
                    "Search",
                    list(targets),
                    index=None,
                    placeholder="Search companies, sectors and pages",
                    key=SEARCH_KEY,
                    label_visibility="collapsed",
                    on_change=_jump,
                    args=(targets,),
                )
        with state:
            render(status_html(status["latest_fy"], status["retrieved_on"], status["filings"]))
        with help_col:
            target = next((p for p in ("About", "Metrics guide") if p in pages), None)
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
