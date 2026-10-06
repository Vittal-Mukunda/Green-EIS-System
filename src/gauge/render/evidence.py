"""Assemble the evidence shown to models from the database, rounded exactly once.

Raw indicators are shown in canonical units to 6 significant figures; KPIs, trends, sector medians,
quartiles and tertile cut-points to `figures` (4 by default). The rules (T2, T3) are applied to
these DISPLAYED values, so the answer is derivable from the prompt text. Nothing here is ever a
conclusion: no class, rating or data-quality verdict reaches a model.

Completeness: the three core KPIs (the ones the rules use) must be present for the analysis year
and, with trends, for every trend year, or the evidence is refused. Anything else that is missing
is kept as `None` and printed as "not reported": it is never filled in or guessed. (Sample
selection guarantees complete data for the real study, so this only matters for synthetic data and
for the optional leave-one-indicator-out extension.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.benchmark.compute import collect_benchmarks
from gauge.config import IndicatorsConfig, StudyConfig
from gauge.db.models import Company, IndicatorValue, KpiValue, Report, Sector, SectorBenchmark
from gauge.rules.rounding import sig_round

RAW_FIGURES = 6
DISPLAY_FIGURES = 4
STAT_NAMES = ("median", "p25", "p75", "p33", "p67")


class EvidenceError(RuntimeError):
    """The database cannot support the requested evidence (something is missing)."""


@dataclass(frozen=True)
class CompanyEvidence:
    code: str
    sector: str
    boundary: str | None
    assured: bool | None
    indicators: dict[str, Decimal | None]  # canonical units, analysis year, RAW_FIGURES
    kpis: dict[str, Decimal | None]  # analysis year, displayed
    trend: dict[str, dict[str, Decimal | None]] = field(default_factory=dict)  # kpi -> fy -> value


@dataclass(frozen=True)
class SectorBench:
    sector: str
    n: int
    stats: dict[str, dict[str, Decimal]]  # kpi -> {median, p25, p75, p33, p67}, displayed


@dataclass(frozen=True)
class Evidence:
    analysis_fy: str
    trend_fys: list[str]
    figures: int
    companies: dict[str, CompanyEvidence]  # by masked code
    sectors: dict[str, SectorBench]  # by sector name
    has_trend: bool
    provisional: bool  # built from `candidate` companies: a preview, never frozen
    synthetic: bool  # every company is synthetic (dry run)
    n_not_reported: int  # cells that will print as "not reported"


def _missing_text(problems: list[str], limit: int = 12) -> str:
    shown = "\n  ".join(problems[:limit])
    more = f"\n  ... and {len(problems) - limit} more" if len(problems) > limit else ""
    return shown + more


def _shown(value: Decimal | None, figures: int) -> Decimal | None:
    return None if value is None else sig_round(value, figures)


def load_evidence(
    session: Session,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    *,
    provisional: bool = False,
    with_trend: bool = True,
    figures: int = DISPLAY_FIGURES,
) -> Evidence:
    """Evidence for the study sample (`included` companies).

    `provisional` also takes `candidate` companies and computes the sector statistics on the fly
    instead of reading the stored benchmarks. It exists so prompts can be previewed before the
    sample is final; the result is labelled provisional and `freeze` refuses it.
    Raises EvidenceError listing everything that is missing.
    """
    analysis_fy, trend_fys = cfg.study.analysis_fy, list(cfg.study.trend_fys)
    kpi_codes = [k.code for k in indicators.kpis]
    core = {k.code for k in indicators.core_kpis}
    indicator_codes = [i.code for i in indicators.indicators]
    sectors = {s.id: s.name for s in session.scalars(select(Sector))}
    statuses = ("included", "candidate") if provisional else ("included",)

    companies = list(
        session.scalars(
            select(Company).where(Company.selection_status.in_(statuses)).order_by(Company.code)
        )
    )
    if not companies:
        raise EvidenceError(
            "no `included` companies: run `gauge select` first "
            "(or use --provisional to preview from candidates)"
        )
    if len({c.is_synthetic for c in companies}) > 1:
        raise EvidenceError("synthetic and real companies are mixed in one sample")

    problems: list[str] = []
    not_reported = 0
    out: dict[str, CompanyEvidence] = {}
    for c in companies:
        report = session.scalar(
            select(Report).where(Report.company_id == c.id, Report.fy == analysis_fy)
        )
        if report is None:
            problems.append(f"{c.code}: no {analysis_fy} report")
            continue
        raw = {
            iv.indicator: iv.value
            for iv in session.scalars(
                select(IndicatorValue).where(IndicatorValue.report_id == report.id)
            )
        }
        kpi_rows = {
            (k.fy, k.kpi): k.value
            for k in session.scalars(select(KpiValue).where(KpiValue.company_id == c.id))
        }
        missing_core = sorted(k for k in core if (analysis_fy, k) not in kpi_rows)
        if missing_core:
            problems.append(f"{c.code}: {analysis_fy} core KPIs missing {missing_core}")
            continue
        trend: dict[str, dict[str, Decimal | None]] = {}
        if with_trend:
            for k in kpi_codes:
                years = {fy: kpi_rows.get((fy, k)) for fy in trend_fys}
                gaps = [fy for fy, v in years.items() if v is None]
                if gaps and k in core:
                    problems.append(f"{c.code}: core KPI {k} missing for {gaps}")
                trend[k] = {fy: _shown(v, figures) for fy, v in years.items()}
                not_reported += len(gaps)
        ce = CompanyEvidence(
            code=c.code,
            sector=sectors[c.sector_id],
            boundary=report.boundary,
            assured=report.assured,
            indicators={k: _shown(raw.get(k), RAW_FIGURES) for k in indicator_codes},
            kpis={k: _shown(kpi_rows.get((analysis_fy, k)), figures) for k in kpi_codes},
            trend=trend,
        )
        not_reported += sum(v is None for v in ce.indicators.values())
        not_reported += sum(v is None for v in ce.kpis.values())
        out[c.code] = ce
    if problems:
        raise EvidenceError(f"evidence is incomplete:\n  {_missing_text(problems)}")

    stored = _stored_stats(session, analysis_fy, sectors, provisional, cfg, kpi_codes)
    benches: dict[str, SectorBench] = {}
    for name in sorted({c.sector for c in out.values()}):
        per_kpi = {kpi: stored[(name, kpi)] for kpi in kpi_codes if (name, kpi) in stored}
        absent_core = sorted(core - per_kpi.keys())
        if absent_core:
            raise EvidenceError(
                f"{name}: no {analysis_fy} benchmark for core KPIs {absent_core} "
                f"(needs >= 3 companies): run `gauge benchmarks`"
            )
        benches[name] = SectorBench(
            name,
            max(n for n, _ in per_kpi.values()),
            {
                kpi: {stat: sig_round(v, figures) for stat, v in stats.items()}
                for kpi, (_, stats) in per_kpi.items()
            },
        )
    return Evidence(
        analysis_fy,
        trend_fys,
        figures,
        out,
        benches,
        has_trend=with_trend,
        provisional=provisional,
        synthetic=all(c.is_synthetic for c in companies),
        n_not_reported=not_reported,
    )


def _stored_stats(
    session: Session,
    analysis_fy: str,
    sectors: dict[int, str],
    provisional: bool,
    cfg: StudyConfig,
    kpi_codes: list[str],
) -> dict[tuple[str, str], tuple[int, dict[str, Decimal]]]:
    """(sector name, kpi) -> (n, full-precision stats): from the benchmark table, or on the fly."""
    if provisional:
        found, _skipped = collect_benchmarks(
            session, cfg, kpi_codes, statuses=("included", "candidate"), fys=[analysis_fy]
        )
        return {(s, k): (b.n, b.stats) for (s, fy, k), b in found.items() if fy == analysis_fy}
    rows = session.scalars(select(SectorBenchmark).where(SectorBenchmark.fy == analysis_fy))
    return {
        (sectors[r.sector_id], r.kpi): (r.n, {s: getattr(r, s) for s in STAT_NAMES}) for r in rows
    }
