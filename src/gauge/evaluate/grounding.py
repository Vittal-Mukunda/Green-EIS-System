"""Grounding (spec §5): do the numbers in a justification come from the evidence the model was shown?

A *claim* is a clause of the justification that contains a number or names an indicator or KPI by its
printed label. Numbers are extracted with regular expressions and compared, after unit normalisation,
with the values printed in THAT model's prompt for THAT company and condition (so a trend value quoted
under C1, where no trend was shown, is unsupported). The labels are rule-based and deliberately simple;
non-numeric claims are only queued for the human annotators. No model judges another model.

Numeric claim status:
  supported    every number matches, within 1%, a printed value of a named indicator (or, when no
               indicator is named, of any indicator of that company);
  wrong        a number matches a printed value only of a DIFFERENT indicator (misattribution), or
               misses a printed value of the named indicator by 1% to 10% (a misquote);
  unsupported  anything else: derived, invented or otherwise not traceable to the printed values.
A clause with several numbers takes its worst status. Small bare integers (1-10, no decimal point, no
percent sign), fiscal-year tokens and "Scope 1/2" are not numeric claims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig
from gauge.db.models import Annotation, Claim
from gauge.render.evidence import CompanyEvidence, Evidence
from gauge.rules.t2 import T2Rule

TOLERANCE = Decimal("0.01")
NEAR_MISS = Decimal("0.10")
UNIT_FACTORS = {
    "INR_crore": Decimal(10**7)
}  # revenue is printed in crore; claims may say lakh/million
MULTIPLIERS = {
    "thousand": Decimal(10**3),
    "k": Decimal(10**3),
    "million": Decimal(10**6),
    "mn": Decimal(10**6),
    "m": Decimal(10**6),
    "billion": Decimal(10**9),
    "bn": Decimal(10**9),
    "lakh": Decimal(10**5),
    "lakhs": Decimal(10**5),
    "crore": Decimal(10**7),
    "crores": Decimal(10**7),
    "cr": Decimal(10**7),
}
SEVERITY = {"supported": 0, "unsupported": 1, "wrong": 2}

_FY_RE = re.compile(
    r"\bFY\s?\d{2,4}(?:\s?[-/]\s?\d{2,4})?|\b20\d{2}\s?[-/]\s?\d{2}\b", re.IGNORECASE
)
_SCOPE_RE = re.compile(r"\bScope\s*[12](?:\s*(?:\+|and|&|/)\s*[12])?", re.IGNORECASE)
_NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<pct>\s?(?:%|percent\b|per\s?cent\b))?"
    r"(?:\s?(?P<mult>thousand|k|million|mn|m|billion|bn|lakhs?|crores?|cr)\b)?",
    re.IGNORECASE,
)
_CLAUSE_SPLIT_RE = re.compile(r"[.;!?](?=\s|$)")


@dataclass(frozen=True)
class ClaimedNumber:
    text: str
    value: Decimal
    multiplier: Decimal | None
    percent: bool


@dataclass(frozen=True)
class Shown:
    """One number printed in a prompt: which indicator/KPI it belongs to, and its unit factor."""

    code: str
    value: Decimal
    unit_factor: Decimal = Decimal(1)


@dataclass(frozen=True)
class ClaimResult:
    clause_index: int
    clause_text: str
    claim_type: str  # numeric | indicator_only
    indicator_code: str | None
    claimed_value: Decimal | None
    matched_value: Decimal | None
    status: str


# ---- extraction --------------------------------------------------------------------------------
def split_clauses(text: str) -> list[str]:
    return [c.strip() for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]


def extract_numbers(clause: str) -> list[ClaimedNumber]:
    cleaned = _SCOPE_RE.sub(" ", _FY_RE.sub(" ", clause))
    found = []
    for m in _NUMBER_RE.finditer(cleaned):
        raw = m.group("num")
        try:
            value = Decimal(raw.replace(",", ""))
        except InvalidOperation:  # pragma: no cover - the regex only yields valid numbers
            continue
        percent = m.group("pct") is not None
        small_bare_integer = "." not in raw and "," not in raw and value <= 10 and not percent
        if small_bare_integer and m.group("mult") is None:
            continue
        mult = MULTIPLIERS.get((m.group("mult") or "").lower())
        found.append(ClaimedNumber(m.group(0).strip(), value, mult, percent))
    return found


def mention_pattern(indicators: IndicatorsConfig) -> list[tuple[re.Pattern, str]]:
    """(pattern, code) for every printed label, longest label first so that 'Emissions intensity
    (Scope 1+2)' is found before a shorter label could match inside it."""
    labels = [(i.label, i.code) for i in indicators.indicators] + [
        (k.label, k.code) for k in indicators.kpis
    ]
    # "Emissions intensity (Scope 1+2)" is often written without the parenthesis
    labels += [(label.split(" (")[0], code) for label, code in labels if " (" in label]
    labels.sort(key=lambda item: -len(item[0]))
    return [
        (re.compile(rf"(?<![\w]){re.escape(label)}(?![\w])", re.IGNORECASE), code)
        for label, code in labels
    ]


def mentioned_codes(clause: str, patterns: list[tuple[re.Pattern, str]]) -> list[str]:
    remaining, codes = clause, []
    for pattern, code in patterns:
        if pattern.search(remaining):
            codes.append(code)
            remaining = pattern.sub(
                " ", remaining
            )  # a longer label hides the shorter one inside it
    return codes


# ---- matching ----------------------------------------------------------------------------------
def _close(claimed: Decimal, shown: Decimal, tolerance: Decimal) -> bool:
    if shown == 0:
        return abs(claimed) <= Decimal("1e-9")
    return abs(claimed - shown) <= tolerance * abs(shown)


def _claim_matches(number: ClaimedNumber, shown: Shown, tolerance: Decimal) -> bool:
    """Compare in base units: a claim with a multiplier word ("6.4 million") is x * multiplier; one
    without is read in the unit the value was printed in."""
    claimed_base = number.value * (number.multiplier or shown.unit_factor)
    return _close(claimed_base, shown.value * shown.unit_factor, tolerance)


def label_number(
    number: ClaimedNumber, named: list[str], shown: list[Shown]
) -> tuple[str, Decimal | None]:
    """(status, matched printed value) for one number."""
    pool = [s for s in shown if s.code in named] if named else shown
    for s in pool:
        if _claim_matches(number, s, TOLERANCE):
            return "supported", s.value
    if named:
        others = [s for s in shown if s.code not in named]
        for s in others:
            if _claim_matches(number, s, TOLERANCE):
                return "wrong", s.value  # misattributed to the named indicator
        for s in pool:
            if _claim_matches(number, s, NEAR_MISS):
                return "wrong", s.value  # a misquote of the named indicator
    return "unsupported", None


def label_clause(
    index: int,
    clause: str,
    patterns: list[tuple[re.Pattern, str]],
    shown: list[Shown],
) -> ClaimResult | None:
    numbers = extract_numbers(clause)
    named = mentioned_codes(clause, patterns)
    if not numbers and not named:
        return None
    if not numbers:
        return ClaimResult(
            index, clause, "indicator_only", named[0], None, None, "pending_annotation"
        )
    worst, claimed, matched = "supported", numbers[0].value, None
    first = True
    for n in numbers:
        status, match = label_number(n, named, shown)
        if first or SEVERITY[status] > SEVERITY[worst]:
            worst, claimed, matched = status, n.value, match
            first = False
    return ClaimResult(
        index, clause, "numeric", named[0] if named else None, claimed, matched, worst
    )


def label_justification(
    text: str, patterns: list[tuple[re.Pattern, str]], shown: list[Shown]
) -> list[ClaimResult]:
    out = []
    for index, clause in enumerate(split_clauses(text)):
        result = label_clause(index, clause, patterns, shown)
        if result is not None:
            out.append(result)
    return out


# ---- what was shown ------------------------------------------------------------------------------
def shown_values(
    ce: CompanyEvidence,
    evidence: Evidence,
    t2_rule: T2Rule,
    indicators: IndicatorsConfig,
    condition: str,
) -> list[Shown]:
    """Every number printed for this company in the prompt of `condition`."""
    out: list[Shown] = []
    for i in indicators.indicators:
        value = ce.indicators.get(i.code)
        if value is not None:
            out.append(Shown(i.code, value, UNIT_FACTORS.get(i.unit, Decimal(1))))
    for k in indicators.kpis:
        value = ce.kpis.get(k.code)
        if value is not None:
            out.append(Shown(k.code, value))
    for kpi, cuts in t2_rule.cut_points.get(ce.sector, {}).items():  # printed under both conditions
        out += [Shown(kpi, cuts.p33), Shown(kpi, cuts.p67)]
    if condition == "C2":
        for kpi, years in ce.trend.items():
            out += [Shown(kpi, v) for v in years.values() if v is not None]
        for kpi, stats in evidence.sectors[ce.sector].stats.items():
            out += [Shown(kpi, stats[name]) for name in ("median", "p25", "p75")]
    return out


# ---- storing -------------------------------------------------------------------------------------
class ClaimStoreError(RuntimeError):
    """Claims with human annotations would be changed or removed by a re-evaluation."""


def store_claims(session: Session, judgment_id: int, results: list[ClaimResult]) -> int:
    """Upsert the claims of one judgment by clause index. A claim whose clause text is unchanged
    keeps its row (and so its annotations); a changed or vanished claim is replaced only if nothing
    has been annotated on it."""
    existing = {
        c.clause_index: c
        for c in session.scalars(select(Claim).where(Claim.judgment_id == judgment_id))
    }
    keep = set()
    for r in results:
        row = existing.get(r.clause_index)
        if row is not None and row.clause_text != r.clause_text:
            _remove(session, row)
            row = None
        if row is None:
            row = Claim(judgment_id=judgment_id, clause_index=r.clause_index)
            session.add(row)
        row.clause_text, row.claim_type, row.indicator_code = (
            r.clause_text,
            r.claim_type,
            r.indicator_code,
        )
        row.claimed_value, row.matched_value, row.status = (
            r.claimed_value,
            r.matched_value,
            r.status,
        )
        keep.add(r.clause_index)
    for index, row in existing.items():
        if index not in keep:
            _remove(session, row)
    session.flush()
    return len(results)


def _remove(session: Session, claim: Claim) -> None:
    annotated = session.scalar(select(Annotation.id).where(Annotation.claim_id == claim.id))
    if annotated is not None:
        raise ClaimStoreError(
            f"claim {claim.id} ('{claim.clause_text[:40]}...') has human annotations and would be "
            "changed by this evaluation; resolve them first"
        )
    session.delete(claim)
    session.flush()
