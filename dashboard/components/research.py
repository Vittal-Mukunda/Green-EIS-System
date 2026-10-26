"""Blocks the research pages share: a labelled answer, a gap heading, a reference entry.

Pages call these; they do not write markup. Text is escaped here unless it is passed as trusted HTML
built from escaped parts (a citation link, say).
"""

from __future__ import annotations

from greeneis import references

from .citations import verification_badge
from .markup import esc, render
from .status_badge import badge

STATUS_TONE = {
    "addressed": "ok",
    "partial": "info",
    "unresolved": "warn",
    "insufficient": "warn",
}


def status_badge(status_key: str, text: str) -> str:
    return badge(text, STATUS_TONE.get(status_key, ""))


def qa_html(question: str, answer: str, *, raw: bool = False) -> str:
    body = answer if raw else esc(answer)
    return (
        f'<div class="eis-qa"><div class="q">{esc(question)}</div><div class="a">{body}</div></div>'
    )


def qa(question: str, answer: str, *, raw: bool = False) -> None:
    render(qa_html(question, answer, raw=raw))


def gap_head_html(title: str, badges_html: str = "") -> str:
    return f'<div class="eis-gaphead"><h3>{esc(title)}</h3>{badges_html}</div>'


def gap_head(title: str, badges_html: str = "") -> None:
    render(gap_head_html(title, badges_html))


def reference_html(ref: references.Reference) -> str:
    """One bibliography entry with its anchor, how far it was checked and its note."""
    link = (
        f' <a class="eis-cite" href="{esc(ref.link)}" target="_blank" rel="noopener">{esc(ref.link)}</a>'
        if ref.link
        else ""
    )
    head = f"{esc(ref.authors)} ({esc(ref.year)})." if ref.authors and ref.year else ""
    if ref.authors and not ref.year:
        head = f"{esc(ref.authors)} (year not established)."
    if not ref.authors and ref.year:
        head = f"({esc(ref.year)})."
    body = f"{head} {esc(ref.title)}. {esc(ref.venue) + '.' if ref.venue else ''}{link}".strip()
    label = f"Reference document label {esc(ref.ref_id)}" if ref.ref_id else ""
    meta = verification_badge(ref.verification) + (
        f' <span class="eis-sub">{label}</span>' if label else ""
    )
    note = f'<div class="note">{esc(ref.note)}</div>' if ref.note else ""
    return (
        f'<div class="eis-ref" id="{esc(references.anchor(ref.key))}"><div class="cite">{body}</div>'
        f'<div class="meta">{meta}</div>{note}</div>'
    )
