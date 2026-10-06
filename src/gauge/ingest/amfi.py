"""Parser for AMFI's half-yearly "Average Market Capitalization of listed companies" PDF.

The PDF is a table: Sr. No., company name, ISIN, BSE symbol, BSE average market cap, NSE symbol,
NSE average, MSEI symbol and average, average of all exchanges (INR crore, Indian digit grouping)
and the SEBI category. Text extraction sometimes glues the ISIN to the company name or to the next
symbol (`LIMITEDINE00M201021`), so the ISIN is located by its shape, not by surrounding spaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

CATEGORIES = ("Large Cap", "Mid Cap", "Small Cap")
_ROW = re.compile(r"^(\d+)\s+(.*?)\s*(INE[A-Z0-9]{6}\d{3})\s*(.*)$")
_NUMBER = re.compile(r"^\d[\d,]*\.\d+$")


@dataclass(frozen=True)
class AmfiRow:
    rank: int
    name: str
    isin: str
    symbols: tuple[str, ...]  # non-numeric tokens: exchange symbols, in the order printed
    avg_mcap_cr: Decimal  # average of all exchanges, INR crore
    category: str


def parse_amfi_text(text: str) -> list[AmfiRow]:
    """Parse extracted PDF text into rows. Lines that are not data rows are ignored; a data row
    whose category or numbers cannot be read raises, so a layout change is noticed, not dropped."""
    rows: list[AmfiRow] = []
    for line in text.split("\n"):
        match = _ROW.match(line.strip())
        if not match:
            continue
        rank, name, isin, rest = int(match[1]), match[2].strip(), match[3], match[4].strip()
        category = next((c for c in CATEGORIES if rest.endswith(c)), None)
        if category is None:
            raise ValueError(f"AMFI row {rank} has no category: {line!r}")
        tokens = rest[: -len(category)].split()
        numbers = [t for t in tokens if _NUMBER.match(t)]
        if not numbers:
            raise ValueError(f"AMFI row {rank} has no market cap: {line!r}")
        symbols = tuple(t for t in tokens if not _NUMBER.match(t))
        rows.append(
            AmfiRow(rank, name, isin, symbols, Decimal(numbers[-1].replace(",", "")), category)
        )
    return rows


def read_amfi_pdf(path: Path) -> list[AmfiRow]:
    """Extract and parse an AMFI PDF (needs pypdf, a dev dependency)."""
    from pypdf import PdfReader

    text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    return parse_amfi_text(text)


def find_by_symbol(rows: list[AmfiRow], symbol: str) -> AmfiRow:
    """The row whose printed symbols include `symbol`; raises if none or several match."""
    hits = [r for r in rows if symbol in r.symbols]
    if len(hits) != 1:
        raise LookupError(f"symbol {symbol!r} matches {len(hits)} AMFI rows")
    return hits[0]
