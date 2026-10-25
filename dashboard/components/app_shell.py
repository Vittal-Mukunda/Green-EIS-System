"""The application shell: loads the stylesheets, then draws the sidebar and the top bar around
whichever page is selected."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import streamlit as st

from .sidebar import nav_css, render_sidebar
from .topbar import render_topbar

STYLES = Path(__file__).resolve().parents[1] / "styles"
SHEETS = ("theme.css", "layout.css", "components.css")


def _stylesheet() -> str:
    """The three stylesheets as one string. They are small, so they are read on every run: an edit to a
    stylesheet shows up on the next rerun without restarting the server."""
    return "\n".join((STYLES / name).read_text(encoding="utf-8") for name in SHEETS)


def inject_styles(pages: list[str]) -> None:
    """The design system: tokens, shell and component styles, plus the per-page navigation rules."""
    st.html(f"<style>\n{_stylesheet()}\n{nav_css(pages)}\n</style>")


def render_shell(
    pages: list[str],
    unit: dict,
    status_text: str,
    status_tone: str = "",
    notice: str | None = None,
    extra: Callable[[], None] | None = None,
) -> str:
    """Draw the chrome and return the selected page."""
    page = render_sidebar(pages, unit, notice, extra)
    render_topbar(pages, status_text, status_tone)
    return page
