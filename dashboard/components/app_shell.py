"""The application shell: loads the stylesheets, then draws the sidebar and the top bar around
whichever page is selected."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from .people import People
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


def render_shell(pages: list[str], directory, pilot: dict, status: dict, notice: str | None):
    """Draw the chrome and return (selected page, show real company names, People)."""
    page, real_names = render_sidebar(pages, pilot, notice)
    people = People(directory, real_names)
    render_topbar(pages, people, people.sectors(), status)
    return page, real_names, people
