"""Extraction from BRSR XBRL: structure, unit decisions, overrides, hints and consistency notes.

The fixture uses the real element names and layout with FAKE values; expected numbers are
written out by hand."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from gauge.config import ConfigError, load_indicators, load_study
from gauge.ingest.xbrl_extract import extract_filing, resolve_unit
from gauge.ingest.xbrl_map import Override, load_overrides, load_xbrl_mapping
from xbrl_fixture import FAKE_ISIN, build_instance

D = Decimal
S1 = "TotalScope1Emissions"
REV = "RevenueFromOperations"


@pytest.fixture(scope="module")
def mapping():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    cfg = load_study("config/study.yaml", root=root)
    return load_xbrl_mapping(cfg, load_indicators(cfg))


def extract(tmp_path, mapping, overrides=(), cin_to_isin=None, **kw):
    return extract_filing(
        build_instance(tmp_path / "f.xml", **kw), mapping, list(overrides), cin_to_isin
    )


def override(unit, *codes, fy=("FY2025-26",), isin=FAKE_ISIN):
    return Override(
        isin=isin,
        fy=list(fy),
        indicators=list(codes),
        unit=unit,
        evidence="verified against page 1 of the filing PDF",
    )


# ---- structure ---------------------------------------------------------------------------------
def test_extracts_current_and_previous_year(tmp_path, mapping):
    f = extract(tmp_path, mapping)
    assert [(y.fy, y.current) for y in f.years] == [("FY2024-25", False), ("FY2025-26", True)]
    assert all(y.complete and len(y.values) == 9 for y in f.years)
    cur = f.years[1].values
    assert cur["revenue_from_operations"].value == D("500000000000")
    assert (cur["energy_total"].value, cur["energy_total"].unit) == (D("1000000"), "GJ")
    assert (cur["water_consumption"].unit, cur["waste_recovered"].unit) == ("kL", "t")
    assert f.years[0].values["scope1_emissions"].value == D("4800000")


def test_identity_boundary_and_assurance(tmp_path, mapping):
    f = extract(tmp_path, mapping)
    assert (f.isin, f.name, f.boundary) == (FAKE_ISIN, "Fake Cement Limited", "standalone")
    assert f.assured is True
    assert (
        "energy: Reasonable" in f.assurance_note
        and "provider: Fake Assurers LLP" in f.assurance_note
    )
    consolidated = extract(tmp_path, mapping, boundary="Consolidated basis")
    assert consolidated.boundary == "consolidated"


def test_provenance_names_the_element_and_basis(tmp_path, mapping):
    r = extract(tmp_path, mapping).years[1].values["scope1_emissions"]
    assert (r.element, r.context_id, r.raw_label, r.basis) == (
        S1,
        "DCYMain",
        "Non-SI:tCO2e",
        "label",
    )


def test_dimensional_facts_are_never_read_as_company_level(tmp_path, mapping):
    f = extract(tmp_path, mapping)  # the fixture also has a dimensional revenue of 1
    assert f.years[1].values["revenue_from_operations"].value == D("500000000000")


def test_assurance_requires_every_group(tmp_path, mapping):
    assert extract(tmp_path, mapping, assurance=None).assured is None
    f = extract(tmp_path, mapping, assurance="Reasonable")
    assert f.assured is True
    assert extract(tmp_path, mapping, assurance="Not assured").assured is False


def test_previous_year_may_be_absent(tmp_path, mapping):
    f = extract(tmp_path, mapping, previous=None)
    assert [y.fy for y in f.years] == ["FY2025-26"]


def test_non_april_march_period_is_ignored_with_a_warning(tmp_path, mapping):
    f = extract(tmp_path, mapping, previous_period=("2024-01-01", "2025-03-31"))
    assert [y.fy for y in f.years] == ["FY2025-26"]
    assert any("non April-March" in i.message for i in f.issues)


# ---- refusals ----------------------------------------------------------------------------------
@pytest.mark.parametrize("schema", ["in-capmkt-ent-2023-01-01.xsd", None])
def test_unverified_taxonomy_is_refused(tmp_path, mapping, schema):
    f = extract(tmp_path, mapping, schema=schema)
    assert (
        f.refused
        and not f.years
        and "not one this mapping has been checked against" in f.issues[0].message
    )


def test_missing_isin_is_refused(tmp_path, mapping):
    f = extract(tmp_path, mapping, isin=None)
    assert f.refused and "cannot tell which company" in f.issues[0].message


def test_cin_joins_to_the_isin_when_the_filing_has_no_isin(tmp_path, mapping):
    """Taxonomy 2024-04-30 states a CIN and no ISIN. The join table supplies the ISIN."""
    extra = (
        '<in-capmkt:CorporateIdentityNumber contextRef="DCYMain">'
        "L00000XX0000PLC000000</in-capmkt:CorporateIdentityNumber>"
    )
    f = extract(
        tmp_path,
        mapping,
        isin=None,
        extra=extra,
        cin_to_isin={"L00000XX0000PLC000000": FAKE_ISIN},
    )
    assert f.isin == FAKE_ISIN and not f.refused and f.years


def test_unknown_cin_is_refused(tmp_path, mapping):
    extra = (
        '<in-capmkt:CorporateIdentityNumber contextRef="DCYMain">'
        "L00000XX0000PLC000000</in-capmkt:CorporateIdentityNumber>"
    )
    f = extract(tmp_path, mapping, isin=None, extra=extra, cin_to_isin={})
    assert f.refused and not f.years
    assert "not in data/reference/cin_isin.csv" in f.issues[0].message


def test_checked_2024_taxonomy_is_accepted(tmp_path, mapping):
    f = extract(tmp_path, mapping, schema="in-capmkt-ent-2024-04-30.xsd")
    assert not f.refused and [y.fy for y in f.years] == ["FY2024-25", "FY2025-26"]


def test_unknown_boundary_text_warns(tmp_path, mapping):
    f = extract(tmp_path, mapping, boundary="Group basis")
    assert f.boundary is None and any("not recognised" in i.message for i in f.issues)


# ---- unit decisions ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "unit_key, value, expected_unit",
    [("tCO2e", "5000000", "tCO2e"), ("ktCO2e", "1045", "ktCO2e")],
)
def test_unambiguous_emission_labels_are_taken_as_filed(
    tmp_path, mapping, unit_key, value, expected_unit
):
    f = extract(tmp_path, mapping, current={S1: (value, unit_key)})
    r = f.years[1].values["scope1_emissions"]
    assert (r.unit, r.basis) == (expected_unit, "label")


def test_mtco2e_label_with_a_large_value_is_tonnes(tmp_path, mapping):
    """UltraTech-style: 88,884,246 under the MtCO2e label cannot be million tonnes."""
    r = (
        extract(tmp_path, mapping, current={S1: ("88884246", "MtCO2e")})
        .years[1]
        .values["scope1_emissions"]
    )
    assert (r.unit, r.basis) == ("tCO2e", "magnitude")


def test_mtco2e_label_with_zero_is_unambiguous(tmp_path, mapping):
    r = (
        extract(tmp_path, mapping, current={S1: ("0", "MtCO2e")})
        .years[1]
        .values["scope1_emissions"]
    )
    assert (r.value, r.unit, r.basis) == (D("0"), "tCO2e", "zero")


def test_mtco2e_label_with_a_small_value_is_unresolved(tmp_path, mapping):
    """Tata Steel-style: 64 could be 64 tonnes or 64 million tonnes. No guess."""
    f = extract(tmp_path, mapping, current={S1: ("64", "MtCO2e")})
    year = f.years[1]
    assert not year.complete and "scope1_emissions" not in year.values
    assert "ambiguous (tonnes or million tonnes)" in year.unresolved["scope1_emissions"]
    assert f.years[0].complete  # the other year is unaffected


def test_override_resolves_an_ambiguous_value_and_leaves_a_note(tmp_path, mapping):
    f = extract(
        tmp_path, mapping, [override("Mn MT", "scope1_emissions")], current={S1: ("64", "MtCO2e")}
    )
    year = f.years[1]
    r = year.values["scope1_emissions"]
    assert (r.value, r.unit, r.basis) == (D("64"), "Mn MT", "override")
    assert year.complete
    assert (
        year.notes[0][0] == "xbrl_override_applied"
        and "verified against page 1" in year.notes[0][1]
    )


def test_override_is_specific_to_company_year_and_indicator(tmp_path, mapping):
    wrong_company = override("Mn MT", "scope1_emissions", isin="INE999Z99999")
    wrong_year = override("Mn MT", "scope1_emissions", fy=("FY2024-25",))
    wrong_indicator = override("Mn MT", "scope2_emissions")
    for o in (wrong_company, wrong_year, wrong_indicator):
        f = extract(tmp_path, mapping, [o], current={S1: ("64", "MtCO2e")})
        assert "scope1_emissions" in f.years[1].unresolved


def test_unknown_unit_label_is_unresolved(tmp_path, mapping):
    f = extract(tmp_path, mapping, current={"TotalWasteGenerated": ("100", "bogus")})
    assert "not in config/xbrl_mapping.yaml" in f.years[1].unresolved["waste_generated"]


def test_energy_labels_convert_exactly_later(tmp_path, mapping):
    for key, unit in (("TJ", "TJ"), ("MJ", "MJ"), ("GJ", "GJ")):
        f = extract(
            tmp_path,
            mapping,
            current={"TotalEnergyConsumedFromRenewableAndNonRenewableSources": ("5", key)},
        )
        assert f.years[1].values["energy_total"].unit == unit


# ---- revenue scale -----------------------------------------------------------------------------
def test_absolute_rupee_revenue_in_range_is_accepted(tmp_path, mapping):
    r = extract(tmp_path, mapping).years[1].values["revenue_from_operations"]
    assert (r.unit, r.basis) == ("INR", "magnitude")


@pytest.mark.parametrize("value", ["63493", "985697200", "9999999999"])
def test_small_revenue_is_unresolved(tmp_path, mapping, value):
    f = extract(tmp_path, mapping, current={REV: (value, "INR")})
    assert "not read as rupees" in f.years[1].unresolved["revenue_from_operations"]


def test_implausibly_large_revenue_is_unresolved(tmp_path, mapping):
    f = extract(tmp_path, mapping, current={REV: ("100000000000001", "INR")})
    assert "revenue_from_operations" in f.years[1].unresolved


def test_scale_hint_from_an_absolute_section_a_field(tmp_path, mapping):
    """HUL-style: revenue 63,493 while Section A TotalRevenueOfTheCompany is 657,250,000,000."""
    extra = (
        '<in-capmkt:TotalRevenueOfTheCompany contextRef="DCYMain" unitRef="U_INR">'
        "657250000000</in-capmkt:TotalRevenueOfTheCompany>"
    )
    f = extract(tmp_path, mapping, current={REV: ("63493", "INR")}, extra=extra)
    assert (
        "suggests the revenue is in INR crore" in f.years[1].unresolved["revenue_from_operations"]
    )


def test_scale_hint_million(tmp_path, mapping):
    """Nestle-style: revenue 230,715 while Turnover is 230,714,626,515 rupees."""
    extra = (
        '<in-capmkt:Turnover contextRef="DCYMain" unitRef="U_INR">230714626515</in-capmkt:Turnover>'
    )
    f = extract(tmp_path, mapping, current={REV: ("230715", "INR")}, extra=extra)
    assert "INR million" in f.years[1].unresolved["revenue_from_operations"]


def test_no_hint_without_an_absolute_anchor(tmp_path, mapping):
    f = extract(tmp_path, mapping, current={REV: ("63493", "INR")})
    assert "Hint" not in f.years[1].unresolved["revenue_from_operations"]


def test_revenue_override_in_thousands(tmp_path, mapping):
    """SAIL-style previous year: 985,697,200 thousand rupees."""
    o = override("INR thousand", "revenue_from_operations", fy=("FY2024-25",))
    f = extract(tmp_path, mapping, [o], previous={REV: ("985697200", "INR")})
    assert f.years[0].values["revenue_from_operations"].unit == "INR thousand"
    assert f.years[1].complete and f.years[0].complete


# ---- missing / malformed facts -----------------------------------------------------------------
def test_missing_element_is_unresolved_with_its_name(tmp_path, mapping):
    path = build_instance(tmp_path / "g.xml")
    pattern = (
        r'<in-capmkt:TotalWasteRecovered contextRef="DCYMain".*?</in-capmkt:TotalWasteRecovered>'
    )
    path.write_text(re.sub(pattern, "", path.read_text(encoding="utf-8")), encoding="utf-8")
    g = extract_filing(path, mapping, [])
    assert "TotalWasteRecovered not reported" in g.years[1].unresolved["waste_recovered"]
    assert g.years[0].complete  # the previous year still has it


def test_non_numeric_value_is_unresolved(tmp_path, mapping):
    f = extract(tmp_path, mapping, current={"TotalWasteGenerated": ("n/a", "t")})
    assert "no numeric value" in f.years[1].unresolved["waste_generated"]


# ---- consistency notes --------------------------------------------------------------------------
def test_consistent_intensities_raise_no_note(tmp_path, mapping):
    # energy 1,000,000 GJ / revenue 5e11 = 2e-6 per rupee exactly
    f = extract(
        tmp_path, mapping, intensities={"EnergyIntensityPerRupeeOfTurnover": ("0.000002", "GJ/INR")}
    )
    assert f.years[1].notes == []


def test_intensity_mismatch_is_noted(tmp_path, mapping):
    f = extract(
        tmp_path, mapping, intensities={"EnergyIntensityPerRupeeOfTurnover": ("0.000004", "GJ/INR")}
    )
    rules = [r for r, _ in f.years[1].notes]
    assert rules == ["xbrl_intensity_mismatch"] and "= 0.500" in f.years[1].notes[0][1]


def test_intensity_numerator_unit_differing_from_absolute_is_noted(tmp_path, mapping):
    consistent = {"WasteIntensityPerRupeeOfTurnover": ("0.0000002", "t/INR")}
    f = extract(
        tmp_path, mapping, intensities=consistent, current={"TotalWasteGenerated": ("100000", "t")}
    )
    assert f.years[1].notes == []  # same label: consistent
    # the same intensity labelled in kilolitres against a waste figure in tonnes is a unit mismatch
    g = extract(
        tmp_path, mapping, intensities={"WasteIntensityPerRupeeOfTurnover": ("0.0000002", "kl/INR")}
    )
    assert "differs from absolute unit" in g.years[1].notes[0][1]


def test_zero_intensity_carries_no_information(tmp_path, mapping):
    f = extract(
        tmp_path, mapping, intensities={"EnergyIntensityPerRupeeOfTurnover": ("0", "GJ/INR")}
    )
    assert f.years[1].notes == []


def test_scale_break_between_the_two_years(tmp_path, mapping):
    f = extract(tmp_path, mapping, previous={"TotalWasteGenerated": ("95", "t")})  # 100,000 vs 95
    assert [(r, "waste_generated" in m) for r, m in f.years[1].notes] == [
        ("xbrl_scale_break", True)
    ]


def test_ordinary_year_to_year_change_is_not_a_scale_break(tmp_path, mapping):
    assert (
        extract(tmp_path, mapping, previous={"TotalWasteGenerated": ("5000", "t")}).years[1].notes
        == []
    )


# ---- resolve_unit directly ---------------------------------------------------------------------
def test_resolve_unit_reasons(mapping):
    spec = mapping.indicators["scope1_emissions"]
    assert resolve_unit(spec, "Non-SI:MtCO2e", D("999.99"), mapping)[0] is None
    assert resolve_unit(spec, "Non-SI:MtCO2e", D("1000"), mapping)[:2] == ("tCO2e", "magnitude")
    assert resolve_unit(spec, "Non-SI:nope", D("5"), mapping)[0] is None


# ---- configuration -----------------------------------------------------------------------------
def test_repo_overrides_are_valid_and_evidenced(real_cfg):
    ind = load_indicators(real_cfg)
    overrides = load_overrides(real_cfg, ind)
    assert {(o.isin, o.unit) for o in overrides} >= {
        ("INE081A01020", "Mn MT"),
        ("INE030A01027", "INR crore"),
        ("INE239A01024", "INR million"),
        ("INE114A01011", "INR thousand"),
    }
    assert all(len(o.evidence) >= 20 for o in overrides)


def test_override_without_evidence_or_with_a_bad_unit_is_rejected(proj):
    cfg = load_study("config/study.yaml")
    ind = load_indicators(cfg)
    path = proj / "config" / "xbrl_overrides.yaml"
    head = ["overrides:", "  - isin: INE000T00001", "    fy: [FY2025-26]"]
    base = "\n".join([*head, "    indicators: [scope1_emissions]", ""])
    for body, message in (
        (base + '    unit: "Mn MT"\n    evidence: "short"\n', "evidence"),
        (
            base + '    unit: "furlongs"\n    evidence: "verified against page 1 of the PDF"\n',
            "furlongs",
        ),
        (
            base.replace("scope1_emissions", "scope9")
            + '    unit: "t"\n    evidence: "verified against page 1 of the PDF"\n',
            "unknown indicator",
        ),
    ):
        path.write_text(body, encoding="utf-8")
        with pytest.raises(ConfigError, match=message):
            load_overrides(cfg, ind)


def test_mapping_must_cover_every_indicator(proj):
    cfg = load_study("config/study.yaml")
    ind = load_indicators(cfg)
    path = proj / "config" / "xbrl_mapping.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("  waste_recovered:", "  waste_recovered_x:"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="must cover every indicator"):
        load_xbrl_mapping(cfg, ind)
