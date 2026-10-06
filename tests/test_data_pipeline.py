"""The data pipeline end to end on synthetic data: ingest -> standardize -> validate -> KPIs ->
benchmarks. The planted defects must be found, and the KPIs must match an independent calculation
written in this file (own unit table, own formulas, no code shared with the pipeline)."""

from __future__ import annotations

import csv
from collections import defaultdict
from decimal import Decimal

import pytest
from sqlalchemy import select

from gauge.config import load_indicators, load_study
from gauge.db.models import (
    Company,
    IndicatorValue,
    KpiValue,
    QualityFlag,
    Report,
    SectorBenchmark,
)
from gauge.db.session import make_engine, session_scope
from gauge.ingest.manual import parse_manual_csv
from gauge.pipeline import run_all_dry
from gauge.quality import validators as q
from gauge.synthetic_data import SYNTHETIC_DEFECTS, synthetic_symbol, write_synthetic_manual_csv

D = Decimal

# Independent unit table for the spellings the generator uses (value in unit * factor = canonical).
OWN_FACTOR = {
    "INR crore": D("1"),
    "INR lakh": D("0.01"),
    "GJ": D("1"),
    "MWh": D("3.6"),
    "TJ": D("1000"),
    "kL": D("1"),
    "m3": D("1"),
    "Mn Lt": D("1000"),
    "t": D("1"),
    "kg": D("0.001"),
    "MT": D("1"),
    "tCO2e": D("1"),
}


@pytest.fixture
def dry(proj):
    run_all_dry(root=proj)
    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    yield cfg, engine, cfg.path(cfg.paths.raw_data_dir) / "synthetic_manual_entry.csv"
    engine.dispose()


def flags_by_symbol(engine):
    out = defaultdict(list)
    with session_scope(engine) as s:
        for flag, symbol in s.execute(
            select(QualityFlag, Company.nse_symbol).join(
                Company, Company.id == QualityFlag.company_id
            )
        ):
            out[symbol].append((flag.rule, flag.severity, flag.fy, flag.indicator))
    return out


def test_every_planted_defect_is_found(dry):
    _, engine, _ = dry
    flags = flags_by_symbol(engine)
    for d in SYNTHETIC_DEFECTS:
        hits = [f for f in flags[d.symbol] if f[0] == d.rule and (d.fy is None or f[2] == d.fy)]
        assert hits, f"validator {d.rule} missed the planted defect for {d.symbol}: {d.what}"
        if d.indicator and d.rule != q.MISSING_INDICATOR:
            assert any(f[3] == d.indicator for f in hits)
        if d.rule == q.MISSING_INDICATOR:
            assert any(f[3] == d.indicator for f in hits)


def test_no_unplanted_errors(dry):
    """Clean synthetic data must not trip any error-level validator."""
    _, engine, _ = dry
    errors = {
        (sym, f[0], f[2])
        for sym, fl in flags_by_symbol(engine).items()
        for f in fl
        if f[1] == "error"
    }
    assert errors == {
        ("SYNA1", q.RENEWABLE_LE_TOTAL, "FY2024-25"),
        ("SYNB2", q.CONSUMPTION_LE_WITHDRAWAL, "FY2023-24"),
        ("SYNA3", q.RECOVERED_LE_GENERATED, "FY2022-23"),
        ("SYNB3", q.MISSING_INDICATOR, "FY2022-23"),
    }


def test_company_codes_match_the_masked_sample(dry):
    cfg, engine, _ = dry
    with session_scope(engine) as s:
        codes = set(s.scalars(select(Company.code)))
    assert codes == set(cfg.masked_codes())


def test_standardization_is_exact_and_keeps_originals(dry):
    _, engine, _ = dry
    with session_scope(engine) as s:
        rows = s.scalars(select(IndicatorValue)).all()
    assert all(r.original_unit is not None for r in rows)
    converted = [r for r in rows if r.original_unit != r.unit]
    assert len(converted) > 20  # the generator mixes units on purpose
    for r in rows:
        assert r.value == r.original_value * OWN_FACTOR[r.original_unit], (
            r.indicator,
            r.original_unit,
        )


def test_kpis_match_an_independent_calculation(dry):
    cfg, engine, csv_path = dry
    canonical = defaultdict(dict)  # (symbol, fy) -> indicator -> value in canonical units
    with csv_path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            canonical[(r["nse_symbol"], r["fy"])][r["indicator"]] = (
                D(r["value"]) * OWN_FACTOR[r["unit"]]
            )

    with session_scope(engine) as s:
        stored = {
            (sym, kv.fy, kv.kpi): kv.value
            for kv, sym in s.execute(
                select(KpiValue, Company.nse_symbol).join(
                    Company, Company.id == KpiValue.company_id
                )
            )
        }
    quantum = D("1E-12")
    checked = 0
    for (sym, fy), v in canonical.items():
        expected = {}
        if {"energy_total", "revenue_from_operations"} <= v.keys():
            expected["energy_intensity"] = v["energy_total"] / v["revenue_from_operations"]
        if {"scope1_emissions", "scope2_emissions", "revenue_from_operations"} <= v.keys():
            expected["emissions_intensity"] = (v["scope1_emissions"] + v["scope2_emissions"]) / v[
                "revenue_from_operations"
            ]
        if {"water_consumption", "revenue_from_operations"} <= v.keys():
            expected["water_intensity"] = v["water_consumption"] / v["revenue_from_operations"]
        if {"energy_renewable", "energy_total"} <= v.keys():
            expected["renewable_share"] = 100 * v["energy_renewable"] / v["energy_total"]
        if {"waste_recovered", "waste_generated"} <= v.keys():
            expected["waste_recovery_rate"] = 100 * v["waste_recovered"] / v["waste_generated"]
        for kpi, value in expected.items():
            assert abs(stored[(sym, fy, kpi)] - value) <= quantum, (sym, fy, kpi)
            checked += 1
    assert checked == len(stored) == 89  # 6 companies x 3 years x 5 KPIs, minus one omitted input


def test_two_year_change_is_stored_on_the_analysis_year(dry):
    _, engine, _ = dry
    with session_scope(engine) as s:
        rows = s.scalars(select(KpiValue)).all()
    by = {(r.company_id, r.fy, r.kpi): r for r in rows}
    for (cid, fy, kpi), r in by.items():
        old = by.get((cid, "FY2022-23", kpi))
        if fy == "FY2024-25" and old is not None and old.value != 0:
            expected = 100 * (r.value - old.value) / old.value
            assert abs(r.change_2y_pct - expected) <= D("1E-11")
        else:
            assert r.change_2y_pct is None


def test_benchmarks_for_the_analysis_year(dry):
    _, engine, _ = dry
    with session_scope(engine) as s:
        bench = s.scalars(select(SectorBenchmark).where(SectorBenchmark.fy == "FY2024-25")).all()
        kpis = defaultdict(list)
        for kv, sector_id in s.execute(
            select(KpiValue, Company.sector_id)
            .join(Company, Company.id == KpiValue.company_id)
            .where(KpiValue.fy == "FY2024-25")
        ):
            kpis[(sector_id, kv.kpi)].append(kv.value)
    assert len(bench) == 2 * 5  # 2 sectors x 5 KPIs
    for b in bench:
        xs = sorted(kpis[(b.sector_id, b.kpi)])
        assert b.n == 3 == len(xs)
        assert b.median == xs[1]  # n = 3: the middle value
        assert b.p25 == (xs[0] + (xs[1] - xs[0]) / 2).quantize(D("1E-12"))  # h = 2 * 1/4 = 0.5
        assert b.p25 <= b.median <= b.p75 and b.p33 <= b.p67


def test_the_small_n_skip_is_reported(proj):
    results = {r.name: r for r in run_all_dry(root=proj)}
    assert "skipped for n < 3" in results["benchmarks"].detail  # SYNB3 lacks one FY2022-23 input


def test_dry_run_is_deterministic(proj):
    def snapshot():
        run_all_dry(root=proj)
        cfg = load_study("config/study_dry.yaml")
        engine = make_engine(cfg.database_url())
        try:
            with session_scope(engine) as s:
                return (
                    sorted((c.code, c.real_name) for c in s.scalars(select(Company))),
                    sorted((r.fy, r.kpi, str(r.value)) for r in s.scalars(select(KpiValue))),
                    sorted((f.rule, f.message) for f in s.scalars(select(QualityFlag))),
                )
        finally:
            engine.dispose()

    assert snapshot() == snapshot()


# ---- the generator itself -----------------------------------------------------------------------
def test_generated_csv_passes_the_manual_validator_and_mixes_units(proj):
    cfg = load_study("config/study_dry.yaml")
    ind = load_indicators(cfg)
    path = proj / "syn.csv"
    planted = write_synthetic_manual_csv(cfg, ind, path)
    parsed = parse_manual_csv(path, cfg, ind)
    assert parsed.ok, [str(i) for i in parsed.errors]
    assert len(parsed.rows) == 6 * 3 * 9 - 1  # one planted omission
    assert len({r.unit for r in parsed.rows}) >= 8  # several spellings per dimension
    assert set(planted) == set(SYNTHETIC_DEFECTS) and len(planted) == len(SYNTHETIC_DEFECTS)


def test_generated_csv_is_byte_identical_across_runs(proj):
    cfg = load_study("config/study_dry.yaml")
    ind = load_indicators(cfg)
    write_synthetic_manual_csv(cfg, ind, proj / "a.csv")
    write_synthetic_manual_csv(cfg, ind, proj / "b.csv")
    assert (proj / "a.csv").read_bytes() == (proj / "b.csv").read_bytes()


def test_generated_data_is_marked_synthetic_everywhere(dry):
    _, engine, csv_path = dry
    text = csv_path.read_text(encoding="utf-8")
    assert "synthetic://dry-run" in text and "Synthetic" in text
    with session_scope(engine) as s:
        assert {c.is_synthetic for c in s.scalars(select(Company))} == {True}
        assert {r.entry_method for r in s.scalars(select(Report))} == {"synthetic"}
    assert synthetic_symbol(0, 1) == "SYNA1"
