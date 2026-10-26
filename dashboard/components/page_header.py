"""The opening of every page: breadcrumb, title, then the same scope box (what the page shows, what is
compared, how to read it)."""

from __future__ import annotations

import streamlit as st
import vocab

from .icons import icon
from .markup import esc, render

BRAND = "GreenEIS"

# The sidebar's groups; also the breadcrumb's first level.
GROUPS = {
    "Overview": vocab.OVERVIEW_PAGES,
    "Unit": vocab.UNIT_PAGES,
    "Study": vocab.STUDY_PAGES,
    "Reference": vocab.REFERENCE_PAGES,
}


def group_of(page: str) -> str:
    return next((g for g, pages in GROUPS.items() if page in pages), BRAND)


def breadcrumb_html(page: str, trail: tuple[str, ...] = ()) -> str:
    parts = [BRAND, group_of(page), *([page] if not trail else [page, *trail])]
    last = len(parts) - 1
    items = []
    for i, part in enumerate(parts):
        cls = "here" if i == last else ""
        items.append(f'<span class="{cls}">{esc(part)}</span>')
    sep = '<span class="sep">' + icon("chevron_right", "sm") + "</span>"
    return f'<nav class="eis-crumbs" aria-label="Breadcrumb">{sep.join(items)}</nav>'


def page_header(
    title: str,
    what: str,
    compared: str | None = None,
    read: str | None = None,
    page: str | None = None,
    trail: tuple[str, ...] = (),
) -> None:
    """Breadcrumb, title and scope. The scope box opens every page with what the page shows and, where it
    matters, what is being compared and how to read it."""
    page = page or title
    render(breadcrumb_html(page, trail) + f'<h1 class="eis-title">{esc(title)}</h1>')
    with st.container(key="eis-scope"):
        st.markdown(f"**What this page shows.** {what}")
        if compared:
            st.markdown(f"**What is being compared.** {compared}")
        if read:
            st.caption(f"How to read it: {read}")
