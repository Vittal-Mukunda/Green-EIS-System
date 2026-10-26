"""Moving between pages. A page is chosen through the sidebar radio, whose state lives in
`st.session_state["view"]`; these callbacks set it before the next run.

Streamlit keeps the scroll position when the page content changes, so a button far down one page would
open the next page part-way down. Every way of changing page therefore also asks for a scroll to the top
(`request_scroll_top`), which `scroll_to_top_if_requested` carries out once the new page has been drawn.
"""

from __future__ import annotations

import contextlib

import streamlit as st

_FLAG = "_scroll_top"
_SCRIPT = (
    "<script>setTimeout(function () {"
    "var m = document.querySelector('[data-testid=\"stMain\"]') || document.querySelector('section.main');"
    "if (m) { m.scrollTo(0, 0); }"
    "}, 60);</script>"
)


def request_scroll_top() -> None:
    """Callback: the next run should start at the top of the page."""
    st.session_state[_FLAG] = True


def scroll_to_top_if_requested() -> None:
    """Scroll to the top once, if a page change asked for it. Needs a Streamlit that can run a script
    in `st.html`; on an older one the page simply keeps its scroll position."""
    if st.session_state.pop(_FLAG, False):
        with contextlib.suppress(TypeError):
            st.html(_SCRIPT, unsafe_allow_javascript=True)


def open_page(view: str) -> None:
    """Callback for a button: go to another page."""
    st.session_state["view"] = view
    request_scroll_top()


def link_button(label: str, view: str, key: str, pages: list[str], **kwargs) -> None:
    """A text-style button that opens `view`, shown only when that page is offered. Keys start with
    `link_` so the stylesheet draws them as links."""
    if view in pages:
        st.button(label, key=f"link_{key}", on_click=open_page, args=(view,), **kwargs)


def primary_button(label: str, view: str, key: str, pages: list[str], **kwargs) -> None:
    """A prominent button that opens `view` (shown only when that page is offered)."""
    if view in pages:
        st.button(
            label,
            key=f"go_{key}",
            type="primary",
            on_click=open_page,
            args=(view,),
            **kwargs,
        )
