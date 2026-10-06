"""Matching downloaded BRSR PDFs to companies and fiscal years."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from gauge.ingest.pool import PoolEntry, load_pool
from gauge.ingest.rawfiles import NAME_KEYS, detect_fy, identify_pdf

ROOT = Path(__file__).resolve().parents[1]


def entry(symbol, isin, name) -> PoolEntry:
    return PoolEntry(isin, "Cement", "primary", symbol, name, 1, "")


POOL = {
    "INE1": entry("ULTRACEMCO", "INE1", "UltraTech Cement Ltd"),
    "INE2": entry("AMBUJACEM", "INE2", "Ambuja Cements Ltd."),
    "INE3": entry("ITC", "INE3", "ITC Ltd"),
}


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "Business Responsibility Report FY 2025-26. Year 2025-26 data; 2024-25 comparatives",
            "FY2025-26",
        ),
        ("financial year 2025-2026 and again 2025-2026, previous 2024-2025", "FY2025-26"),
        ("2025-26 vs 2024-25", None),  # a tie is not a decision
        ("figures for 2025-27 and 2025-27", None),  # not consecutive years
        ("no year here", None),
        ("page 2012-13 flagged once, and 2025-26 twice 2025-26", "FY2025-26"),
    ],
)
def test_detect_fy(text, expected):
    assert detect_fy(text) == expected


def test_identifies_the_company_by_name_with_evidence():
    text = "UltraTech Cement Limited BRSR. UltraTech Cement Limited, Mumbai. FY 2025-26 FY 2025-26"
    m = identify_pdf(text, POOL)
    assert (
        m.entry.nse_symbol == "ULTRACEMCO"
        and m.fy == "FY2025-26"
        and "matched 2 times" in m.evidence
    )


def test_name_matching_ignores_case_and_line_breaks():
    m = identify_pdf("AMBUJA\n  CEMENTS LIMITED 2025-26 2025-26", POOL)
    assert m.entry is not None and m.entry.nse_symbol == "AMBUJACEM"


def test_close_second_is_not_guessed():
    text = "ultratech cement ultratech cement ambuja cements ambuja cements ambuja cements"
    m = identify_pdf(text, POOL)
    assert m.entry is None and m.ambiguous and "ULTRACEMCO" in m.evidence


def test_a_clear_majority_wins_over_a_passing_mention():
    text = "Ambuja Cements " * 9 + "mentions UltraTech Cement once"
    assert identify_pdf(text, POOL).entry.nse_symbol == "AMBUJACEM"


def test_unknown_company_is_left_alone():
    m = identify_pdf("Some Other Company Limited 2025-26 2025-26", POOL)
    assert m.entry is None and not m.ambiguous and "no company name" in m.evidence


def test_every_primary_company_has_a_name_key():
    pool = load_pool(ROOT)
    primaries = {e.nse_symbol for e in pool.values() if e.pool == "primary"}
    assert primaries <= set(NAME_KEYS), primaries - set(NAME_KEYS)


def test_name_keys_are_distinct_across_companies():
    keys = [k for ks in NAME_KEYS.values() for k in ks]
    assert len(keys) == len(set(keys))
    assert not any(a != b and a in b for a in keys for b in keys)  # no key is inside another


def test_pdf_manifest_is_consistent_with_the_filed_pdfs():
    manifest = ROOT / "data" / "reference" / "pdf_manifest.csv"
    rows = list(csv.DictReader(manifest.open(encoding="utf-8", newline="")))
    assert len(rows) == len({r["stored_name"] for r in rows}) == len({r["sha256"] for r in rows})
    assert all(r["stored_name"] == f"{r['nse_symbol']}_{r['fy']}.pdf" for r in rows)
    pool = load_pool(ROOT)
    assert all(r["isin"] in pool and pool[r["isin"]].nse_symbol == r["nse_symbol"] for r in rows)
    folder = ROOT / "data" / "raw" / "pdf"
    if not folder.is_dir():
        pytest.skip("PDFs are gitignored and absent in this checkout")
    for r in rows:
        data = (folder / r["stored_name"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == r["sha256"] and len(data) == int(r["bytes"])
