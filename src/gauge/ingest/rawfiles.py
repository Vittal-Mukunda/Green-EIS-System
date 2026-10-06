"""Identify and file downloaded BRSR PDFs (used only by `verify-sample`, to check values by eye).

A PDF is matched to a company by the company's name in the first pages of the document, and to a
fiscal year by the year labels in the same pages. Both are reported with their evidence; an
ambiguous or unmatched PDF is left where it is rather than filed under a guess.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from gauge.ingest.pool import PoolEntry

# Distinctive name fragments per NSE symbol (the AMFI names alone are too generic, e.g. "ITC Ltd").
NAME_KEYS: dict[str, tuple[str, ...]] = {
    "ULTRACEMCO": ("ultratech cement",),
    "AMBUJACEM": ("ambuja cements",),
    "SHREECEM": ("shree cement",),
    "JKCEMENT": ("j.k. cement", "jk cement"),
    "ACC": ("acc limited",),
    "JSWSTEEL": ("jsw steel",),
    "TATASTEEL": ("tata steel",),
    "JINDALSTEL": ("jindal steel",),
    "JSL": ("jindal stainless",),
    "SAIL": ("steel authority of india",),
    "TCS": ("tata consultancy services",),
    "INFY": ("infosys",),
    "HCLTECH": ("hcl technologies", "hcltech"),
    "WIPRO": ("wipro",),
    "TECHM": ("tech mahindra",),
    "HINDUNILVR": ("hindustan unilever",),
    "ITC": ("itc limited",),
    "NESTLEIND": ("nestle india", "nestlé india"),
    "BRITANNIA": ("britannia industries",),
    "GODREJCP": ("godrej consumer products",),
}

_FY = re.compile(r"(?<!\d)(20\d{2})\s?[-–/]\s?(?:20)?(\d{2})(?!\d)")


@dataclass(frozen=True)
class PdfMatch:
    entry: PoolEntry | None
    evidence: str
    fy: str | None
    ambiguous: bool = False


def detect_fy(text: str) -> str | None:
    """The fiscal year the text mentions most, as FY2025-26; None if none or a tie."""
    counts: Counter[str] = Counter()
    for a, b in _FY.findall(text):
        if int(b) == (int(a) + 1) % 100:
            counts[f"FY{a}-{b}"] += 1
    top = counts.most_common(2)
    if not top or (len(top) > 1 and top[0][1] == top[1][1]):
        return None
    return top[0][0]


def identify_pdf(text: str, pool: dict[str, PoolEntry]) -> PdfMatch:
    """Match extracted PDF text to a pool company by distinctive name fragments."""
    low = re.sub(r"\s+", " ", text.lower())
    scores: dict[str, int] = {}
    for entry in pool.values():
        hits = sum(low.count(key) for key in NAME_KEYS.get(entry.nse_symbol, ()))
        if hits:
            scores[entry.isin] = hits
    fy = detect_fy(text)
    if not scores:
        return PdfMatch(None, "no company name found", fy)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best_isin, best = ranked[0]
    if len(ranked) > 1 and ranked[1][1] * 3 > best:  # a close second: do not guess
        names = ", ".join(f"{pool[i].nse_symbol} x{n}" for i, n in ranked[:3])
        return PdfMatch(None, f"ambiguous between {names}", fy, ambiguous=True)
    return PdfMatch(pool[best_isin], f"name matched {best} times", fy)
