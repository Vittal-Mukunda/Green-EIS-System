"""Empty and error states: say what is missing and what to do, never a blank area."""

from __future__ import annotations

from .icons import icon
from .markup import esc, render


def empty_state_html(title: str, text: str = "", glyph: str = "inbox") -> str:
    return (
        f'<div class="eis-empty" role="status">{icon(glyph)}<b>{esc(title)}</b>'
        f"{'<span>' + esc(text) + '</span>' if text else ''}</div>"
    )


def empty_state(title: str, text: str = "", glyph: str = "inbox") -> None:
    render(empty_state_html(title, text, glyph))
