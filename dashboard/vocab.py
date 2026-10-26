"""Page names, in sidebar order. The groups they sit in are in `components/page_header.GROUPS`.

The user-facing navigation is Study, one analysis page per research gap, Overall Findings, References.
The analysis pages are generated from `greeneis.gaps.GAPS`, so adding or renaming a gap changes the
sidebar, the Study page and the findings table together.

The unit tool (Data entry, Summary, Hotspots, What-if, Report) and the earlier reference pages are not in
this navigation. Their code is kept and runs from `dashboard/legacy_app.py`; see `LEGACY_PAGES`.
"""

from __future__ import annotations

import re
from typing import Final

from greeneis import gaps

STUDY_PAGES: Final = ("Study",)
ANALYSIS_PAGES: Final = tuple(g.nav_label for g in gaps.GAPS)
FINDINGS_PAGES: Final = ("Overall Findings",)
REFERENCE_PAGES: Final = ("References",)
PAGES: Final = STUDY_PAGES + ANALYSIS_PAGES + FINDINGS_PAGES + REFERENCE_PAGES

# Pages that are not in the navigation but still run (dashboard/legacy_app.py).
LEGACY_UNIT_PAGES: Final = ("Data entry", "Summary", "Hotspots", "What-if", "Report")
LEGACY_REFERENCE_PAGES: Final = ("Study results", "Factors and method", "About")
LEGACY_PAGES: Final = LEGACY_UNIT_PAGES + LEGACY_REFERENCE_PAGES

# One line under each page name: what the page is for.
PAGE_NOTES: Final = {
    "Study": "Why the project exists, and the seven research gaps",
    **{g.nav_label: g.question for g in gaps.GAPS},
    "Overall Findings": "What was found, what is unresolved, and the evidence behind each",
    "References": "Every source cited, and how far each was checked",
    "Data entry": "Enter a month of energy, fuel and cost data",
    "Summary": "Total emissions and how far to believe them",
    "Hotspots": "Where emissions and cost come from",
    "What-if": "Try a change before spending money",
    "Report": "A one-page summary to share",
    "Study results": "Does the trust score predict real error?",
    "Factors and method": "Every factor, its source, and the formulas",
    "About": "What this system is, and where it stops",
}


def slug(text: str) -> str:
    """A page name as it appears in a web address: 'What-if' becomes 'what-if'."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def gap_page(number: int) -> str:
    """The navigation label of the analysis page for gap `number`."""
    return gaps.get(number).nav_label
