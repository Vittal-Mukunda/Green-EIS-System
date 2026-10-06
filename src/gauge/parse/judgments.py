"""Validate a reply company by company and store the judgments.

A reply can be partly good: one malformed object must not discard the other companies. Every
company the run's prompt listed gets exactly one `judgment` row, `ok` or `parse_failure` with the
reason. A response is never "fixed" here: a rating of "3" or 3.0, an out-of-range value, an unknown
extra key, a justification over 40 words, or a `top_drivers` name that is not in the printed list is
a failure that the single repair attempt (parse/repair.py) and the parse-failure rate are meant to
expose. Only case and spacing of a driver name are normalised to the printed spelling.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.config import StudyConfig
from gauge.db.models import Company, Judgment, Run, RunCompanyPosition
from gauge.parse.extract import Extraction, extract_json_array
from gauge.schemas import CompanyJudgment


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


@dataclass
class CompanyResult:
    code: str
    judgment: CompanyJudgment | None = None
    error: str | None = None


@dataclass
class ResponseCheck:
    extraction: Extraction
    results: dict[str, CompanyResult]  # expected company code -> result
    unexpected: list[str] = field(
        default_factory=list
    )  # codes in the reply that were not asked for
    notes: list[str] = field(default_factory=list)

    @property
    def bad(self) -> list[CompanyResult]:
        return [r for r in self.results.values() if r.judgment is None]

    @property
    def ok(self) -> bool:
        return not self.bad


def _error_text(exc: ValidationError) -> str:
    parts = []
    for e in exc.errors():
        where = ".".join(str(p) for p in e["loc"]) or "object"
        parts.append(f"{where}: {e['msg']}")
    return "; ".join(parts)


def validate_response(
    text: str, expected_codes: Sequence[str], driver_labels: Sequence[str]
) -> ResponseCheck:
    """Check `text` against the companies the prompt listed. Pure: touches no database."""
    extraction = extract_json_array(text)
    results = {code: CompanyResult(code) for code in expected_codes}
    check = ResponseCheck(extraction, results)
    if extraction.items is None:
        for r in results.values():
            r.error = extraction.error or "no JSON array"
        return check

    canonical = {_norm(label): label for label in driver_labels}
    seen: dict[str, int] = {}
    valid: dict[str, CompanyJudgment] = {}
    invalid: dict[str, str] = {}
    for index, item in enumerate(extraction.items):
        code = item.get("company_code") if isinstance(item, dict) else None
        label = code if isinstance(code, str) else f"element {index}"
        try:
            judgment = CompanyJudgment.model_validate(item)
        except ValidationError as exc:
            if not isinstance(code, str):  # no usable company code: it cannot be matched to anyone
                reason = _error_text(exc)
                check.notes.append(f"element {index} has no usable company_code: {reason}")
                continue
            invalid[label] = _error_text(exc)
            seen[label] = seen.get(label, 0) + 1
            continue
        names = [canonical.get(_norm(d)) for d in judgment.top_drivers]
        if None in names:
            bad = [d for d, n in zip(judgment.top_drivers, names, strict=True) if n is None]
            invalid[judgment.company_code] = f"top_drivers: not a listed name: {bad}"
        elif len(set(names)) != len(names):
            invalid[judgment.company_code] = "top_drivers: names are not distinct"
        else:
            valid[judgment.company_code] = judgment.model_copy(update={"top_drivers": names})
        seen[judgment.company_code] = seen.get(judgment.company_code, 0) + 1

    for code, result in results.items():
        times = seen.get(code, 0)
        if times == 0:
            result.error = "the company is missing from the reply"
        elif times > 1:
            result.error = f"the company appears {times} times in the reply"
        elif code in valid:
            result.judgment = valid[code]
        else:
            result.error = invalid[code]
    check.unexpected = sorted(code for code in seen if code not in results)
    if check.unexpected:
        check.notes.append(f"codes not asked for were ignored: {check.unexpected}")
    return check


# ---- database ----------------------------------------------------------------------------------
def run_company_codes(session: Session, run: Run) -> list[str]:
    """The company codes in the run's prompt, in prompt order."""
    rows = session.execute(
        select(Company.code)
        .join(RunCompanyPosition, RunCompanyPosition.company_id == Company.id)
        .where(RunCompanyPosition.run_id == run.id)
        .order_by(RunCompanyPosition.position)
    )
    return [code for (code,) in rows]


def read_raw(cfg: StudyConfig, run: Run) -> str:
    """The raw reply, from its file (written before anything was parsed); the logged stdout is only
    a fallback when the file is gone."""
    if run.raw_path:
        path = Path(cfg.root) / run.raw_path
        if path.is_file():
            with path.open(encoding="utf-8", newline="") as fh:
                return fh.read()
    return run.stdout or ""


def store_judgments(
    session: Session,
    run: Run,
    check: ResponseCheck,
    *,
    only: Sequence[str] | None = None,
    repaired_from: dict[str, str] | None = None,
) -> None:
    """Write one judgment row per company (or per `only`) for `run`.

    `repaired_from` maps a code to the first-attempt error it replaces: those rows are stored with
    that text in `parse_error`, which is how a repaired judgment stays recognisable.
    """
    by_code = {c.code: c.id for c in session.scalars(select(Company))}
    existing = {
        j.company_id: j for j in session.scalars(select(Judgment).where(Judgment.run_id == run.id))
    }
    for code, result in check.results.items():
        if only is not None and code not in only:
            continue
        company_id = by_code[code]
        row = existing.get(company_id)
        if row is None:
            row = Judgment(run_id=run.id, company_id=company_id, parse_status="parse_failure")
            session.add(row)
        j = result.judgment
        if j is None:
            row.parse_status, row.parse_error = "parse_failure", result.error
            row.t2_class = row.t3_rating = row.t3_confidence = None
            row.top_drivers = row.justification = row.insufficient_evidence = None
            continue
        row.parse_status = "ok"
        row.parse_error = (
            f"repaired: {repaired_from[code]}" if repaired_from and code in repaired_from else None
        )
        row.t2_class, row.t3_rating, row.t3_confidence = j.t2_class, j.t3_rating, j.t3_confidence
        row.top_drivers, row.justification = list(j.top_drivers), j.justification
        row.insufficient_evidence = j.insufficient_evidence
    session.flush()


@dataclass(frozen=True)
class ParseOutcome:
    run_id: str
    n_ok: int
    n_bad: int
    method: str
    errors: dict[str, str]


def parse_run(
    session: Session, cfg: StudyConfig, run: Run, driver_labels: Sequence[str]
) -> ParseOutcome:
    """First parse of a successful, non-repair run: store judgments, set `run.parse_status`."""
    codes = run_company_codes(session, run)
    check = validate_response(read_raw(cfg, run), codes, driver_labels)
    store_judgments(session, run, check)
    run.parse_status = "ok" if check.ok else "parse_failure"
    session.flush()
    return ParseOutcome(
        run.run_id,
        len(check.results) - len(check.bad),
        len(check.bad),
        check.extraction.method,
        {r.code: r.error or "" for r in check.bad},
    )
