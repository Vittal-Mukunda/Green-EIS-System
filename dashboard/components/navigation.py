"""Moving between pages. A page is chosen through the sidebar radio, whose state lives in
`st.session_state["view"]`; these callbacks set it (and what to focus) before the next run."""

from __future__ import annotations

import streamlit as st


def open_page(view: str) -> None:
    """Callback for a button: go to another page."""
    st.session_state["view"] = view


def open_company(code: str, view: str = "Companies") -> None:
    st.session_state["view"] = view
    st.session_state["company_focus"] = code


def open_sector(name: str) -> None:
    st.session_state["view"] = "Sectors"
    st.session_state["sector_focus"] = name


def open_filing(code: str, fy: str) -> None:
    """Go to Sources and filings with a company and year preselected."""
    st.session_state["view"] = "Sources and filings"
    st.session_state["filing_focus"] = (code, fy)


def open_verification(code: str, fy: str, indicator: str | None = None) -> None:
    """Go to Data verification with a company, year and (optionally) a value preselected."""
    st.session_state["view"] = "Data verification"
    st.session_state["verify_focus"] = (code, fy, indicator)


def link_button(label: str, view: str, key: str, pages: list[str], **kwargs) -> None:
    """A text-style button that opens `view`, shown only when that page is offered. Keys start with
    `link_` so the stylesheet draws them as links."""
    if view in pages:
        st.button(label, key=f"link_{key}", on_click=open_page, args=(view,), **kwargs)
