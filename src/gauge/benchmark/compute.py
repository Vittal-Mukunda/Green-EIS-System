"""Sector benchmarks from the study's own included companies (spec §4.2).

The `p33`/`p67` columns hold the tertile cut-points (probabilities 1/3 and 2/3) that the T2 rule
uses. A sector-KPI-year needs at least MIN_N companies; with fewer there are no meaningful tertiles,
so it is skipped and reported, never extrapolated.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from gauge.benchmark.quantiles import describe
from gauge.config import StudyConfig
from gauge.db.models import Company, KpiValue, Sector, SectorBenchmark
from gauge.kpi.engine import quantize

MIN_N = 3


@dataclass
class BenchmarkSummary:
    written: int = 0
    skipped: list[str] = field(default_factory=list)
    no_included_companies: bool = False


@dataclass(frozen=True)
class BenchStats:
    n: int
    stats: dict[str, Decimal]  # median, p25, p75, p33, p67 at full (12 dp) precision


def collect_benchmarks(
    session: Session,
    cfg: StudyConfig,
    kpi_codes: list[str],
    *,
    statuses: tuple[str, ...] = ("included",),
    fys: list[str] | None = None,
) -> tuple[dict[tuple[str, str, str], BenchStats], list[str]]:
    """Benchmarks per (sector name, fy, kpi) for companies whose status is in `statuses`.

    Pure computation, nothing is written: `compute_benchmarks` stores the result for the real
    sample, and provisional previews (candidate companies) use it directly. Returns the stats and a
    list of skipped (sector, fy, kpi) with n < MIN_N.
    """
    sectors = {s.code: s for s in session.scalars(select(Sector))}
    in_sample = {
        c.id: c.sector_id
        for c in session.scalars(select(Company).where(Company.selection_status.in_(statuses)))
    }
    pooled: dict[tuple[int, str, str], list[Decimal]] = defaultdict(list)
    for kv in session.scalars(select(KpiValue)):
        sector_id = in_sample.get(kv.company_id)
        if sector_id is not None:
            pooled[(sector_id, kv.fy, kv.kpi)].append(kv.value)

    out: dict[tuple[str, str, str], BenchStats] = {}
    skipped: list[str] = []
    for sector in cfg.study.sectors:
        row = sectors.get(sector.code)
        if row is None:
            continue
        for fy in fys or cfg.study.trend_fys:
            for kpi in kpi_codes:
                values = pooled.get((row.id, fy, kpi), [])
                if len(values) < MIN_N:
                    skipped.append(f"{sector.code} {fy} {kpi}: n={len(values)} < {MIN_N}")
                    continue
                stats = {name: quantize(v) for name, v in describe(values).items()}
                out[(row.name, fy, kpi)] = BenchStats(len(values), stats)
    return out, skipped


def compute_benchmarks(
    session: Session, cfg: StudyConfig, kpi_codes: list[str]
) -> BenchmarkSummary:
    """Rebuild sector_benchmark from KPI values of `included` companies, for each of `kpi_codes`."""
    session.execute(delete(SectorBenchmark))
    summary = BenchmarkSummary()
    if session.scalar(select(Company.id).where(Company.selection_status == "included")) is None:
        summary.no_included_companies = True
        return summary

    sector_ids = {s.name: s.id for s in session.scalars(select(Sector))}
    found, summary.skipped = collect_benchmarks(session, cfg, kpi_codes)
    for (sector_name, fy, kpi), bench in found.items():
        session.add(
            SectorBenchmark(
                sector_id=sector_ids[sector_name], fy=fy, kpi=kpi, n=bench.n, **bench.stats
            )
        )
        summary.written += 1
    session.flush()
    return summary
