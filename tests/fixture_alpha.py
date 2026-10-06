"""A small controlled world for the interpretation and page tests, with every value chosen by hand.

Test Alpha has five companies (XAA-01 .. XAA-05) in two fiscal years, one impossible figure and one
metric whose values are nearly identical. Test Beta has two companies, too few to place in thirds.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from gauge.db.models import Company, IndicatorValue, KpiValue, QualityFlag, Report, Sector
from gauge.db.session import session_scope

FY, PRIOR = "FY2024-25", "FY2023-24"
ALPHA = ["XAA-01", "XAA-02", "XAA-03", "XAA-04", "XAA-05"]

# emissions intensity (lower is better): this year, last year
EMISSIONS = {
    "XAA-01": (10, 10),  # unchanged
    "XAA-02": (20, 25),  # (20-25)/25 = -20.0%: better
    "XAA-03": (30, 27),  # (30-27)/27 = +11.11%: worse
    "XAA-04": (40, Decimal("40.2")),  # (40-40.2)/40.2 = -0.4975%: about the same
    "XAA-05": (50, 40),  # (50-40)/40 = +25%: worse
}
# waste recovery rate (higher is better); XAA-05's 103 is impossible and flagged as an error
WASTE = {"XAA-01": 95, "XAA-02": 96, "XAA-03": 97, "XAA-04": 98, "XAA-05": 103}
# renewable share (higher is better): all within 1% of each other
RENEWABLE = {
    "XAA-01": "50.0",
    "XAA-02": "50.1",
    "XAA-03": "50.2",
    "XAA-04": "50.3",
    "XAA-05": "50.4",
}


def build_alpha_world(db):
    """Test Alpha: five companies, two years. Test Beta: two companies (too few to place)."""
    with session_scope(db.engine) as s:
        alpha = Sector(code="XAA", name="Test Alpha")
        beta = Sector(code="XBB", name="Test Beta")
        s.add_all([alpha, beta])
        s.flush()
        company = {}
        for code in ALPHA:
            company[code] = Company(code=code, real_name=f"{code} Ltd", sector_id=alpha.id)
        for code in ("XBB-01", "XBB-02"):
            company[code] = Company(code=code, real_name=f"{code} Ltd", sector_id=beta.id)
        s.add_all(company.values())
        s.flush()

        def kpi(code, fy, name, value):
            s.add(
                KpiValue(
                    company_id=company[code].id,
                    fy=fy,
                    kpi=name,
                    value=Decimal(str(value)),
                    engine_version="t",
                )
            )

        for code, (now, before) in EMISSIONS.items():
            kpi(code, FY, "emissions_intensity", now)
            kpi(code, PRIOR, "emissions_intensity", before)
        for code, value in WASTE.items():
            kpi(code, FY, "waste_recovery_rate", value)
        kpi("XAA-01", PRIOR, "waste_recovery_rate", 94)  # (95-94)/94 = +1.0638%
        kpi("XAA-02", PRIOR, "waste_recovery_rate", 90)  # but this year's flag below taints it
        for code, value in RENEWABLE.items():
            kpi(code, FY, "renewable_share", value)
        kpi("XBB-01", FY, "emissions_intensity", 100)
        kpi("XBB-02", FY, "emissions_intensity", 200)

        def error(code, fy, rule, indicator):
            s.add(
                QualityFlag(
                    company_id=company[code].id,
                    fy=fy,
                    rule=rule,
                    severity="error",
                    indicator=indicator,
                    message=f"{code}: {rule}",
                )
            )

        error("XAA-05", FY, "recovered_le_generated", "waste_recovered")  # 103% recovered
        error("XAA-02", PRIOR, "recovered_le_generated", "waste_recovered")  # taints XAA-02's 90
        s.add(
            QualityFlag(
                company_id=company["XAA-03"].id,
                fy=FY,
                rule="xbrl_override_applied",
                severity="warning",
                message="XAA-03: unit override",
            )
        )

        report = Report(
            company_id=company["XAA-01"].id,
            fy=FY,
            boundary="standalone",
            assured=True,
            source_file="data/raw/xbrl/A1.xml",
            file_sha256="cd" * 32,
            retrieved_on=date(2026, 10, 2),
            entry_method="xbrl",
        )
        later = Report(
            company_id=company["XAA-05"].id,
            fy=FY,
            entry_method="xbrl_comparative",
            retrieved_on=date(2026, 10, 3),
        )
        s.add_all([report, later])
        s.flush()
        s.add(
            IndicatorValue(
                report_id=report.id,
                indicator="scope1_emissions",
                value=Decimal(1),
                unit="tCO2e",
                verified=True,
                verification_note="matches page 48",
            )
        )
        s.add(
            IndicatorValue(
                report_id=report.id,
                indicator="revenue_from_operations",
                value=Decimal(2),
                unit="INR_crore",
            )
        )
    return db
