"""Build small BRSR-shaped XBRL instances for tests.

Element names, namespaces, context ids and unit measures are the REAL ones read from the filings
(2026-10-02). The company, ISIN and every value are FAKE. Defaults describe a plausible cement-like
company reporting in absolute rupees, GJ, tonnes, kL.
"""

from __future__ import annotations

from pathlib import Path

FAKE_ISIN = "INE000T00001"
SCHEMA = "in-capmkt-ent-2026-02-28.xsd"

CURRENT = {
    "RevenueFromOperations": ("500000000000", "INR"),
    "TotalEnergyConsumedFromRenewableAndNonRenewableSources": ("1000000", "GJ"),
    "TotalEnergyConsumedFromRenewableSources": ("200000", "GJ"),
    "TotalScope1Emissions": ("5000000", "tCO2e"),
    "TotalScope2Emissions": ("500000", "tCO2e"),
    "TotalVolumeOfWaterWithdrawal": ("3000000", "kl"),
    "TotalVolumeOfWaterConsumption": ("2000000", "kl"),
    "TotalWasteGenerated": ("100000", "t"),
    "TotalWasteRecovered": ("90000", "t"),
}
PREVIOUS = {
    "RevenueFromOperations": ("450000000000", "INR"),
    "TotalEnergyConsumedFromRenewableAndNonRenewableSources": ("950000", "GJ"),
    "TotalEnergyConsumedFromRenewableSources": ("150000", "GJ"),
    "TotalScope1Emissions": ("4800000", "tCO2e"),
    "TotalScope2Emissions": ("520000", "tCO2e"),
    "TotalVolumeOfWaterWithdrawal": ("2900000", "kl"),
    "TotalVolumeOfWaterConsumption": ("1900000", "kl"),
    "TotalWasteGenerated": ("95000", "t"),
    "TotalWasteRecovered": ("85000", "t"),
}
UNIT_MEASURES = {
    "INR": "iso4217:INR",
    "GJ": "Non-SI:GJ",
    "TJ": "Non-SI:TJ",
    "MJ": "Non-SI:MJ",
    "tCO2e": "Non-SI:tCO2e",
    "ktCO2e": "Non-SI:ktCO2e",
    "MtCO2e": "Non-SI:MtCO2e",
    "kl": "in-capmkt-types:kl",
    "t": "Non-SI:t",
    "bogus": "Non-SI:furlongs",
    "GJ/INR": "Non-SI:GJ/iso4217:INR",
    "tCO2e/INR": "Non-SI:tCO2e/iso4217:INR",
    "kl/INR": "in-capmkt-types:kl/iso4217:INR",
    "t/INR": "Non-SI:t/iso4217:INR",
}
ASSURANCE = {
    "AssuranceSubTypeForDetailsOfTotalEnergyConsumptionInJoulesOrMultiplesAndEnergyIntensity",
    "AssuranceSubTypeForDetailsOfGreenHouseGasEmissionsAndItsIntensity",
    "AssuranceSubTypeForDetailsOfTheDisclosuresRelatedToWaterWithdrawal",
    "AssuranceSubTypeForDetailsRelatedToWasteManagementByTheEntity",
}


def build_instance(
    path: Path,
    *,
    isin: str | None = FAKE_ISIN,
    name: str = "Fake Cement Limited",
    boundary: str | None = "Standalone basis",
    current: dict | None = None,
    previous: dict | None = "default",
    schema: str | None = SCHEMA,
    assurance: str | None = "Reasonable",
    extra: str = "",
    previous_period: tuple[str, str] = ("2024-04-01", "2025-03-31"),
    current_period: tuple[str, str] = ("2025-04-01", "2026-03-31"),
    intensities: dict | None = None,
) -> Path:
    """Write an instance. `current`/`previous` map element -> (value, unit key) and override defaults
    per element; pass `previous=None` for a filing without a previous year."""
    cur = {**CURRENT, **(current or {})}
    prev = (
        None
        if previous is None
        else {**PREVIOUS, **(previous if isinstance(previous, dict) else {})}
    )
    used_units = {u for _, u in cur.values()} | ({u for _, u in prev.values()} if prev else set())
    used_units |= {u for _, u in (intensities or {}).values()}
    facts: list[str] = []

    def fact(element: str, ctx: str, value: str, unit: str | None = None) -> None:
        unit_attr = f' unitRef="U_{unit.replace("/", "_per_")}"' if unit else ""
        facts.append(
            f'<in-capmkt:{element} contextRef="{ctx}"{unit_attr}>{value}</in-capmkt:{element}>'
        )

    for element, (value, unit) in cur.items():
        fact(element, "DCYMain", value, unit)
    if prev:
        for element, (value, unit) in prev.items():
            fact(element, "DPYMain", value, unit)
    if isin:
        fact("ISIN", "ICYMain", isin)
    fact("NameOfTheCompany", "ICYMain", name)
    if boundary:
        fact("ReportingBoundary", "DCYMain", boundary)
    if assurance:
        for element in sorted(ASSURANCE):
            fact(element, "DCYMain", assurance)
        fact(
            "NameOfTheCompanyOrLLPOrFirmOfAssessmentOrAssuranceProvider",
            "DCYMain",
            "Fake Assurers LLP",
        )
    for element, (value, unit) in (intensities or {}).items():
        fact(element, "DCYMain", value, unit)
    # a dimensional fact with a DIFFERENT revenue: it must never be read as company-level
    facts.append(
        '<in-capmkt:RevenueFromOperations contextRef="D_Seg" unitRef="U_INR">1</in-capmkt:RevenueFromOperations>'
    )

    for u in used_units:
        if u not in UNIT_MEASURES:
            raise KeyError(u)

    def unit_element(u: str) -> str:
        measure = UNIT_MEASURES[u]
        if "/" in measure:
            num, den = measure.split("/")
            return (
                f'<xbrli:unit id="U_{u.replace("/", "_per_")}"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>{num}'
                f"</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>{den}"
                "</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>"
            )
        return f'<xbrli:unit id="U_{u}"><xbrli:measure>{measure}</xbrli:measure></xbrli:unit>'

    unit_xml = "".join(unit_element(u) for u in sorted(used_units | {"INR"}))
    ident = '<xbrli:entity><xbrli:identifier scheme="https://www.sebi.gov.in/in-capmkt/ISIN">X</xbrli:identifier></xbrli:entity>'

    def duration(cid, span):
        return (
            f'<xbrli:context id="{cid}">{ident}<xbrli:period><xbrli:startDate>{span[0]}</xbrli:startDate>'
            f"<xbrli:endDate>{span[1]}</xbrli:endDate></xbrli:period></xbrli:context>"
        )

    contexts = duration("DCYMain", current_period) + duration("DPYMain", previous_period)
    contexts += (
        f'<xbrli:context id="ICYMain">{ident}<xbrli:period><xbrli:instant>{current_period[1]}</xbrli:instant>'
        "</xbrli:period></xbrli:context>"
    )
    contexts += (
        '<xbrli:context id="D_Seg"><xbrli:entity><xbrli:identifier scheme="s">X</xbrli:identifier>'
        '<xbrli:segment><xbrldi:explicitMember dimension="in-capmkt:SomeAxis">in-capmkt:SomeMember'
        f"</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>{current_period[0]}"
        f"</xbrli:startDate><xbrli:endDate>{current_period[1]}</xbrli:endDate></xbrli:period></xbrli:context>"
    )
    ref = f'<link:schemaRef xlink:type="simple" xlink:href="{schema}"/>' if schema else ""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:link="http://www.xbrl.org/2003/linkbase" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
        'xmlns:iso4217="http://www.xbrl.org/2003/iso4217" xmlns:Non-SI="http://www.xbrl.org/2009/utr" '
        'xmlns:in-capmkt-types="https://www.sebi.gov.in/xbrl/2026-02-28/in-capmkt-types" '
        'xmlns:in-capmkt="https://www.sebi.gov.in/xbrl/2026-02-28/in-capmkt">'
        f"{ref}{contexts}{unit_xml}{''.join(facts)}{extra}</xbrli:xbrl>"
    )
    path.write_text(xml, encoding="utf-8")
    return path
