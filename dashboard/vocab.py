"""Page names, in sidebar order. The groups they sit in are in `components/page_header.GROUPS`."""

from __future__ import annotations

import re
from typing import Final

OVERVIEW_PAGES: Final = ("Home", "Research gaps", "National picture", "Trust in numbers")
UNIT_PAGES: Final = ("Data entry", "Summary", "Hotspots", "What-if", "Report")
STUDY_PAGES: Final = ("Study results",)
REFERENCE_PAGES: Final = ("Data and sources", "Factors and method", "About")
PAGES: Final = OVERVIEW_PAGES + UNIT_PAGES + STUDY_PAGES + REFERENCE_PAGES

# One line under each page name in the sidebar: what the page is for.
PAGE_NOTES: Final = {
    "Home": "What was found on real factory data",
    "Research gaps": "The seven gaps and how far each is settled",
    "National picture": "Where published estimates disagree",
    "Trust in numbers": "How far to believe a Measured, Estimated or Default number",
    "Data and sources": "Every source, and what is not shown",
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
