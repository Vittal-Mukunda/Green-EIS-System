"""The References page: every source the project cites, from the one registry in `greeneis.references`.

The Study and analysis pages cite by key, so a title or link is written once. Each entry shows how far
it was checked and which research gaps cite it. Categories with nothing in them (SDG documents, company
reports) are named, not padded.
"""

from __future__ import annotations

from collections import Counter
from importlib import metadata

import streamlit as st
from components.alerts import callout
from components.data_table import Column, table_html
from components.markup import render, section
from components.page_header import page_header
from components.research import reference_html

from greeneis import gaps, references


def used_by(key: str) -> list[int]:
    return [g.number for g in gaps.GAPS if any(s.ref == key for s in g.sources)]


def _installed(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "not installed"


def bibliography() -> None:
    page_header(
        "References",
        "Every source cited on the Study, analysis and Overall Findings pages, in one citation style, "
        "with how far each was checked.",
        read="'Checked' is the level of verification, from read in the original down to unverified. An "
        "unverified entry is listed because the project uses it, not because it is confirmed.",
        page="References",
    )
    counts = Counter(r.verification for r in references.REFERENCES)
    render(
        table_html(
            [Column("How far checked"), Column("Sources", numeric=True)],
            [[references.VERIFICATION[k], str(counts.get(k, 0))] for k in references.VERIFICATION],
        )
    )
    callout(
        "warn",
        "Several sources are abstract-only or unverified.",
        "The project reference document retrieved many sources as abstracts or extracts only. Read the "
        "original before quoting in the paper. Items to check are in docs/VERIFY.md (V-13, V-14, V-38, V-39).",
    )
    for category, label in references.CATEGORIES.items():
        entries = [r for r in references.REFERENCES if r.category == category]
        if not entries:
            continue
        section(label, f"{len(entries)} entries")
        for ref in sorted(entries, key=lambda r: (r.authors or r.title).lower()):
            cited = used_by(ref.key)
            render(reference_html(ref))
            if cited:
                st.caption("Cited on: " + ", ".join(f"Gap {n}" for n in cited))
        if category == "software":
            st.caption(
                "Installed versions: "
                + ", ".join(f"{p} {_installed(p)}" for p in references.SOFTWARE_PACKAGES.values())
            )
    section("Not used in this project")
    st.markdown(
        "- **Official SDG documents.** The project does not map its results to SDG targets, so none are cited.\n"
        "- **Company annual reports and BRSR documents.** No company or BRSR data are used: the unit of "
        "analysis is an anonymous ASI factory return. An earlier project that used such filings was "
        "discarded and nothing from it is used here."
    )
