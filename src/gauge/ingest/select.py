"""Sample selection (spec §4.1): largest by market cap, with complete core indicators.

The candidate pool (data/reference/candidate_pool.csv) already orders companies by AMFI rank within
each sector and marks `primary` and `spare` ones. Selection walks each sector in rank order, takes a
company if it is complete for every trend year, and otherwise records WHY it was excluded and moves
on to the next, until the configured number per sector is filled. Every exclusion is logged on the
company (`exclusion_reason`).

It refuses to act while any trend year has no reports at all (the data are not loaded yet), so that
a missing download can never be mistaken for an incomplete company.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig, StudyConfig
from gauge.db.models import Company, IndicatorValue, Report, Run, Sector
from gauge.ingest.pool import PoolEntry


class SelectionError(RuntimeError):
    """Selection cannot run yet (data missing) or would break an invariant."""


@dataclass
class SectorOutcome:
    sector: str
    included: list[str] = field(default_factory=list)  # NSE symbols
    excluded: dict[str, str] = field(default_factory=dict)  # symbol -> reason
    not_needed: list[str] = field(default_factory=list)  # spares left unused
    short_by: int = 0
    wanted_spares: list[str] = field(default_factory=list)  # pool spares not yet loaded


@dataclass
class SelectionResult:
    sectors: list[SectorOutcome]
    renumbered: dict[str, str] = field(default_factory=dict)  # old code -> new code

    @property
    def complete(self) -> bool:
        return all(s.short_by == 0 for s in self.sectors)


def _missing(session: Session, company: Company, fys: list[str], required: list[str]) -> list[str]:
    """'FY2022-23: water_withdrawal' style entries for everything absent for this company."""
    have: dict[str, set[str]] = defaultdict(set)
    for fy, indicator in session.execute(
        select(Report.fy, IndicatorValue.indicator)
        .join(IndicatorValue, IndicatorValue.report_id == Report.id)
        .where(Report.company_id == company.id)
    ):
        have[fy].add(indicator)
    out = []
    for fy in fys:
        if fy not in have:
            out.append(f"{fy}: no report")
        else:
            out.extend(f"{fy}: {code}" for code in required if code not in have[fy])
    return out


def run_selection(
    session: Session,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    pool: dict[str, PoolEntry],
    *,
    apply: bool = True,
    renumber: bool = True,
) -> SelectionResult:
    fys = cfg.study.trend_fys
    required = [i.code for i in indicators.indicators]

    reports_per_fy = dict(
        session.execute(
            select(Report.fy, func.count()).join(Company, Company.id == Report.company_id)
            .where(~Company.is_synthetic).group_by(Report.fy)
        ).all()
    )  # fmt: skip
    empty = [fy for fy in fys if not reports_per_fy.get(fy)]
    if empty:
        raise SelectionError(
            f"no reports are loaded for {', '.join(empty)}; load them first (`gauge ingest`). "
            "Selection is not run while a whole year is missing, so that a pending download "
            "is not mistaken for incomplete companies."
        )

    in_db = {c.isin: c for c in session.scalars(select(Company)) if c.isin}
    sectors: list[SectorOutcome] = []
    for sector in cfg.study.sectors:
        ranked = sorted(
            (
                e
                for e in pool.values()
                if e.sector == sector.name and e.pool in ("primary", "spare")
            ),
            key=lambda e: e.amfi_rank,
        )
        outcome = SectorOutcome(sector.name)
        for entry in ranked:
            company = in_db.get(entry.isin)
            if len(outcome.included) >= cfg.study.companies_per_sector:
                outcome.not_needed.append(entry.nse_symbol)
                continue
            if company is None:
                if entry.pool == "primary":
                    outcome.excluded[entry.nse_symbol] = (
                        "no filings loaded for this primary company"
                    )
                else:
                    outcome.wanted_spares.append(entry.nse_symbol)
                continue
            gaps = _missing(session, company, fys, required)
            if gaps:
                shown = "; ".join(gaps[:4]) + (
                    f"; and {len(gaps) - 4} more" if len(gaps) > 4 else ""
                )
                outcome.excluded[entry.nse_symbol] = f"incomplete core indicators: {shown}"
            else:
                outcome.included.append(entry.nse_symbol)
        outcome.short_by = max(0, cfg.study.companies_per_sector - len(outcome.included))
        sectors.append(outcome)

    result = SelectionResult(sectors)
    if not apply:
        return result

    included_symbols = {s for o in sectors for s in o.included}
    excluded_reasons = {s: r for o in sectors for s, r in o.excluded.items()}
    for company in in_db.values():
        symbol = company.nse_symbol
        if symbol in included_symbols:
            company.selection_status, company.exclusion_reason = "included", None
        elif symbol in excluded_reasons:
            company.selection_status, company.exclusion_reason = (
                "excluded",
                excluded_reasons[symbol],
            )
        else:
            company.selection_status, company.exclusion_reason = "candidate", None
    session.flush()
    if renumber and result.complete:
        result.renumbered = _renumber(session, cfg, sectors, pool)
    return result


def _renumber(
    session: Session, cfg: StudyConfig, sectors: list[SectorOutcome], pool: dict[str, PoolEntry]
) -> dict[str, str]:
    """Give each sector's included companies the codes SEC-01..SEC-N in a seeded-hash order that
    does not depend on size, then number the sector's other companies after them. Refused once
    any run exists: codes are part of the run record."""
    if session.scalar(select(func.count()).select_from(Run)):
        raise SelectionError("runs already exist: masked codes can no longer change")
    sector_ids = {s.name: s.id for s in session.scalars(select(Sector))}
    sector_code = {s.name: s.code for s in cfg.study.sectors}
    seed = cfg.runs.master_seed

    def order(company: Company) -> str:
        return hashlib.sha256(f"{seed}|{company.isin or company.nse_symbol}".encode()).hexdigest()

    targets: dict[int, tuple[Company, str]] = {}
    for outcome in sectors:
        members = list(
            session.scalars(select(Company).where(Company.sector_id == sector_ids[outcome.sector]))
        )
        chosen = sorted((c for c in members if c.nse_symbol in outcome.included), key=order)
        others = sorted((c for c in members if c.nse_symbol not in outcome.included), key=order)
        for n, company in enumerate([*chosen, *others], start=1):
            targets[company.id] = (company, f"{sector_code[outcome.sector]}-{n:02d}")
    changes = {c.code: new for c, new in targets.values() if c.code != new}
    # two passes through temporary codes so unique(code) is never violated part-way
    for company, new in targets.values():
        if company.code != new:
            company.code = f"TMP-{company.id:04d}"
    session.flush()
    for company, new in targets.values():
        if company.code.startswith("TMP-"):
            company.code = new
    session.flush()
    return changes
