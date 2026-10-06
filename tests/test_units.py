"""Unit and fiscal-year handling. Expected values are worked out by hand."""

from __future__ import annotations

from decimal import Decimal

import pytest

from gauge.standardize.fiscal import FiscalYearError, normalize_fy, shift_fy, start_year
from gauge.standardize.units import (
    UnitError,
    accepted_units,
    factor_to_canonical,
    to_canonical,
    unit_key,
)

D = Decimal


@pytest.mark.parametrize(
    "value, unit, canonical, expected",
    [
        # currency -> INR_crore (1 crore = 10^7 INR, 1 lakh = 10^5 INR)
        ("5", "INR crore", "INR_crore", "5"),
        ("250", "INR lakh", "INR_crore", "2.5"),
        ("12500000", "INR", "INR_crore", "1.25"),
        ("2", "INR million", "INR_crore", "0.2"),
        ("3", "INR billion", "INR_crore", "300"),
        ("7", "₹ crore", "INR_crore", "7"),
        # energy -> GJ (1 kWh = 3.6 MJ)
        ("2", "MWh", "GJ", "7.2"),
        ("1", "TJ", "GJ", "1000"),
        ("5000000000", "J", "GJ", "5"),
        ("1", "GWh", "GJ", "3600"),
        ("100", "kWh", "GJ", "0.36"),
        ("4", "MJ", "GJ", "0.004"),
        # volume -> kL (SEBI: "Mn Lt or KL")
        ("3", "Mn Lt", "kL", "3000"),
        ("500", "L", "kL", "0.5"),
        ("7", "m3", "kL", "7"),
        # mass -> t (SEBI: "Kg / MT")
        ("2500", "kg", "t", "2.5"),
        ("3", "KT", "t", "3000"),
        ("1.5", "Mn MT", "t", "1500000"),
        ("40", "MT", "t", "40"),
        # emissions -> tCO2e (SEBI: "Mn MT / KT / MT")
        ("8", "MT", "tCO2e", "8"),
        ("2", "KT", "tCO2e", "2000"),
        ("3", "Metric tonnes of CO2 equivalent", "tCO2e", "3"),
        ("900", "kg CO2e", "tCO2e", "0.9"),
    ],
)
def test_conversions_are_exact(value, unit, canonical, expected):
    result = to_canonical(D(value), unit, canonical)
    assert result == D(expected)
    assert isinstance(result, Decimal)


def test_unit_key_ignores_case_spacing_punctuation():
    assert unit_key("Mn Lt") == unit_key("mn_lt") == unit_key("MN-LT") == "mnlt"
    assert unit_key("tCO₂e") == "tco2e"
    assert unit_key("₹ crore") == "inrcrore"


def test_canonical_units_convert_by_one():
    for canonical in ("INR_crore", "GJ", "tCO2e", "kL", "t"):
        assert factor_to_canonical(canonical, canonical) == 1


@pytest.mark.parametrize(
    "unit, canonical",
    [
        ("ton", "t"),  # short vs long ton
        ("tons", "t"),
        ("ml", "kL"),  # millilitre vs megalitre
        ("MLD", "kL"),  # a rate
        ("MtCO2e", "tCO2e"),  # megatonne (international) vs metric tonne (SEBI notation)
        ("MT CO2e", "tCO2e"),
        ("kcal", "GJ"),  # calorie definitions differ
        ("MMBTU", "GJ"),
    ],
)
def test_ambiguous_units_are_rejected(unit, canonical):
    with pytest.raises(UnitError, match="ambiguous"):
        factor_to_canonical(unit, canonical)


def test_free_text_unit_from_real_filings_is_rejected():
    """The XBRL International analysis found free-text emission units such as 'CO2 in MT'."""
    with pytest.raises(UnitError, match="not a emissions unit I can convert"):
        factor_to_canonical("CO2 in MT", "tCO2e")


def test_wrong_dimension_is_named():
    with pytest.raises(UnitError, match="looks like a energy unit"):
        factor_to_canonical("GJ", "kL")
    with pytest.raises(UnitError, match="empty"):
        factor_to_canonical("  ", "kL")


def test_unknown_canonical_unit():
    with pytest.raises(UnitError, match="no unit table"):
        factor_to_canonical("kL", "furlong")


def test_accepted_units_lists_examples():
    assert "kl" in accepted_units("kL") and len(accepted_units("GJ")) <= 12


# ---- fiscal years -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    [
        "FY2024-25",
        "2024-25",
        "FY 2024-25",
        "fy2024-25",
        "FY2024-2025",
        "2024-2025",
        "FY24-25",
        "FY2024–25",
        " FY2024-25 ",
    ],
)
def test_fiscal_year_spellings_normalize(raw):
    assert normalize_fy(raw) == "FY2024-25"


@pytest.mark.parametrize(
    "raw",
    ["FY25", "2025", "FY2024", "FY2024-26", "FY2024-2026", "FY24-2025", "FY2023-25", "", "latest"],
)
def test_ambiguous_or_wrong_fiscal_years_rejected(raw):
    with pytest.raises(FiscalYearError):
        normalize_fy(raw)


def test_century_rollover_label():
    assert normalize_fy("2099-00") == "FY2099-00"
    assert shift_fy("FY2024-25", 1) == "FY2025-26"
    assert shift_fy("FY2024-25", -2) == "FY2022-23"
    assert shift_fy("FY2099-00", 1) == "FY2100-01"
    assert start_year("FY2022-23") == 2022
