"""Manual-entry CSV: validator and loader (spec §6.2, the fallback when no structured source fits).

Columns: company, nse_symbol, sector, fy, indicator, value, unit, boundary, assured, source_url,
page_ref (see data/manual_entry_template.csv). Values are stored exactly as reported, in the unit
typed; `gauge standardize` converts them afterwards.

Loading is all-or-nothing: a file with any error loads nothing. Provenance (source_url and page_ref
per value, file SHA-256) is mandatory so `verify-sample` has something to check against.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge import vocab
from gauge.config import IndicatorsConfig, StudyConfig
from gauge.db.models import Company, IndicatorValue, Report, Sector
from gauge.standardize.fiscal import FiscalYearError, normalize_fy
from gauge.standardize.units import UnitError, factor_to_canonical

EXPECTED_COLUMNS = [
    "company",
    "nse_symbol",
    "sector",
    "fy",
    "indicator",
    "value",
    "unit",
    "boundary",
    "assured",
    "source_url",
    "page_ref",
]

_NUMBER = re.compile(r"^[+-]?\d[\d,]*(\.\d+)?([eE][+-]?\d+)?$")
_TRUE = {"true", "yes", "y", "1", "assured"}
_FALSE = {"false", "no", "n", "0", "not assured", "not_assured", "unassured"}


class IngestError(RuntimeError):
    """The file has errors; nothing was loaded."""


@dataclass(frozen=True)
class Issue:
    line: int  # 1-based CSV line (header = 1); 0 for file-level issues
    level: str  # error | warning
    message: str

    def __str__(self) -> str:
        where = f"line {self.line}" if self.line else "file"
        return f"[{self.level}] {where}: {self.message}"


@dataclass(frozen=True)
class ManualRow:
    line: int
    company: str
    nse_symbol: str
    sector: str  # canonical sector name from config
    fy: str  # canonical FY label
    indicator: str  # indicator code
    value: Decimal
    unit: str
    boundary: str | None
    assured: bool | None
    source_url: str
    page_ref: str

    @property
    def company_key(self) -> str:
        return company_key(self.nse_symbol, self.company)


@dataclass
class ParsedFile:
    path: Path
    sha256: str
    rows: list[ManualRow] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors


def company_key(nse_symbol: str, name: str) -> str:
    return nse_symbol.strip().upper() if nse_symbol.strip() else name.strip().casefold()


def parse_manual_csv(path: Path, cfg: StudyConfig, indicators: IndicatorsConfig) -> ParsedFile:
    """Read and validate a manual-entry CSV without touching the database."""
    raw_bytes = path.read_bytes()
    parsed = ParsedFile(path=path, sha256=hashlib.sha256(raw_bytes).hexdigest())
    text = raw_bytes.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())

    header = reader.fieldnames or []
    missing = [c for c in EXPECTED_COLUMNS if c not in header]
    extra = [c for c in header if c not in EXPECTED_COLUMNS]
    if missing:
        parsed.issues.append(Issue(1, "error", f"missing columns: {', '.join(missing)}"))
        return parsed
    if extra:
        parsed.issues.append(Issue(1, "warning", f"ignoring unknown columns: {', '.join(extra)}"))

    sectors = {s.name.casefold(): s.name for s in cfg.study.sectors}
    by_code = {i.code: i for i in indicators.indicators}
    by_label = {i.label.casefold(): i.code for i in indicators.indicators}

    for line, record in enumerate(reader, start=2):
        cells = {k: (record.get(k) or "").strip() for k in EXPECTED_COLUMNS}
        if not any(cells.values()):
            continue
        row = _parse_row(line, cells, parsed, sectors, by_code, by_label)
        if row is not None:
            parsed.rows.append(row)

    _cross_row_checks(parsed)
    if not parsed.rows and parsed.ok:
        parsed.issues.append(Issue(0, "error", "file contains no data rows"))
    return parsed


def _parse_row(line, cells, parsed, sectors, by_code, by_label) -> ManualRow | None:
    problems: list[str] = []

    def err(msg: str) -> None:
        problems.append(msg)

    if not cells["company"]:
        err("company is empty")
    sector = sectors.get(cells["sector"].casefold())
    if sector is None:
        err(f"sector {cells['sector']!r} is not one of {sorted(sectors.values())}")
    fy = None
    try:
        fy = normalize_fy(cells["fy"])
    except FiscalYearError as exc:
        err(str(exc))
    code = (
        cells["indicator"]
        if cells["indicator"] in by_code
        else by_label.get(cells["indicator"].casefold())
    )
    if code is None:
        err(f"indicator {cells['indicator']!r} is not in config/indicators.yaml")

    value = None
    if not _NUMBER.match(cells["value"]):
        err(f"value {cells['value']!r} is not a plain number")
    else:
        try:
            value = Decimal(cells["value"].replace(",", ""))
        except InvalidOperation:
            err(f"value {cells['value']!r} is not a number")

    if code is not None:
        try:
            factor_to_canonical(cells["unit"], by_code[code].unit)
        except UnitError as exc:
            err(str(exc))

    boundary = None
    if cells["boundary"]:
        boundary = cells["boundary"].casefold()
        if boundary not in vocab.BOUNDARIES:
            err(f"boundary {cells['boundary']!r} must be one of {list(vocab.BOUNDARIES)}")
    assured = None
    if cells["assured"]:
        flag = cells["assured"].casefold()
        if flag in _TRUE:
            assured = True
        elif flag in _FALSE:
            assured = False
        else:
            err(f"assured {cells['assured']!r} must be true/false (yes/no)")
    if not cells["source_url"]:
        err("source_url is required (provenance)")
    if not cells["page_ref"]:
        err("page_ref is required (provenance)")

    for message in problems:
        parsed.issues.append(Issue(line, "error", message))
    if problems:
        return None
    return ManualRow(
        line=line,
        company=cells["company"],
        nse_symbol=cells["nse_symbol"],
        sector=sector,
        fy=fy,
        indicator=code,
        value=value,
        unit=cells["unit"],
        boundary=boundary,
        assured=assured,
        source_url=cells["source_url"],
        page_ref=cells["page_ref"],
    )


def _cross_row_checks(parsed: ParsedFile) -> None:
    seen: dict[tuple[str, str, str], int] = {}
    names_by_key: dict[str, set[str]] = defaultdict(set)
    sector_by_key: dict[str, set[str]] = defaultdict(set)
    symbols_by_name: dict[str, set[str]] = defaultdict(set)
    per_report: dict[tuple[str, str], list[ManualRow]] = defaultdict(list)

    for row in parsed.rows:
        slot = (row.company_key, row.fy, row.indicator)
        if slot in seen:
            parsed.issues.append(
                Issue(
                    row.line,
                    "error",
                    f"duplicate value for {row.company} {row.fy} {row.indicator} "
                    f"(first at line {seen[slot]})",
                )
            )
        else:
            seen[slot] = row.line
        names_by_key[row.company_key].add(row.company)
        sector_by_key[row.company_key].add(row.sector)
        if row.nse_symbol:
            symbols_by_name[row.company.casefold()].add(row.nse_symbol.upper())
        per_report[(row.company_key, row.fy)].append(row)

    for key, names in names_by_key.items():
        if len({n.casefold() for n in names}) > 1:
            parsed.issues.append(Issue(0, "error", f"{key}: several company names {sorted(names)}"))
    for key, sectors in sector_by_key.items():
        if len(sectors) > 1:
            parsed.issues.append(
                Issue(0, "error", f"{key}: appears in several sectors {sorted(sectors)}")
            )
    for name, symbols in symbols_by_name.items():
        if len(symbols) > 1:
            parsed.issues.append(
                Issue(0, "error", f"{name!r}: several NSE symbols {sorted(symbols)}")
            )
    for (key, fy), rows in per_report.items():
        for attr in ("boundary", "assured"):
            distinct = {getattr(r, attr) for r in rows if getattr(r, attr) is not None}
            if len(distinct) > 1:
                parsed.issues.append(
                    Issue(
                        rows[0].line,
                        "error",
                        f"{key} {fy}: conflicting {attr} values {sorted(map(str, distinct))}",
                    )
                )


# ----------------------------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------------------------
@dataclass
class LoadSummary:
    companies_created: int = 0
    reports_touched: int = 0
    values_written: int = 0
    warnings: list[Issue] = field(default_factory=list)


def assign_codes(
    taken: set[str], new_keys: list[str], sector_code: str, master_seed: int
) -> dict[str, str]:
    """Masked codes for new companies of one sector.

    Order comes from a seeded hash of the company key, never from market cap or input order, so the
    number in a code carries no size information. Existing codes are never changed.
    """
    used = {int(c.split("-")[1]) for c in taken}
    ordered = sorted(
        new_keys, key=lambda k: hashlib.sha256(f"{master_seed}|{k}".encode()).hexdigest()
    )
    out, n = {}, 0
    for key in ordered:
        n += 1
        while n in used:
            n += 1
        out[key] = f"{sector_code}-{n:02d}"
    return out


def load_manual(
    session: Session,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    path: Path,
    *,
    retrieved_on: date | None = None,
    synthetic: bool = False,
) -> LoadSummary:
    """Validate then load a manual-entry CSV. Raises IngestError (loading nothing) on any error."""
    parsed = parse_manual_csv(path, cfg, indicators)
    if not parsed.ok:
        raise IngestError("\n".join(str(i) for i in parsed.errors))

    sector_rows = {s.name: s for s in session.scalars(select(Sector))}
    sector_code = {s.name: s.code for s in cfg.study.sectors}
    if not all(name in sector_rows for name in sector_code):
        raise LookupError("sectors not registered: run `gauge init-db` first")

    existing = {}
    for c in session.scalars(select(Company)):
        existing[company_key(c.nse_symbol or "", c.real_name)] = c
        existing[c.real_name.strip().casefold()] = c

    summary = LoadSummary(warnings=[i for i in parsed.issues if i.level == "warning"])
    first_row: dict[str, ManualRow] = {}
    for row in parsed.rows:
        first_row.setdefault(row.company_key, row)

    new_by_sector: dict[str, list[str]] = defaultdict(list)
    for key, row in first_row.items():
        if key not in existing and row.company.strip().casefold() not in existing:
            new_by_sector[row.sector].append(key)
    codes: dict[str, str] = {}
    for sector_name, keys in new_by_sector.items():
        sector = sector_rows[sector_name]
        taken = {
            c for c in session.scalars(select(Company.code).where(Company.sector_id == sector.id))
        }
        codes.update(assign_codes(taken, keys, sector_code[sector_name], cfg.runs.master_seed))

    companies: dict[str, Company] = {}
    for key, row in first_row.items():
        company = existing.get(key) or existing.get(row.company.strip().casefold())
        if company is None:
            company = Company(
                code=codes[key],
                real_name=row.company,
                nse_symbol=row.nse_symbol or None,
                sector_id=sector_rows[row.sector].id,
                selection_status="included" if synthetic else "candidate",
                is_synthetic=synthetic,
            )
            session.add(company)
            summary.companies_created += 1
        elif company.sector_id != sector_rows[row.sector].id:
            raise IngestError(f"{row.company}: already stored under a different sector")
        companies[key] = company
    session.flush()

    source_file = _display_path(path, cfg.root)
    by_report: dict[tuple[str, str], list[ManualRow]] = defaultdict(list)
    for row in parsed.rows:
        by_report[(row.company_key, row.fy)].append(row)

    for (key, fy), rows in by_report.items():
        company = companies[key]
        report = session.scalar(
            select(Report).where(Report.company_id == company.id, Report.fy == fy)
        )
        if report is None:
            report = Report(company_id=company.id, fy=fy, entry_method="manual")
            session.add(report)
        urls = {r.source_url for r in rows}
        report.boundary = next((r.boundary for r in rows if r.boundary), None)
        report.assured = next((r.assured for r in rows if r.assured is not None), None)
        report.source_url = urls.pop() if len(urls) == 1 else None
        report.source_file, report.file_sha256 = source_file, parsed.sha256
        report.retrieved_on = retrieved_on
        report.entry_method = "synthetic" if synthetic else "manual"
        session.flush()
        summary.reports_touched += 1

        stored = {
            v.indicator: v
            for v in session.scalars(
                select(IndicatorValue).where(IndicatorValue.report_id == report.id)
            )
        }
        for r in rows:
            iv = stored.get(r.indicator)
            if iv is None:
                iv = IndicatorValue(report_id=report.id, indicator=r.indicator)
                session.add(iv)
            iv.value, iv.unit = r.value, r.unit  # as reported
            iv.original_value = iv.original_unit = None  # not yet standardized
            iv.source_url, iv.page_ref = r.source_url, r.page_ref
            iv.verified = iv.verification_note = None
            summary.values_written += 1
    session.flush()
    return summary


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
