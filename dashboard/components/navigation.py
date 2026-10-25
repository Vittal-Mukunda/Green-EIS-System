"""Moving between pages. A page is chosen through the sidebar radio, whose state lives in
`st.session_state["view"]`; these callbacks set it before the next run."""

from __future__ import annotations

import streamlit as st


def open_page(view: str) -> None:
    """Callback for a button: go to another page."""
    st.session_state["view"] = view


def link_button(label: str, view: str, key: str, pages: list[str], **kwargs) -> None:
    """A text-style button that opens `view`, shown only when that page is offered. Keys start with
    `link_` so the stylesheet draws them as links."""
    if view in pages:
        st.button(label, key=f"link_{key}", on_click=open_page, args=(view,), **kwargs)
