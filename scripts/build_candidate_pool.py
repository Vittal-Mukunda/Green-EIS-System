"""Regenerate data/reference/candidate_pool.csv from the downloaded AMFI PDF.

    python scripts/build_candidate_pool.py [path/to/amfi.pdf]

Ranks, names, ISINs and market caps come from the AMFI file. The SECTOR ASSIGNMENT below is the
project author's judgement from company names, not a data source, and notes marked "(unverified)"
are recollections to be checked (docs/VERIFY.md V-22). Edit PICKS, not the CSV.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from gauge.ingest.amfi import find_by_symbol, read_amfi_pdf

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF = ROOT / "data" / "raw" / "reference" / "amfi_avg_mcap_2025-06-30.pdf"
OUT = ROOT / "data" / "reference" / "candidate_pool.csv"

# (sector, pool, NSE symbol, note). primary = the largest five by AMFI rank among companies judged to
# belong to the sector; spare = next in line if a primary fails the completeness rule.
PICKS = [
    ("Cement", "primary", "ULTRACEMCO", ""),
    ("Cement", "primary", "AMBUJACEM", ""),
    ("Cement", "primary", "SHREECEM", ""),
    ("Cement", "primary", "JKCEMENT", ""),
    ("Cement", "primary", "ACC", "same group as Ambuja; I recall merger plans, so check each year's filing and boundary (unverified)"),
    ("Cement", "spare", "DALBHARAT", ""),
    ("Cement", "spare", "RAMCOCEM", ""),
    ("Iron & Steel", "primary", "JSWSTEEL", ""),
    ("Iron & Steel", "primary", "TATASTEEL", ""),
    ("Iron & Steel", "primary", "JINDALSTEL", ""),
    ("Iron & Steel", "primary", "JSL", "stainless steel"),
    ("Iron & Steel", "primary", "SAIL", ""),
    ("Iron & Steel", "spare", "APLAPOLLO", "steel tubes (downstream of steel-making)"),
    ("Iron & Steel", "spare", "SHYAMMETL", ""),
    ("Iron & Steel", "not_in_pool", "LLOYDSME", "mainly iron-ore mining and sponge iron: doubtful Iron & Steel fit"),
    ("IT Services", "primary", "TCS", ""),
    ("IT Services", "primary", "INFY", ""),
    ("IT Services", "primary", "HCLTECH", ""),
    ("IT Services", "primary", "WIPRO", ""),
    ("IT Services", "primary", "TECHM", ""),
    ("IT Services", "spare", "LTIM", "formed by a merger in Nov 2022, so FY2022-23 is not like-for-like (unverified)"),
    ("IT Services", "spare", "PERSISTENT", ""),
    ("IT Services", "spare", "COFORGE", ""),
    ("IT Services", "not_in_pool", "HEXT", "listed in Feb 2025, so no FY2022-23 BRSR expected (unverified)"),
    ("IT Services", "not_in_pool", "OFSS", "banking software products rather than IT services: doubtful fit"),
    ("FMCG", "primary", "HINDUNILVR", ""),
    ("FMCG", "primary", "ITC", "diversified (FMCG, hotels, agri, paper): the consolidated BRSR mixes businesses; sector fit is a judgement call"),
    ("FMCG", "primary", "NESTLEIND", "I recall a change of financial-year end; check the three filings cover April-March years (unverified)"),
    ("FMCG", "primary", "BRITANNIA", ""),
    ("FMCG", "primary", "GODREJCP", ""),
    ("FMCG", "spare", "TATACONSUM", ""),
    ("FMCG", "spare", "DABUR", ""),
    ("FMCG", "spare", "MARICO", ""),
    ("FMCG", "not_in_pool", "VBL", "beverage bottler: doubtful FMCG fit"),
    ("FMCG", "not_in_pool", "UNITDSPR", "alcoholic beverages: doubtful FMCG fit"),
]  # fmt: skip

COLUMNS = ["sector", "pool", "amfi_rank", "company_name", "nse_symbol", "isin", "avg_mcap_cr",
           "amfi_category", "note"]  # fmt: skip


def main(pdf: Path) -> None:
    rows = read_amfi_pdf(pdf)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for sector, pool, symbol, note in PICKS:
            r = find_by_symbol(rows, symbol)
            writer.writerow({
                "sector": sector, "pool": pool, "amfi_rank": r.rank, "company_name": r.name,
                "nse_symbol": symbol, "isin": r.isin, "avg_mcap_cr": f"{r.avg_mcap_cr:.2f}",
                "amfi_category": r.category, "note": note,
            })  # fmt: skip
    print(f"parsed {len(rows)} AMFI rows; wrote {OUT.relative_to(ROOT)} ({len(PICKS)} companies)")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF)
