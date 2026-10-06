"""verify-sample (spec §6.4): a seeded sample of stored values to confirm against the filing PDF.

Sampling is stratified by company (each contributes the same share of its own values, rounded up),
so no company can be missed by chance. Where a PDF is on file, the value is searched for in its
text as a number token (Indian or Western digit grouping): a hit gives the page to look at, but
only a human decision, recorded with `record_results`, marks a value verified. A miss is normal
when the PDF states the value in another unit (e.g. petajoules for terajoules), so it asks for a
human look instead of counting as an error.
"""

from __future__ import annotations

import csv
import dataclasses
import math
import random
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.db.models import Company, IndicatorValue, Report

MIN_DIGITS = 4  # shorter numbers match too many tokens to say anything
_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?")

COLUMNS = [
    "item_id",
    "company_code",
    "company",
    "nse_symbol",
    "fy",
    "indicator",
    "value_as_filed",
    "unit_as_filed",
    "xbrl_element",
    "source_xml",
    "pdf",
    "auto_check",
    "human_result",
    "human_note",
]


@dataclass(frozen=True)
class SampleItem:
    item_id: int  # indicator_value.id
    company_code: str
    company: str
    nse_symbol: str
    fy: str
    indicator: str
    value: Decimal
    unit: str
    element: str
    source_xml: str
    pdf: str  # relative path of the PDF to check, "" if none on file
    auto_check: str = ""


def as_filed(iv: IndicatorValue) -> tuple[Decimal, str]:
    """The value and unit exactly as the filing states them. After `standardize`, `value`/`unit`
    hold the converted figure and the as-filed pair moves to `original_*`; the PDF shows the
    latter."""
    if iv.original_value is not None and iv.original_unit is not None:
        return iv.original_value, iv.original_unit
    return iv.value, iv.unit


def _plain(value: Decimal) -> str:
    """Digits as a PDF would print them without grouping: 88884246, 486.6 (no trailing zeros)."""
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def number_tokens(page_text: str) -> set[str]:
    """Every number on a page with grouping commas removed (1,88,42,244 and 18,842,244 alike)."""
    out = set()
    for tok in _TOKEN.findall(page_text):
        plain = tok.replace(",", "")
        out.add(plain.rstrip("0").rstrip(".") if "." in plain else plain)
    return out


def find_in_pages(pages: list[str], value: Decimal) -> list[int]:
    """1-based pages whose text contains `value` as a number token; empty if too short to judge."""
    target = _plain(abs(value))
    if len(target.replace(".", "")) < MIN_DIGITS:
        return []
    return [i for i, text in enumerate(pages, start=1) if target in number_tokens(text)]


def draw_sample(
    session: Session, root: Path, *, fraction: float = 0.10, seed: int = 42
) -> list[SampleItem]:
    """Stratified by company, seeded; real (non-synthetic) companies only."""
    pdf_dir = root / "data" / "raw" / "pdf"
    items: list[SampleItem] = []
    companies = session.scalars(select(Company).where(~Company.is_synthetic).order_by(Company.code))
    for company in companies:
        rows = session.execute(
            select(IndicatorValue, Report)
            .join(Report, Report.id == IndicatorValue.report_id)
            .where(Report.company_id == company.id)
            .order_by(Report.fy, IndicatorValue.indicator)
        ).all()
        if not rows:
            continue
        k = math.ceil(len(rows) * fraction)
        picked = random.Random(f"{seed}|{company.code}").sample(rows, k)
        for iv, report in sorted(picked, key=lambda r: (r[1].fy, r[0].indicator)):
            source = report.source_file or ""
            m = re.search(r"_(FY\d{4}-\d{2})", source)
            pdf = (
                pdf_dir / f"{company.nse_symbol}_{m.group(1)}.pdf"
                if m and company.nse_symbol
                else None
            )
            items.append(
                SampleItem(
                    item_id=iv.id,
                    company_code=company.code,
                    company=company.real_name,
                    nse_symbol=company.nse_symbol or "",
                    fy=report.fy,
                    indicator=iv.indicator,
                    value=as_filed(iv)[0],
                    unit=as_filed(iv)[1],
                    element=(iv.page_ref or "").split(" [")[0],
                    source_xml=source,
                    pdf=pdf.relative_to(root).as_posix()
                    if pdf is not None and pdf.is_file()
                    else "",
                )
            )
    return items


def auto_check(items: list[SampleItem], root: Path) -> list[SampleItem]:
    """Search each item's PDF (read once per PDF) and fill `auto_check`."""
    from pypdf import PdfReader

    cache: dict[str, list[str]] = {}
    out = []
    for it in items:
        if not it.pdf:
            out.append(dataclasses.replace(it, auto_check="no PDF on file"))
            continue
        if it.pdf not in cache:
            cache[it.pdf] = [p.extract_text() or "" for p in PdfReader(root / it.pdf).pages]
        pages = find_in_pages(cache[it.pdf], it.value)
        if pages:
            note = f"found on page(s) {', '.join(map(str, pages[:5]))}"
        elif len(_plain(abs(it.value)).replace(".", "")) < MIN_DIGITS:
            note = "number too short to match automatically"
        else:
            note = "not found as printed (PDF may use another unit)"
        out.append(dataclasses.replace(it, auto_check=note))
    return out


def write_csv(items: list[SampleItem], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for it in items:
            writer.writerow(
                {
                    "item_id": it.item_id,
                    "company_code": it.company_code,
                    "company": it.company,
                    "nse_symbol": it.nse_symbol,
                    "fy": it.fy,
                    "indicator": it.indicator,
                    "value_as_filed": _plain(it.value),
                    "unit_as_filed": it.unit,
                    "xbrl_element": it.element,
                    "source_xml": it.source_xml,
                    "pdf": it.pdf,
                    "auto_check": it.auto_check,
                    "human_result": "",
                    "human_note": "",
                }
            )


@dataclass
class RecordSummary:
    ok: int = 0
    error: int = 0
    pending: int = 0

    @property
    def error_rate(self) -> float | None:
        done = self.ok + self.error
        return self.error / done if done else None


def record_results(
    session: Session, path: Path, *, accept_auto_found: bool = False
) -> RecordSummary:
    """Store the human column of a filled-in sample CSV: `ok` or `error` (with a note).

    With `accept_auto_found`, a blank row whose auto check says "found on page" is recorded as ok.
    """
    summary = RecordSummary()
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            result = (row.get("human_result") or "").strip().lower()
            if (
                not result
                and accept_auto_found
                and (row.get("auto_check") or "").startswith("found on")
            ):
                result, row["human_note"] = (
                    "ok",
                    (row.get("human_note") or "") + " (auto: " + row["auto_check"] + ")",
                )
            if result not in ("ok", "error"):
                summary.pending += 1
                continue
            iv = session.get(IndicatorValue, int(row["item_id"]))
            if iv is None:
                raise LookupError(f"indicator_value {row['item_id']} not found")
            try:
                if Decimal(row["value_as_filed"]) != as_filed(iv)[0]:
                    raise ValueError(
                        f"item {row['item_id']}: CSV value {row['value_as_filed']} "
                        "no longer matches the database"
                    )
            except InvalidOperation as exc:
                raise ValueError(f"item {row['item_id']}: unreadable value") from exc
            iv.verified = result == "ok"
            iv.verification_note = (row.get("human_note") or "").strip() or None
            summary.ok += result == "ok"
            summary.error += result == "error"
    session.flush()
    return summary
