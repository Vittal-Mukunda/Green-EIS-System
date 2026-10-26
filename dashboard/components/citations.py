"""Citations and the source table. A citation is a link to the References page, where every entry has an
anchor; the text is the same short form everywhere because it comes from the registry."""

from __future__ import annotations

from collections.abc import Iterable

from greeneis import references
from greeneis.gaps import ROLES, Source

from .data_table import Column, Html, table_html
from .markup import esc
from .status_badge import badge

VERIFICATION_TONE = {
    "read_original": "ok",
    "metadata_verified": "info",
    "abstract_only": "warn",
    "unverified": "warn",
}


def cite(key: str) -> str:
    """'CSTEP (2018)' as a link to its entry on the References page (HTML)."""
    ref = references.get(key)
    return (
        f'<a class="eis-cite" href="?page=references#{references.anchor(key)}">{esc(ref.short)}</a>'
    )


def cites(keys: Iterable[str]) -> str:
    return "; ".join(cite(k) for k in keys)


def verification_badge(level: str) -> str:
    return badge(references.VERIFICATION[level], VERIFICATION_TONE[level])


def source_table_html(sources: Iterable[Source]) -> str:
    """Role, citation and how far it was checked, for the sources of one gap."""
    rows = []
    for s in sources:
        ref = references.get(s.ref)
        rows.append(
            [
                ROLES[s.role],
                Html(
                    f"<b>{cite(s.ref)}</b><br><span class='eis-sub'>{esc(ref.title)}"
                    f"{' . ' + esc(ref.venue) if ref.venue else ''}</span>"
                ),
                Html(verification_badge(ref.verification)),
            ]
        )
    return table_html([Column("Role"), Column("Source"), Column("Checked")], rows, first_bold=False)


def note_html(text_html: str) -> str:
    """A small grey line of trusted HTML (a sentence that carries citation links)."""
    return f'<p class="eis-sub">{text_html}</p>'


def page_link_html(label: str, slug: str) -> str:
    """A link to another page of the app by its address."""
    return f'<a class="eis-cite" href="?page={esc(slug)}">{esc(label)}</a>'


def origin_cell_html(gap) -> str:
    """The originating papers of a gap as citations, or a plain 'none verified'."""
    keys = [s.ref for s in gap.sources if s.role == "originating"]
    return "; ".join(cite(k) for k in keys) if keys else "<i>none verified</i>"


def origin_detail_html(gap) -> tuple[str, str]:
    """(originating study text, citation text) for the Study page. Honest when none is verified."""
    origin = [s for s in gap.sources if s.role == "originating"]
    if origin:
        lines = []
        for s in origin:
            r = references.get(s.ref)
            who = f"{esc(r.authors)} " if r.authors else ""
            lines.append(f"{who}({esc(r.year)}). <i>{esc(r.title)}</i>. {esc(r.venue)}")
        cites = "<br>".join(
            f"{cite(s.ref)}: <a class='eis-cite' href='{esc(references.get(s.ref).link)}' "
            f"target='_blank' rel='noopener'>{esc(references.get(s.ref).link)}</a> "
            f"{verification_badge(references.get(s.ref).verification)}"
            for s in origin
        )
        return "<br>".join(lines), cites
    others = [s for s in gap.sources if s.role in ("independent", "supporting")]
    head = (
        "<b>No originating paper could be verified for this gap.</b> The closest sources in the "
        "project's register are listed under 'Citation'; they are not claimed to establish the gap."
    )
    cites = "<br>".join(
        f"{cite(s.ref)}: {esc(references.get(s.ref).title)} "
        f"{verification_badge(references.get(s.ref).verification)}"
        for s in others
    )
    return head, cites
