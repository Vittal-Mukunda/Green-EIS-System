"""Small helpers every component uses: HTML escaping and rendering.

Components return HTML strings and `render` puts them on the page with `st.html`. Text from the
database (company names, file names) always goes through `esc`.
"""

from __future__ import annotations

import html as _html

import streamlit as st


def esc(value: object) -> str:
    """HTML-escape any value (None becomes an empty string)."""
    return "" if value is None else _html.escape(str(value), quote=True)


def attrs(**kw: object) -> str:
    """Render attributes, skipping empty ones: attrs(cls="a", title="t") -> ' class="a" title="t"'."""
    parts = []
    for key, value in kw.items():
        if value in (None, "", False):
            continue
        name = {"cls": "class"}.get(key, key.replace("_", "-"))
        parts.append(f'{name}="{esc(value)}"')
    return (" " + " ".join(parts)) if parts else ""


def render(markup: str) -> None:
    """Put a component on the page."""
    st.html(markup)


def section(title: str, note: str = "") -> None:
    """A section heading with an optional note at the right."""
    tail = f'<span class="eis-section-note">{esc(note)}</span>' if note else ""
    render(f'<div class="eis-section"><h3>{esc(title)}</h3>{tail}</div>')
