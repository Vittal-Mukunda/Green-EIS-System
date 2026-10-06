"""Unit normalization and exact conversion to the canonical units of config/indicators.yaml.

Factors are exact definitions (powers of ten, 1 kWh = 3.6 MJ), held as Decimal strings. Notation for
tonnes and litres follows SEBI's own BRSR Core annexure (July 2023): emissions "Mn MT / KT / MT",
water "Mn Lt or KL", waste "Kg / MT", energy "Joules or multiples", where MT means metric tonnes.

Units that cannot be converted without guessing are rejected, never defaulted:
  * "ton"/"tons" (short vs long ton), "ml" (millilitre vs megalitre), "MLD" (a rate),
  * "MtCO2e" / "MT CO2e" spellings that fuse the tonne unit with the gas ("mtco2e"): megatonnes in
    international usage but metric tonnes in SEBI notation,
  * calorie and BTU based energy units (several non-equivalent definitions).
The owner then restates the value in an accepted unit, checking the filing's own unit text.
"""

from __future__ import annotations

import re
from decimal import Decimal

CANONICAL_DIMENSION = {
    "INR_crore": "currency",
    "GJ": "energy",
    "tCO2e": "emissions",
    "kL": "volume",
    "t": "mass",
}

_D = Decimal

# dimension -> normalized key -> factor that converts one such unit into the canonical unit
_FACTORS: dict[str, dict[str, Decimal]] = {
    "currency": {
        **dict.fromkeys(
            (
                "inrcrore",
                "inrcrores",
                "inrcr",
                "rscrore",
                "rscrores",
                "rscr",
                "crore",
                "crores",
                "cr",
                "rupeescrore",
            ),
            _D("1"),
        ),
        **dict.fromkeys(
            (
                "inrlakh",
                "inrlakhs",
                "inrlac",
                "inrlacs",
                "rslakh",
                "rslakhs",
                "lakh",
                "lakhs",
                "lac",
                "lacs",
            ),
            _D("0.01"),
        ),
        **dict.fromkeys(
            ("inrmillion", "inrmillions", "inrmn", "rsmillion", "rsmn", "millioninr"), _D("0.1")
        ),
        **dict.fromkeys(("inrbillion", "inrbillions", "inrbn", "rsbillion", "rsbn"), _D("100")),
        **dict.fromkeys(
            ("inrthousand", "inrthousands", "inrth", "rsthousand", "rsthousands"), _D("1E-4")
        ),
        **dict.fromkeys(("inr", "rs", "rupee", "rupees"), _D("1E-7")),
    },
    "energy": {
        **dict.fromkeys(("gj", "gigajoule", "gigajoules"), _D("1")),
        **dict.fromkeys(("mj", "megajoule", "megajoules"), _D("0.001")),
        **dict.fromkeys(("tj", "terajoule", "terajoules"), _D("1000")),
        **dict.fromkeys(("pj", "petajoule", "petajoules"), _D("1000000")),
        **dict.fromkeys(("kj", "kilojoule", "kilojoules"), _D("1E-6")),
        **dict.fromkeys(("j", "joule", "joules"), _D("1E-9")),
        **dict.fromkeys(("kwh", "kilowatthour", "kilowatthours"), _D("0.0036")),
        **dict.fromkeys(("mwh", "megawatthour", "megawatthours"), _D("3.6")),
        **dict.fromkeys(("gwh", "gigawatthour", "gigawatthours"), _D("3600")),
        **dict.fromkeys(("twh", "terawatthour", "terawatthours"), _D("3600000")),
    },
    "emissions": {
        **dict.fromkeys(
            (
                "tco2e",
                "tco2eq",
                "tco2equivalent",
                "tonnesco2e",
                "tonnesco2eq",
                "tonneco2e",
                "metrictonnesco2e",
                "metrictonnesco2eq",
                "metrictonneco2e",
                "metrictonnesofco2equivalent",
                "metrictonnesofco2eq",
                "tonnesofco2e",
                "tonnesofco2equivalent",
                "t",
                "mt",
                "tonnes",
                "metrictonnes",
            ),
            _D("1"),
        ),
        **dict.fromkeys(("ktco2e", "ktco2eq", "kilotonnesco2e", "kt", "kilotonnes"), _D("1000")),
        **dict.fromkeys(
            (
                "mnmt",
                "millionmt",
                "millionmetrictonnes",
                "mnmtco2e",
                "millionmtco2e",
                "mnmtco2eq",
                "millionmetrictonnesco2e",
            ),
            _D("1000000"),
        ),
        **dict.fromkeys(("kgco2e", "kgco2eq", "kg", "kilograms"), _D("0.001")),
    },
    "volume": {
        **dict.fromkeys(
            (
                "kl",
                "kilolitre",
                "kilolitres",
                "kiloliter",
                "kiloliters",
                "m3",
                "cubicmetre",
                "cubicmetres",
                "cubicmeter",
                "cubicmeters",
            ),
            _D("1"),
        ),
        **dict.fromkeys(
            (
                "mnlt",
                "mnl",
                "millionlitres",
                "millionliters",
                "megalitre",
                "megalitres",
                "megaliter",
                "megaliters",
            ),
            _D("1000"),
        ),
        **dict.fromkeys(("l", "lt", "litre", "litres", "liter", "liters"), _D("0.001")),
    },
    "mass": {
        **dict.fromkeys(("t", "tonne", "tonnes", "metrictonne", "metrictonnes", "mt"), _D("1")),
        **dict.fromkeys(("kt", "kilotonne", "kilotonnes"), _D("1000")),
        **dict.fromkeys(("mnmt", "millionmt", "millionmetrictonnes"), _D("1000000")),
        **dict.fromkeys(("kg", "kgs", "kilogram", "kilograms"), _D("0.001")),
    },
}

_AMBIGUOUS = {
    "ton": "short or long ton",
    "tons": "short or long ton",
    "ml": "millilitre or megalitre",
    "mld": "a flow rate, not a volume",
    "mtco2e": "megatonne (international) or metric tonne (SEBI notation)",
    "mtco2eq": "megatonne (international) or metric tonne (SEBI notation)",
    "kcal": "calorie definitions differ",
    "gcal": "calorie definitions differ",
    "mmbtu": "BTU definitions differ",
    "btu": "BTU definitions differ",
}

_SEPARATORS = re.compile(r"[\s._\-/(),]+")


class UnitError(ValueError):
    """The unit is unknown, ambiguous, or of the wrong dimension for the indicator."""


def unit_key(raw: str) -> str:
    """Case-, spacing- and punctuation-insensitive key: 'Mn Lt' -> 'mnlt', 'tCO₂e' -> 'tco2e'."""
    text = raw.replace("₹", "inr").replace("₂", "2").replace("³", "3")
    return _SEPARATORS.sub("", text.casefold())


def accepted_units(canonical_unit: str) -> list[str]:
    """A few representative spellings per dimension, for error messages."""
    dim = CANONICAL_DIMENSION[canonical_unit]
    return sorted(_FACTORS[dim])[:12]


def factor_to_canonical(raw_unit: str, canonical_unit: str) -> Decimal:
    """Exact multiplier converting `raw_unit` into `canonical_unit`; raises UnitError."""
    if canonical_unit not in CANONICAL_DIMENSION:
        raise UnitError(f"no unit table for canonical unit {canonical_unit!r}")
    dim = CANONICAL_DIMENSION[canonical_unit]
    key = unit_key(raw_unit)
    if not key:
        raise UnitError("unit is empty")
    if key in _AMBIGUOUS:
        raise UnitError(
            f"unit {raw_unit!r} is ambiguous ({_AMBIGUOUS[key]}); restate it in "
            f"{canonical_unit} or another unambiguous unit"
        )
    try:
        return _FACTORS[dim][key]
    except KeyError:
        other = [d for d, table in _FACTORS.items() if key in table and d != dim]
        hint = f" (it looks like a {other[0]} unit)" if other else ""
        raise UnitError(
            f"unit {raw_unit!r} is not a {dim} unit I can convert{hint}; "
            f"canonical is {canonical_unit}"
        ) from None


def to_canonical(value: Decimal, raw_unit: str, canonical_unit: str) -> Decimal:
    return value * factor_to_canonical(raw_unit, canonical_unit)
