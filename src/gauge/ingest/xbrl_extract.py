"""Extract our nine indicators from a BRSR XBRL filing, with an explicit unit decision per value.

What a survey of 20 real filings (FY2025-26, 2026-10-02) showed, and what this module does:

* Every filing carries the current and the previous fiscal year as company-level facts (contexts
  with no dimensions and a 12-month April-March period). Both years are extracted.
* Unit labels do not determine the unit. `Non-SI:MtCO2e` is tonnes in one filing and million
  tonnes in another; `iso4217:INR` revenue is in rupees, crore, million or thousand. An ambiguous
  label is resolved by a stated rule (zero; a magnitude that rules one reading out) or by an
  override that cites evidence. Otherwise the value is left **unresolved**: reported, never guessed.
* Filings report their own per-rupee intensities, but filers scale the denominator like the
  revenue, so those cannot reveal a scaled revenue. They only check that a numerator and its
  absolute value share a unit.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from gauge.ingest.manual import Issue
from gauge.ingest.xbrl import Instance, read_instance
from gauge.ingest.xbrl_map import IndicatorMap, Override, XbrlMapping
from gauge.standardize.units import UnitError, factor_to_canonical

SCALE_NAMES = {
    Decimal("1e3"): "thousand",
    Decimal("1e5"): "lakh",
    Decimal("1e6"): "million",
    Decimal("1e7"): "crore",
}
CANONICAL = {
    "revenue_from_operations": "INR_crore",
    "energy_total": "GJ", "energy_renewable": "GJ",
    "scope1_emissions": "tCO2e", "scope2_emissions": "tCO2e",
    "water_withdrawal": "kL", "water_consumption": "kL",
    "waste_generated": "t", "waste_recovered": "t",
}  # fmt: skip


@dataclass(frozen=True)
class Resolved:
    indicator: str
    element: str
    context_id: str
    value: Decimal
    unit: str  # our spelling, accepted by standardize
    raw_label: str  # the XBRL unit measure as filed
    basis: str  # label | zero | magnitude | override
    evidence: str = ""


@dataclass
class YearData:
    fy: str
    start: date
    end: date
    current: bool
    values: dict[str, Resolved] = field(default_factory=dict)
    unresolved: dict[str, str] = field(default_factory=dict)  # indicator -> reason (with hint)
    notes: list[tuple[str, str]] = field(default_factory=list)  # (rule, message): quality notes

    @property
    def complete(self) -> bool:
        return not self.unresolved


@dataclass
class Filing:
    path: Path
    sha256: str
    schema_ref: str | None
    isin: str | None = None
    name: str | None = None
    boundary: str | None = None
    assured: bool | None = None
    assurance_note: str | None = None
    years: list[YearData] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def refused(self) -> bool:
        return any(i.level == "error" for i in self.issues)


def fy_label(start_year: int) -> str:
    return f"FY{start_year}-{(start_year + 1) % 100:02d}"


def resolve_unit(
    spec: IndicatorMap, raw_label: str, value: Decimal, mapping: XbrlMapping
) -> tuple[str | None, str, str]:
    """(unit, basis, reason). unit is None when the label does not settle it and no rule applies."""
    if raw_label not in mapping.unit_labels:
        return None, "", f"unit label {raw_label!r} is not in config/xbrl_mapping.yaml"
    unit = mapping.unit_labels[raw_label]
    if unit is not None:
        return unit, "label", ""
    amb = mapping.ambiguity
    if spec.kind == "emissions":
        if value == 0:
            return amb.emissions_tonnes_unit, "zero", ""
        if value >= amb.emissions_label_tonnes_min:
            return amb.emissions_tonnes_unit, "magnitude", ""
        return (
            None,
            "",
            (
                f"label {raw_label} is ambiguous (tonnes or million tonnes) and {value} is below "
                f"{amb.emissions_label_tonnes_min}"
            ),
        )
    if spec.kind == "currency":
        if amb.revenue_min_inr <= value <= amb.revenue_max_inr:
            return amb.revenue_unit, "magnitude", ""
        return (
            None,
            "",
            (
                f"revenue {value:,} {raw_label} is outside INR {amb.revenue_min_inr:,} to "
                f"{amb.revenue_max_inr:,}, so it is not read as rupees"
            ),
        )
    return None, "", f"label {raw_label} is ambiguous and has no rule for kind {spec.kind}"


def scale_hint(stated: Decimal, anchors: dict[str, Decimal]) -> str:
    """Suggest a revenue scale from Section A fields that happen to be in absolute rupees."""
    for name, anchor in anchors.items():
        if anchor < Decimal("1e10"):
            continue
        for scale, label in SCALE_NAMES.items():
            ratio = anchor / (stated * scale)
            if Decimal("0.8") <= ratio <= Decimal("1.3"):
                return (
                    f" Hint: Section A {name} = {anchor:,} suggests the revenue is in INR {label}."
                )
    return ""


def _resolve_isin(filing: Filing, ident, by_el, cin_to_isin: dict[str, str] | None) -> str | None:
    """The filing's ISIN, or the ISIN joined from its CIN when the taxonomy has no ISIN fact.

    Returns None after recording an error. A CIN is accepted only when `cin_to_isin` maps it,
    and that map is built from filings that state both numbers.
    """
    isin = next((f.value for f in by_el.get(ident.isin, []) if f.value and not f.unit_id), None)
    if isin:
        return isin
    cins = sorted(
        {
            f.value.strip()
            for f in by_el.get(ident.cin, [])
            if f.value and not f.unit_id and f.value.strip()
        }
    )
    if len(cins) > 1:
        filing.issues.append(Issue(0, "error", f"{ident.cin} has conflicting values {cins}"))
        return None
    if len(cins) == 1:
        resolved = (cin_to_isin or {}).get(cins[0])
        if resolved is None:
            filing.issues.append(Issue(0, "error", (
                f"no {ident.isin} fact; {ident.cin} {cins[0]} is not in data/reference/cin_isin.csv"
            )))  # fmt: skip
            return None
        return resolved
    filing.issues.append(
        Issue(0, "error", f"no {ident.isin} fact: cannot tell which company this is")
    )
    return None


def _period(ctx_period: str) -> tuple[date, date] | None:
    if ".." not in ctx_period:
        return None
    a, b = ctx_period.split("..")
    return date.fromisoformat(a), date.fromisoformat(b)


def _is_fiscal_year(start: date, end: date) -> bool:
    return (start.month, start.day) == (4, 1) and end == date(start.year + 1, 3, 31)


def extract_filing(
    path: Path,
    mapping: XbrlMapping,
    overrides: list[Override],
    cin_to_isin: dict[str, str] | None = None,
) -> Filing:
    inst = read_instance(path)
    schema_ref = inst.schema_refs[0] if inst.schema_refs else None
    filing = Filing(path=path, sha256=inst.sha256, schema_ref=schema_ref)
    if schema_ref is None or Path(schema_ref).name not in mapping.schema_refs:
        filing.issues.append(Issue(0, "error", (
            f"taxonomy {schema_ref!r} is not one this mapping has been checked against "
            f"({mapping.schema_refs}); compare it with the taxonomy archive first (V-18)"
        )))  # fmt: skip
        return filing

    by_el: dict[str, list] = {}
    for f in inst.facts:
        by_el.setdefault(f.element.split(":")[-1], []).append(f)

    def text(element: str) -> str | None:
        return next((f.value for f in by_el.get(element, []) if f.value and not f.unit_id), None)

    ident = mapping.identity
    filing.name = text(ident.name)
    filing.isin = _resolve_isin(filing, ident, by_el, cin_to_isin)
    if filing.refused:
        return filing
    boundary_text = text(ident.boundary)
    if boundary_text is None or boundary_text not in mapping.boundary_values:
        filing.issues.append(
            Issue(0, "warning", f"reporting boundary {boundary_text!r} not recognised")
        )
    else:
        filing.boundary = mapping.boundary_values[boundary_text]

    # fiscal-year periods: context ids with no dimensions and a 12-month April-March duration
    periods: dict[tuple[date, date], set[str]] = {}
    for ctx in inst.contexts.values():
        span = None if ctx.dimensions else _period(ctx.period)
        if span is None:
            continue
        if _is_fiscal_year(*span):
            periods.setdefault(span, set()).add(ctx.id)
        else:
            filing.issues.append(
                Issue(0, "warning", f"ignoring non April-March period {ctx.period}")
            )

    def fact_values(element: str, ctx_ids: set[str]) -> list:
        return [f for f in by_el.get(element, []) if f.context_id in ctx_ids]

    years: list[YearData] = []
    for (start, end), ctx_ids in sorted(periods.items(), key=lambda kv: kv[0][1]):
        if not any(fact_values(spec.element, ctx_ids) for spec in mapping.indicators.values()):
            continue  # e.g. the year before the previous one, which only has a few HR facts
        years.append(YearData(fy_label(start.year), start, end, current=False))
    if not years:
        filing.issues.append(Issue(0, "error", "no April-March year with any mapped indicator"))
        return filing
    years[-1].current = True
    filing.years = years

    for year in years:
        ctx_ids = periods[(year.start, year.end)]
        _extract_year(filing, year, ctx_ids, inst, by_el, mapping, overrides)
    _scale_breaks(years, Decimal(str(mapping.ambiguity.yoy_scale_break_ratio)))
    current_ids = periods[(years[-1].start, years[-1].end)]
    _assurance(filing, by_el, current_ids, mapping, text)
    return filing


def _extract_year(filing, year, ctx_ids, inst: Instance, by_el, mapping: XbrlMapping, overrides):
    applicable = {
        code: o
        for o in overrides
        if o.isin == filing.isin and year.fy in o.fy
        for code in o.indicators
    }
    raw_revenue = None
    for code, spec in mapping.indicators.items():
        facts = [f for f in by_el.get(spec.element, []) if f.context_id in ctx_ids]
        if not facts:
            year.unresolved[code] = f"element {spec.element} not reported for {year.fy}"
            continue
        distinct = {f.value for f in facts}
        if len(distinct) > 1:
            year.unresolved[code] = f"{spec.element} has conflicting values {sorted(distinct)}"
            continue
        fact = facts[0]
        try:
            value = Decimal(fact.value)
        except (InvalidOperation, ValueError):
            year.unresolved[code] = f"{spec.element} has no numeric value ({fact.value!r})"
            continue
        label = (
            inst.units[fact.unit_id].measure if fact.unit_id in inst.units else (fact.unit_id or "")
        )
        if code == "revenue_from_operations":
            raw_revenue = value
        override = applicable.get(code)
        if override is not None:
            unit, basis, reason, evidence = override.unit, "override", "", override.evidence
            year.notes.append(
                (
                    "xbrl_override_applied",
                    f"{code}: unit {override.unit!r} by override. Evidence: {override.evidence}",
                )
            )
        else:
            unit, basis, reason = resolve_unit(spec, label, value, mapping)
            evidence = ""
        if unit is None:
            hint = ""
            if code == "revenue_from_operations":
                anchors = {}
                for name in mapping.revenue_anchors:
                    for f in by_el.get(name, []):
                        if f.context_id in ctx_ids:
                            with contextlib.suppress(InvalidOperation):
                                anchors[name] = Decimal(f.value)
                hint = scale_hint(value, anchors)
            year.unresolved[code] = reason + hint
            continue
        year.values[code] = Resolved(
            code, spec.element, fact.context_id, value, unit, label, basis, evidence
        )
    _intensity_checks(year, ctx_ids, inst, by_el, mapping, raw_revenue)


def _intensity_checks(year, ctx_ids, inst, by_el, mapping: XbrlMapping, raw_revenue):
    if raw_revenue in (None, 0):
        return
    for name, check in mapping.intensity_checks.items():
        facts = [f for f in by_el.get(check.intensity, []) if f.context_id in ctx_ids]
        if not facts:
            continue
        try:
            intensity = Decimal(facts[0].value)
        except InvalidOperation:
            continue
        if intensity == 0:
            continue  # rounded to zero in the filing: no information
        numerator = (
            inst.units[facts[0].unit_id].measure if facts[0].unit_id in inst.units else ""
        ).split("/")[0]
        total, labels = Decimal(0), set()
        for code in check.absolute:
            absolute = [
                f
                for f in by_el.get(mapping.indicators[code].element, [])
                if f.context_id in ctx_ids
            ]
            if not absolute:
                break
            total += Decimal(absolute[0].value)
            labels.add(
                inst.units[absolute[0].unit_id].measure if absolute[0].unit_id in inst.units else ""
            )
        else:
            if labels != {numerator}:
                year.notes.append(
                    (
                        "xbrl_intensity_mismatch",
                        f"{name}: intensity numerator unit {numerator!r} differs from "
                        f"absolute unit(s) {sorted(labels)}",
                    )
                )
                continue
            ratio = total / (intensity * raw_revenue)
            if abs(ratio - 1) > Decimal(str(mapping.intensity_tolerance)):
                year.notes.append(
                    (
                        "xbrl_intensity_mismatch",
                        f"{name}: absolute / (reported intensity x revenue) = {ratio:.3f}, "
                        "expected about 1",
                    )
                )


def _scale_breaks(years: list[YearData], bound: Decimal) -> None:
    """Flag an indicator whose two years differ by more than `bound` (a likely scale slip)."""
    if len(years) < 2:
        return
    old, new = years[-2], years[-1]
    for code, a in old.values.items():
        b = new.values.get(code)
        if b is None:
            continue
        try:
            ca = a.value * factor_to_canonical(a.unit, CANONICAL[code])
            cb = b.value * factor_to_canonical(b.unit, CANONICAL[code])
        except UnitError:
            continue
        if ca == 0 or cb == 0:
            continue
        ratio = cb / ca
        if ratio > bound or ratio < 1 / bound:
            new.notes.append(
                ("xbrl_scale_break", f"{code}: {new.fy} / {old.fy} = {ratio:.4g} within one filing")
            )


def _assurance(filing: Filing, by_el, ctx_ids, mapping: XbrlMapping, text) -> None:
    kinds: dict[str, str] = {}
    for group, element in mapping.assurance_groups.items():
        found = [f.value for f in by_el.get(element, []) if f.context_id in ctx_ids and f.value]
        if found:
            kinds[group] = found[0]
    if not kinds:
        return
    provider = text(mapping.identity.assurer_name)
    parts = [f"{g}: {kinds.get(g, 'none')}" for g in mapping.assurance_groups]
    if provider:
        parts.append(f"provider: {provider}")
    filing.assurance_note = "; ".join(parts)
    filing.assured = all(
        kinds.get(g) in mapping.assurance_accepted for g in mapping.assurance_groups
    )
