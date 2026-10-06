"""Quantiles and sector benchmarks. Small cases are worked by hand; the exact Decimal quantile is
also checked against numpy's `method="linear"` on random samples."""

from __future__ import annotations

import random
from decimal import Decimal

import numpy as np
import pytest
from sqlalchemy import select

from gauge.benchmark.compute import MIN_N, compute_benchmarks
from gauge.benchmark.quantiles import describe, quantile
from gauge.db.models import Company, KpiValue, Sector, SectorBenchmark
from gauge.db.session import session_scope
from gauge.kpi.engine import quantize

D = Decimal


def ds(*xs) -> list[Decimal]:
    return [D(str(x)) for x in xs]


def test_hand_calculated_quantiles_n5():
    xs = ds(5, 1, 4, 2, 3)  # sorted: 1 2 3 4 5; unsorted input on purpose
    assert quantile(xs, 1, 2) == D("3")  # median: h = 4 * 1/2 = 2 -> x[2]
    assert quantile(xs, 1, 4) == D("2")  # P25:    h = 4 * 1/4 = 1 -> x[1]
    assert quantile(xs, 3, 4) == D("4")  # P75:    h = 4 * 3/4 = 3 -> x[3]
    # lower tertile cut: h = 4/3 = 1.333.. -> 2 + (1/3) * (3 - 2) = 2.3333..
    assert quantize(quantile(xs, 1, 3)) == D("2.333333333333")  # 7/3 at stored precision
    # upper tertile cut: h = 8/3 = 2.666.. -> 3 + (2/3) * (4 - 3) = 3.6666..
    assert quantize(quantile(xs, 2, 3)) == D("3.666666666667")  # 11/3 at stored precision


def test_hand_calculated_quantiles_n4():
    xs = ds(10, 20, 30, 40)
    assert quantile(xs, 1, 2) == D("25")  # h = 1.5 -> 20 + 0.5 * 10
    assert quantile(xs, 1, 4) == D("17.5")  # h = 0.75 -> 10 + 0.75 * 10
    assert quantile(xs, 3, 4) == D("32.5")  # h = 2.25 -> 30 + 0.25 * 10


def test_extremes_and_tiny_samples():
    xs = ds(7, 3, 9)
    assert quantile(xs, 0, 1) == D("3") and quantile(xs, 1, 1) == D("9")
    assert quantile(ds(42), 1, 3) == D("42")  # n = 1: every quantile is the value
    assert quantile(ds(1, 2), 1, 2) == D("1.5")


def test_describe_keys():
    out = describe(ds(1, 2, 3, 4, 5))
    assert set(out) == {"median", "p25", "p75", "p33", "p67"}
    assert out["p25"] <= out["median"] <= out["p75"] and out["p33"] <= out["p67"]


@pytest.mark.parametrize("bad", [(1, 0), (2, 1), (-1, 2), (1, -2)])
def test_invalid_probabilities(bad):
    with pytest.raises(ValueError):
        quantile(ds(1, 2, 3), *bad)


def test_empty_sample():
    with pytest.raises(ValueError, match="empty"):
        quantile([], 1, 2)


def test_matches_numpy_linear_on_random_samples():
    rng = random.Random(7)
    for _ in range(300):
        n = rng.randint(1, 12)
        xs = [D(str(round(rng.uniform(-50, 500), 4))) for _ in range(n)]
        for k, m in ((1, 2), (1, 4), (3, 4), (1, 3), (2, 3)):
            expected = np.quantile([float(x) for x in xs], k / m, method="linear")
            assert float(quantile(xs, k, m)) == pytest.approx(expected, abs=1e-9)


def test_ties_do_not_break_interpolation():
    assert describe(ds(2, 2, 2, 2, 2))["p33"] == D("2")
    assert quantile(ds(1, 1, 5), 1, 2) == D("1")


# ---- database step ------------------------------------------------------------------------------
def _setup(db, *, statuses, kpi="emissions_intensity", fy="FY2024-25", values=(10, 20, 30, 40, 50)):
    with session_scope(db.engine) as s:
        sector = s.scalar(select(Sector).where(Sector.code == "SYA"))
        for i, (status, value) in enumerate(zip(statuses, values, strict=False), start=1):
            reason = "x" if status == "excluded" else None
            c = Company(
                code=f"SYA-{i:02d}",
                real_name=f"C{i}",
                sector_id=sector.id,
                selection_status=status,
                exclusion_reason=reason,
            )
            s.add(c)
            s.flush()
            s.add(
                KpiValue(company_id=c.id, fy=fy, kpi=kpi, value=D(str(value)), engine_version="t")
            )


def test_benchmarks_for_five_included_companies(db):
    _setup(db, statuses=["included"] * 5)
    with session_scope(db.engine) as s:
        summary = compute_benchmarks(s, db.cfg, ["emissions_intensity"])
    assert summary.written == 1
    with session_scope(db.engine) as s:
        row = s.scalar(select(SectorBenchmark))
    # values 10..50: median 30, P25 20, P75 40; tertile cuts 20 + 1/3 * 10 and 30 + 2/3 * 10
    assert (row.n, row.median, row.p25, row.p75) == (5, D("30"), D("20"), D("40"))
    assert row.p33 == D("23.333333333333") and row.p67 == D("36.666666666667")
    assert row.fy == "FY2024-25" and row.kpi == "emissions_intensity"


def test_only_included_companies_count(db):
    # 3 included (10, 20, 30) + 1 candidate (99) + 1 excluded (100): the extremes must not leak in
    _setup(
        db,
        statuses=["included", "included", "included", "candidate", "excluded"],
        values=(10, 20, 30, 99, 100),
    )
    with session_scope(db.engine) as s:
        compute_benchmarks(s, db.cfg, ["emissions_intensity"])
        row = s.scalar(select(SectorBenchmark))
    assert row.n == 3 and row.median == D("20") and row.p75 == D("25")


def test_too_few_companies_are_skipped_and_reported(db):
    _setup(db, statuses=["included"] * (MIN_N - 1), values=(10, 20))
    with session_scope(db.engine) as s:
        summary = compute_benchmarks(s, db.cfg, ["emissions_intensity"])
        assert s.scalar(select(SectorBenchmark)) is None
    assert summary.written == 0
    assert any("SYA FY2024-25 emissions_intensity: n=2" in m for m in summary.skipped)


def test_no_included_companies_is_reported(db):
    _setup(db, statuses=["candidate"] * 4, values=(1, 2, 3, 4))
    with session_scope(db.engine) as s:
        summary = compute_benchmarks(s, db.cfg, ["emissions_intensity"])
    assert summary.no_included_companies and summary.written == 0


def test_rerun_replaces_previous_benchmarks(db):
    _setup(db, statuses=["included"] * 5)
    for _ in range(2):
        with session_scope(db.engine) as s:
            compute_benchmarks(s, db.cfg, ["emissions_intensity"])
    with session_scope(db.engine) as s:
        assert len(s.scalars(select(SectorBenchmark)).all()) == 1
