"""AMFI market-cap table parser. Sample lines have the shapes seen in the real PDF (June 2025)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from gauge.ingest.amfi import find_by_symbol, parse_amfi_text, read_amfi_pdf

TEXT = """Sr. No. Company name ISIN BSE Symbol
 BSE 6 month
Avg Total
1 Reliance Industries Ltd INE002A01018 RELIANCE 17,78,085.84   RELIANCE 17,78,158.87   17,78,122.36   Large Cap
3 Tata Consultancy Services Ltd. INE467B01029 TCS 13,24,318.28   TCS 13,24,366.81   13,24,342.55   Large Cap
434 Cello World Limited INE0LMW01024CELLO 13,320.57        CELLO 13,317.44        13,319.00        Small Cap
632 STERLING AND WILSON RENEWABLE ENERGY LIMITEDINE00M201021 SWSOLAR 7,077.49          SWSOLAR 7,076.95          7,077.22          Small Cap
1243 Khazanchi Jewellers Limited INE0OWC01011KHAZANCHI 1,430.99          1,430.99          Small Cap
250 Some Mid Co Ltd INE111A01011 543210 100.00 SOMEMID 100.00 SOMEMID 100.00 100.00 Mid Cap
page 7 of 46
"""


def test_parses_ordinary_and_glued_rows():
    rows = {r.rank: r for r in parse_amfi_text(TEXT)}
    assert sorted(rows) == [1, 3, 250, 434, 632, 1243]
    tcs = rows[3]
    assert (tcs.name, tcs.isin, tcs.category) == (
        "Tata Consultancy Services Ltd.",
        "INE467B01029",
        "Large Cap",
    )
    assert tcs.avg_mcap_cr == Decimal("1324342.55")  # Indian digit grouping, last column
    assert tcs.symbols == ("TCS", "TCS")


def test_isin_glued_to_the_name_or_to_the_symbol():
    rows = {r.rank: r for r in parse_amfi_text(TEXT)}
    assert rows[434].isin == "INE0LMW01024" and rows[434].symbols == ("CELLO", "CELLO")
    assert rows[632].name == "STERLING AND WILSON RENEWABLE ENERGY LIMITED"
    assert rows[632].isin == "INE00M201021"
    assert rows[1243].isin == "INE0OWC01011" and rows[1243].symbols == (
        "KHAZANCHI",
    )  # no NSE column


def test_numeric_bse_scrip_codes_are_symbols_not_market_caps():
    row = next(r for r in parse_amfi_text(TEXT) if r.rank == 250)
    assert row.avg_mcap_cr == Decimal("100.00") and "543210" in row.symbols


def test_non_data_lines_are_ignored():
    assert parse_amfi_text("Sr. No. Company name ISIN\npage 1\n\n") == []


def test_words_that_look_like_isins_do_not_split_a_name():
    line = "7 ENGINEERING INFRASTRUCTURE LTD INE222B01022 ENGINFRA 50.00 ENGINFRA 50.00 50.00 Small Cap"
    (row,) = parse_amfi_text(line)
    assert row.name == "ENGINEERING INFRASTRUCTURE LTD" and row.isin == "INE222B01022"


def test_unreadable_data_rows_raise_instead_of_vanishing():
    with pytest.raises(ValueError, match="no category"):
        parse_amfi_text("9 Bad Co Ltd INE333C01033 BAD 1.00 BAD 1.00 1.00 Tiny Cap")
    with pytest.raises(ValueError, match="no market cap"):
        parse_amfi_text("9 Bad Co Ltd INE333C01033 BAD Small Cap")


def test_find_by_symbol():
    rows = parse_amfi_text(TEXT)
    assert find_by_symbol(rows, "TCS").rank == 3
    with pytest.raises(LookupError, match="0 AMFI rows"):
        find_by_symbol(rows, "NOPE")
    dup = parse_amfi_text(TEXT + "2 Twin Ltd INE444D01044 TCS 5.00 TCS 5.00 5.00 Small Cap")
    with pytest.raises(LookupError, match="2 AMFI rows"):
        find_by_symbol(dup, "TCS")


def test_real_pdf_if_present(repo_root):
    """The downloaded file (gitignored) parses completely and matches SEBI's category sizes."""
    pdf = Path(repo_root) / "data" / "raw" / "reference" / "amfi_avg_mcap_2025-06-30.pdf"
    if not pdf.is_file():
        pytest.skip("AMFI PDF not downloaded in this checkout")
    rows = read_amfi_pdf(pdf)
    assert len(rows) == 5158
    cats = [r.category for r in rows]
    assert (cats.count("Large Cap"), cats.count("Mid Cap")) == (100, 150)
    caps = [r.avg_mcap_cr for r in sorted(rows, key=lambda r: r.rank)]
    assert caps == sorted(caps, reverse=True)
    assert find_by_symbol(rows, "ULTRACEMCO").rank == 19
