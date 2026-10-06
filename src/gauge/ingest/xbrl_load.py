"""Load extracted BRSR XBRL filings into the database.

Each filing yields up to two reports: its own fiscal year (entry method `xbrl`, "as filed") and the
previous-year column it carries (`xbrl_comparative`, restated by the filer in a later filing). When
both exist for a company-year the as-filed report wins, whatever the order of loading, and a
difference of more than 1% is recorded as a restatement flag.

A company-year is loaded only if all nine indicators resolved to a unit; otherwise it is skipped and
reported with the reason (and a hint where one exists). Loading is idempotent.
"""

from __future__ import annotations

import hashlib
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig, StudyConfig
from gauge.db.models import Company, IndicatorValue, QualityFlag, Report, Sector
from gauge.ingest.manual import assign_codes
from gauge.ingest.pool import PoolEntry
from gauge.ingest.xbrl_extract import CANONICAL, Filing, YearData, extract_filing
from gauge.ingest.xbrl_map import Override, XbrlMapping, load_cin_map
from gauge.standardize.units import UnitError, factor_to_canonical

FILING_RULES = ("xbrl_override_applied", "xbrl_intensity_mismatch", "xbrl_scale_break")
RESTATEMENT_RULE = "xbrl_restatement"
XBRL_RULES = (*FILING_RULES, RESTATEMENT_RULE)
RESTATEMENT_THRESHOLD = Decimal("0.01")
PRIORITY = {"xbrl_comparative": 1, "xbrl": 2, "manual": 3, "synthetic": 3}


@dataclass
class FilingOutcome:
    path: Path
    name: str | None
    loaded: list[str] = field(default_factory=list)  # fiscal years written
    kept: list[str] = field(
        default_factory=list
    )  # comparatives not written: an as-filed report exists
    skipped: dict[str, str] = field(default_factory=dict)  # fy -> reason
    refused: str | None = None


@dataclass
class XbrlLoadSummary:
    outcomes: list[FilingOutcome] = field(default_factory=list)
    companies_created: int = 0
    reports_written: int = 0
    restatements: int = 0

    @property
    def refused(self) -> list[FilingOutcome]:
        return [o for o in self.outcomes if o.refused]

    @property
    def skipped(self) -> int:
        return sum(len(o.skipped) for o in self.outcomes)


def _canonical(value: Decimal, unit: str, code: str) -> Decimal:
    try:
        return value * factor_to_canonical(unit, CANONICAL[code])
    except UnitError:
        return value


def discover(paths: list[Path]) -> list[Path]:
    """Files given explicitly, plus every *.xml in the directories given."""
    out: list[Path] = []
    for p in paths:
        out.extend(sorted(p.glob("*.xml")) if p.is_dir() else [p])
    return out


def load_xbrl(
    session: Session,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    mapping: XbrlMapping,
    overrides: list[Override],
    pool: dict[str, PoolEntry],
    paths: list[Path],
    *,
    retrieved_on: date | None = None,
    copy_to_raw: bool = True,
) -> XbrlLoadSummary:
    summary = XbrlLoadSummary()
    cin_to_isin = load_cin_map(cfg.root)
    filings: list[tuple[Filing, FilingOutcome]] = []
    for path in discover(paths):
        filing = extract_filing(path, mapping, overrides, cin_to_isin)
        outcome = FilingOutcome(path=path, name=filing.name)
        summary.outcomes.append(outcome)
        if filing.refused:
            outcome.refused = "; ".join(i.message for i in filing.issues if i.level == "error")
        elif filing.isin not in pool:
            outcome.refused = f"ISIN {filing.isin} is not in data/reference/candidate_pool.csv"
        else:
            filings.append((filing, outcome))

    sectors = {s.name: s for s in session.scalars(select(Sector))}
    configured = {s.name for s in cfg.study.sectors}
    by_isin = {c.isin: c for c in session.scalars(select(Company)) if c.isin}

    new_by_sector: dict[str, list[str]] = defaultdict(list)
    for filing, outcome in filings:
        entry = pool[filing.isin]
        if entry.sector not in configured or entry.sector not in sectors:
            outcome.refused = f"pool sector {entry.sector!r} is not a registered study sector"
        elif filing.isin not in by_isin and filing.isin not in new_by_sector[entry.sector]:
            new_by_sector[entry.sector].append(filing.isin)
    if not sectors:
        raise LookupError("sectors not registered: run `gauge init-db` first")

    sector_code = {s.name: s.code for s in cfg.study.sectors}
    for sector_name, isins in new_by_sector.items():
        taken = set(
            session.scalars(
                select(Company.code).where(Company.sector_id == sectors[sector_name].id)
            )
        )
        codes = assign_codes(taken, isins, sector_code[sector_name], cfg.runs.master_seed)
        for isin in isins:
            entry = pool[isin]
            company = Company(
                code=codes[isin], real_name=entry.company_name, nse_symbol=entry.nse_symbol,
                isin=isin, sector_id=sectors[entry.sector].id, selection_status="candidate",
                is_synthetic=False,
            )  # fmt: skip
            session.add(company)
            by_isin[isin] = company
            summary.companies_created += 1
    session.flush()

    for filing, outcome in filings:
        if outcome.refused:
            continue
        company = by_isin[filing.isin]
        # The first filing names the company. A later file must not rename it: the FY2023-24
        # taxonomy spells "JK Cement Limited" where the FY2025-26 filing says "J.K. Cement Limited".
        entry = pool[filing.isin]
        if not company.real_name or company.real_name == entry.company_name:
            company.real_name = filing.name or company.real_name
        stored = _stored_copy(cfg, filing, pool[filing.isin]) if copy_to_raw else filing.path
        for year in filing.years:
            if not year.complete:
                outcome.skipped[year.fy] = "; ".join(
                    f"{k}: {v}" for k, v in year.unresolved.items()
                )
                continue
            method = "xbrl" if year.current else "xbrl_comparative"
            wrote = _write_year(
                session, cfg, company, filing, year, method, stored, retrieved_on, summary
            )
            (outcome.loaded if wrote else outcome.kept).append(year.fy)
            summary.reports_written += wrote
    session.flush()
    return summary


def _stored_copy(cfg: StudyConfig, filing: Filing, entry: PoolEntry) -> Path:
    """Keep a copy under data/raw/xbrl/<SYMBOL>_<FY>.xml (never overwriting a different file)."""
    current = next(y for y in filing.years if y.current)
    folder = cfg.path(cfg.paths.raw_data_dir) / "xbrl"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{entry.nse_symbol}_{current.fy}.xml"
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != filing.sha256:
        target = folder / f"{entry.nse_symbol}_{current.fy}_{filing.sha256[:8]}.xml"
    if not target.exists():
        shutil.copy2(filing.path, target)
    return target


def _write_year(
    session, cfg, company, filing, year: YearData, method, stored, retrieved_on, summary
) -> bool:
    """Write one company-year. Returns False if a higher-priority report already exists (an
    as-filed one when `year` is only a comparative): the two are compared and `year` is kept out."""
    report = session.scalar(
        select(Report).where(Report.company_id == company.id, Report.fy == year.fy)
    )
    existing: dict[str, tuple[Decimal, str]] = {}
    if report is not None:
        for iv in session.scalars(
            select(IndicatorValue).where(IndicatorValue.report_id == report.id)
        ):
            existing[iv.indicator] = (iv.value, iv.unit)
        if report.entry_method in PRIORITY and PRIORITY[report.entry_method] > PRIORITY[method]:
            _flag_restatements(
                session,
                company,
                year,
                existing,
                summary,
                kept_method=report.entry_method,
                incoming_method=method,
            )
            return False
    if report is None:
        report = Report(company_id=company.id, fy=year.fy, entry_method=method)
        session.add(report)
    elif existing and report.entry_method != method:
        _flag_restatements(
            session,
            company,
            year,
            existing,
            summary,
            kept_method=report.entry_method,
            incoming_method=method,
        )

    report.entry_method = method
    report.boundary = filing.boundary
    report.assured = filing.assured if year.current else None
    report.assurance_note = (
        filing.assurance_note
        if year.current
        else ("previous-year column of a later filing: assurance of that year not stated here")
    )
    report.source_url = None
    report.source_file = _display(stored, cfg.root)
    report.file_sha256 = filing.sha256
    report.retrieved_on = retrieved_on
    session.flush()

    session.execute(delete(IndicatorValue).where(IndicatorValue.report_id == report.id))
    session.execute(
        delete(QualityFlag).where(
            QualityFlag.company_id == company.id,
            QualityFlag.fy == year.fy,
            QualityFlag.rule.in_(FILING_RULES),
        )
    )
    for code, r in year.values.items():
        session.add(IndicatorValue(
            report_id=report.id, indicator=code, value=r.value, unit=r.unit,
            page_ref=f"{r.element} [{r.basis}]",
        ))  # fmt: skip
    for rule, message in year.notes:
        session.add(QualityFlag(
            company_id=company.id, fy=year.fy, rule=rule, severity="warning",
            message=f"{company.code} {year.fy}: {message}",
        ))  # fmt: skip
    return True


_SOURCE = {
    "xbrl": "as-filed",
    "xbrl_comparative": "later comparative",
    "manual": "manual entry",
    "synthetic": "synthetic",
}


def _flag_restatements(
    session, company, year: YearData, existing, summary, *, kept_method: str, incoming_method: str
):
    """Record indicators whose two reported values for the same company-year differ by more than 1%.
    The set of restatement flags for the company-year is replaced, so reloading never duplicates.
    `kept_method` is the report already stored; `incoming_method` is the filing being loaded."""
    session.execute(
        delete(QualityFlag).where(
            QualityFlag.company_id == company.id,
            QualityFlag.fy == year.fy,
            QualityFlag.rule == RESTATEMENT_RULE,
        )
    )
    which = f"{_SOURCE.get(kept_method, kept_method)} vs {_SOURCE.get(incoming_method, incoming_method)}"
    for code, r in year.values.items():
        if code not in existing:
            continue
        old_value, old_unit = existing[code]
        a, b = _canonical(old_value, old_unit, code), _canonical(r.value, r.unit, code)
        if a == 0 and b == 0:
            continue
        if a == 0 or abs(b - a) / abs(a) > RESTATEMENT_THRESHOLD:
            session.add(QualityFlag(
                company_id=company.id, fy=year.fy, indicator=code, rule=RESTATEMENT_RULE,
                severity="warning",
                message=(
                    f"{company.code} {year.fy}: {code} differs between filings ({which}): "
                    f"{a:.6g} vs {b:.6g}"
                ),
            ))  # fmt: skip
            summary.restatements += 1


def _display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
