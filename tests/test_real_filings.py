"""The 20 real FY2025-26 BRSR filings (data/raw/xbrl, gitignored). Skipped when they are absent.

These pin facts that were checked by hand against the filings' PDFs and Section A fields on
2026-10-02, so a change to the extractor or the mapping cannot silently change what the data say."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from gauge.config import load_indicators, load_study
from gauge.ingest.pool import load_pool
from gauge.ingest.xbrl_extract import extract_filing
from gauge.ingest.xbrl_map import load_overrides, load_xbrl_mapping

D = Decimal
ROOT = Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "data" / "raw" / "xbrl").glob("*_FY2025-26.xml"))

pytestmark = pytest.mark.skipif(
    len(FILES) < 20, reason="the 20 real filings are not in data/raw/xbrl"
)

# ISIN -> why the filing's own unit labels do not settle a value (see config/xbrl_overrides.yaml)
NEEDS_OVERRIDE = {
    "INE081A01020": "Tata Steel: Scope 1/2 labelled MtCO2e but million tonnes",
    "INE030A01027": "Hindustan Unilever: revenue in INR crore",
    "INE239A01024": "Nestle India: revenue in INR million",
    "INE114A01011": "SAIL: FY2024-25 revenue column in INR thousand",
}


@pytest.fixture(scope="module")
def setup():
    cfg = load_study("config/study.yaml", root=ROOT)
    ind = load_indicators(cfg)
    return load_xbrl_mapping(cfg, ind), load_overrides(cfg, ind), load_pool(ROOT)


@pytest.fixture(scope="module")
def filings(setup):
    mapping, overrides, _ = setup
    return {f.isin: f for f in (extract_filing(p, mapping, overrides) for p in FILES)}


def test_twenty_distinct_companies_all_in_the_primary_pool(filings, setup):
    pool = setup[2]
    assert len(filings) == 20
    assert all(pool[isin].pool == "primary" for isin in filings)
    per_sector = {}
    for isin in filings:
        per_sector[pool[isin].sector] = per_sector.get(pool[isin].sector, 0) + 1
    assert per_sector == {"Cement": 5, "Iron & Steel": 5, "IT Services": 5, "FMCG": 5}


def test_every_company_year_resolves_with_the_recorded_overrides(filings):
    for f in filings.values():
        assert not f.refused, f.issues
        assert [y.fy for y in f.years] == ["FY2024-25", "FY2025-26"]
        for y in f.years:
            assert y.complete and len(y.values) == 9, (f.name, y.fy, y.unresolved)


def test_without_overrides_exactly_the_documented_cases_are_unresolved(setup):
    mapping, _, _ = setup
    unresolved = set()
    for p in FILES:
        f = extract_filing(p, mapping, [])
        if any(not y.complete for y in f.years):
            unresolved.add(f.isin)
    assert unresolved == set(NEEDS_OVERRIDE), {
        NEEDS_OVERRIDE.get(i, i) for i in unresolved ^ set(NEEDS_OVERRIDE)
    }


def test_values_checked_against_the_filings(filings):
    def val(isin, fy, code):
        year = next(y for y in filings[isin].years if y.fy == fy)
        return year.values[code]

    ultratech = "INE481G01011"
    assert val(ultratech, "FY2025-26", "scope1_emissions").value == D("88884246")
    assert val(ultratech, "FY2025-26", "scope1_emissions").unit == "tCO2e"  # MtCO2e label, tonnes
    assert val(ultratech, "FY2025-26", "revenue_from_operations").value == D("885115300000")
    tata = "INE081A01020"  # BRSR PDF p.48: "Million tonnes CO2e 64 61"
    tata_s1 = val(tata, "FY2025-26", "scope1_emissions")
    assert (tata_s1.value, tata_s1.unit) == (D("64"), "Mn MT")
    assert val(tata, "FY2024-25", "scope1_emissions").value == D("61")
    assert val("INE030A01027", "FY2025-26", "revenue_from_operations").unit == "INR crore"
    assert val("INE114A01011", "FY2024-25", "revenue_from_operations").unit == "INR thousand"
    # JSPL renewable energy: BRSR PDF p.36 "0.4866" and "0.0112" PJ, i.e. 486.6 and 11.2 TJ
    jspl = "INE749A01030"
    assert val(jspl, "FY2025-26", "energy_renewable").unit == "TJ"
    assert val(jspl, "FY2025-26", "energy_renewable").value == D("486.6")
    assert val(jspl, "FY2024-25", "energy_renewable").value == D("11.2")  # a real 43-fold rise


def test_boundaries_and_assurance_as_filed(filings):
    boundary = {f.isin: f.boundary for f in filings.values()}
    assert boundary["INE481G01011"] == "consolidated"  # UltraTech
    assert boundary["INE081A01020"] == "standalone"  # Tata Steel
    assert all(f.assured is True for f in filings.values())  # Reasonable on all four groups
    assert all("provider:" in f.assurance_note for f in filings.values())


def test_no_unexpected_consistency_notes(filings):
    """Intensity cross-checks and year-over-year scale breaks all pass on the real filings (the only
    notes are the recorded overrides)."""
    noted = {
        (f.name, y.fy, rule)
        for f in filings.values()
        for y in f.years
        for rule, _ in y.notes
        if rule != "xbrl_override_applied"
    }
    assert noted == set()
