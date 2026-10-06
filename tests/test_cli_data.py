"""The data commands as a user runs them (dry config: sectors Synthetic Alpha/Beta, tmp root)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select, update
from typer.testing import CliRunner

from gauge.cli import app
from gauge.config import load_study
from gauge.db.models import Company, IndicatorValue, KpiValue, QualityFlag, Report, SectorBenchmark
from gauge.db.session import make_engine, session_scope
from helpers import manual_row as row
from helpers import write_manual_csv

D = Decimal
cli = CliRunner()
CONFIG = ["--config", "config/study_dry.yaml"]


def gauge(*args):
    return cli.invoke(app, [*CONFIG, *args])


def good_rows():
    """One company, three years, all nine indicators, a mix of as-reported units."""
    rows = []
    for fy, scale in (("FY2022-23", 1), ("FY2023-24", 2), ("FY2024-25", 3)):
        rows += [
            row(
                fy=fy,
                indicator="revenue_from_operations",
                value=str(1000 * scale),
                unit="INR crore",
            ),
            row(fy=fy, indicator="energy_total", value=str(100 * scale), unit="MWh"),
            row(fy=fy, indicator="energy_renewable", value=str(20 * scale), unit="MWh"),
            row(fy=fy, indicator="scope1_emissions", value=str(50 * scale), unit="tCO2e"),
            row(fy=fy, indicator="scope2_emissions", value=str(10 * scale), unit="MT"),
            row(fy=fy, indicator="water_withdrawal", value=str(1_200_000 * scale), unit="kL"),
            row(fy=fy, indicator="water_consumption", value=str(300 * scale), unit="Mn Lt"),
            row(fy=fy, indicator="waste_generated", value=str(80 * scale), unit="t"),
            row(fy=fy, indicator="waste_recovered", value=str(40 * scale), unit="kg"),
        ]
    return rows


@pytest.fixture
def ready(proj):
    """init-db done and a valid CSV on disk."""
    assert gauge("init-db").exit_code == 0
    return write_manual_csv(proj / "filings.csv", good_rows())


def engine_for(proj):
    return make_engine(load_study("config/study_dry.yaml").database_url())


def count(engine, table, *where):
    with session_scope(engine) as s:
        return s.scalar(select(func.count()).select_from(table).where(*where))


# ---- ingest -------------------------------------------------------------------------------------
def test_validate_only_reports_without_needing_a_database(proj):
    path = write_manual_csv(proj / "f.csv", [row(), row(sector="Cement", fy="FY25")])
    result = gauge("ingest", "--manual", str(path), "--validate-only")
    assert result.exit_code == 1
    assert "line 3" in result.output and "1 valid rows, 2 errors" in result.output
    assert not (proj / "dry" / "gauge_dry.db").exists()


def test_validate_only_accepts_a_good_file(proj):
    path = write_manual_csv(proj / "f.csv", good_rows())
    result = gauge("ingest", "--manual", str(path), "--validate-only")
    assert result.exit_code == 0 and "27 valid rows, 0 errors" in result.output


def test_relative_paths_resolve_from_the_project_root(proj):
    write_manual_csv(proj / "f.csv", good_rows())
    assert gauge("ingest", "--manual", "f.csv", "--validate-only").exit_code == 0


def test_ingest_needs_an_existing_database(proj):
    path = write_manual_csv(proj / "f.csv", good_rows())
    result = gauge("ingest", "--manual", str(path))
    assert result.exit_code == 1 and "gauge init-db" in result.output
    assert not (proj / "dry" / "gauge_dry.db").exists()  # and it did not create one


def test_ingest_loads_candidates_with_provenance(ready, proj):
    result = gauge("ingest", "--manual", str(ready), "--retrieved-on", "2026-09-30")
    assert result.exit_code == 0, result.output
    assert "1 new companies, 3 reports, 27 values" in result.output
    engine = engine_for(proj)
    with session_scope(engine) as s:
        company = s.scalar(select(Company))
        retrieved = {r.retrieved_on.isoformat() for r in s.scalars(select(Report))}
    assert company.selection_status == "candidate" and retrieved == {"2026-09-30"}
    engine.dispose()


def test_ingest_without_retrieval_date_says_so(ready):
    result = gauge("ingest", "--manual", str(ready))
    assert result.exit_code == 0 and "no --retrieved-on" in result.output


def test_bad_retrieval_date_is_rejected(ready):
    assert gauge("ingest", "--manual", str(ready), "--retrieved-on", "30/09/2026").exit_code != 0


def test_ingest_with_errors_loads_nothing(proj):
    assert gauge("init-db").exit_code == 0
    path = write_manual_csv(proj / "f.csv", [*good_rows(), row(value="oops", fy="FY2022-23")])
    result = gauge("ingest", "--manual", str(path))
    assert result.exit_code == 1 and "nothing loaded" in result.output
    engine = engine_for(proj)
    assert count(engine, Company) == 0 and count(engine, IndicatorValue) == 0
    engine.dispose()


# ---- standardize / validate / kpis / benchmarks -------------------------------------------------
def test_full_flow(ready, proj):
    assert gauge("ingest", "--manual", str(ready), "--retrieved-on", "2026-09-30").exit_code == 0
    out = gauge("standardize")
    # converted: energy (MWh) 6 + water consumption (Mn Lt) 3 + waste recovered (kg) 3 = 12
    assert out.exit_code == 0 and "12 converted, 15 already canonical, 0 done before" in out.output
    again = gauge("standardize")
    assert (
        again.exit_code == 0 and "0 converted, 0 already canonical, 27 done before" in again.output
    )

    out = gauge("validate")
    assert out.exit_code == 0 and "0 errors" in out.output
    assert gauge("validate", "--strict").exit_code == 0

    out = gauge("compute-kpis")
    assert out.exit_code == 0 and "15 KPI values, 5 2-year changes" in out.output

    engine = engine_for(proj)
    with session_scope(engine) as s:
        kpis = {(k.fy, k.kpi): k for k in s.scalars(select(KpiValue))}
    # FY2024-25: revenue 3000 crore; energy 300 MWh = 1080 GJ; renewable 60 MWh = 216 GJ
    # energy intensity = 1080 / 3000 = 0.36; renewable share = 100 * 216 / 1080 = 20
    assert kpis[("FY2024-25", "energy_intensity")].value == D("0.36")
    assert kpis[("FY2024-25", "renewable_share")].value == D("20")
    # water consumption 900 Mn Lt = 900,000 kL; intensity = 900,000 / 3,000 = 300
    assert kpis[("FY2024-25", "water_intensity")].value == D("300")
    # scope 1 150 + scope 2 30 = 180 tCO2e; intensity 180 / 3000 = 0.06
    assert kpis[("FY2024-25", "emissions_intensity")].value == D("0.06")
    # waste: 240 t generated, 120 kg = 0.12 t recovered -> 100 * 0.12 / 240 = 0.05 %
    assert kpis[("FY2024-25", "waste_recovery_rate")].value == D("0.05")
    engine.dispose()


def test_benchmarks_wait_for_sample_selection(ready, proj):
    for cmd in (["ingest", "--manual", str(ready)], ["standardize"], ["compute-kpis"]):
        assert gauge(*cmd).exit_code == 0
    out = gauge("benchmarks")
    assert out.exit_code == 0 and "no companies are `included` yet" in out.output
    engine = engine_for(proj)
    assert count(engine, SectorBenchmark) == 0
    engine.dispose()


def test_benchmarks_for_included_companies(ready, proj):
    for cmd in (["ingest", "--manual", str(ready)], ["standardize"], ["compute-kpis"]):
        assert gauge(*cmd).exit_code == 0
    engine = engine_for(proj)
    with session_scope(engine) as s:
        s.execute(update(Company).values(selection_status="included"))
    out = gauge("benchmarks")
    assert out.exit_code == 0 and "0 sector benchmarks" in out.output and "n=1 < 3" in out.output
    engine.dispose()


def test_validate_and_kpis_demand_standardized_data(ready):
    assert gauge("ingest", "--manual", str(ready)).exit_code == 0
    for cmd in ("validate", "compute-kpis"):
        out = gauge(cmd)
        assert out.exit_code == 1 and "gauge standardize" in out.output


def test_strict_validate_fails_on_errors(proj):
    assert gauge("init-db").exit_code == 0
    rows = good_rows()
    for r in rows:  # 500 MWh renewable against 300 MWh total energy in the analysis year
        if r["fy"] == "FY2024-25" and r["indicator"] == "energy_renewable":
            r["value"] = "500"
    path = write_manual_csv(proj / "f.csv", rows)
    for cmd in (["ingest", "--manual", str(path)], ["standardize"]):
        assert gauge(*cmd).exit_code == 0
    assert gauge("validate").exit_code == 0  # flags are findings, not failures
    strict = gauge("validate", "--strict")
    assert strict.exit_code == 1 and "renewable_le_total=1" in strict.output
    engine = engine_for(proj)
    assert count(engine, QualityFlag, QualityFlag.rule == "renewable_le_total") == 1
    engine.dispose()


def test_unconvertible_unit_is_caught_at_ingest_not_later(proj):
    assert gauge("init-db").exit_code == 0
    path = write_manual_csv(
        proj / "f.csv", [row(indicator="waste_generated", value="5", unit="tons")]
    )
    out = gauge("ingest", "--manual", str(path), "--validate-only")
    assert out.exit_code == 1 and "ambiguous" in out.output


def test_init_db_reports_sdg_mappings(proj):
    out = gauge("init-db")
    assert "13 sdg_mappings" in out.output
