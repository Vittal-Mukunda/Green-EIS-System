"""Generic XBRL instance reader and inspector.

This deliberately knows no BRSR element names (hard rule 8). It reads any XBRL 2.1 instance into
plain facts, contexts and units, and summarizes them so that the mapping from BRSR elements to our
indicators can be written from real files in Phase 3 (`gauge ingest --inspect-xbrl FILE`).

Filings are untrusted input, so parsing uses defusedxml, which rejects DTDs and entity expansion.
"""

from __future__ import annotations

import csv
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from defusedxml import ElementTree as SafeET

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
_LINK = "http://www.xbrl.org/2003/linkbase"


@dataclass(frozen=True)
class Context:
    id: str
    entity: str  # "scheme|identifier"
    period: str  # "instant:2025-03-31", "2024-04-01..2025-03-31" or "forever"
    dimensions: tuple[str, ...]  # "dimension=member" pairs, sorted; empty = no dimensions


@dataclass(frozen=True)
class Unit:
    id: str
    measure: str  # "iso4217:INR", or "num/den" for a divide unit


@dataclass(frozen=True)
class Fact:
    element: str  # prefixed qname when the prefix is declared, else {namespace}local
    context_id: str
    unit_id: str | None
    decimals: str | None
    precision: str | None
    value: str
    nil: bool


@dataclass
class Instance:
    path: Path
    sha256: str
    namespaces: dict[str, str] = field(default_factory=dict)  # prefix -> uri
    contexts: dict[str, Context] = field(default_factory=dict)
    units: dict[str, Unit] = field(default_factory=dict)
    facts: list[Fact] = field(default_factory=list)
    schema_refs: list[str] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_instance(path: Path) -> Instance:
    """Parse an XBRL instance file. Raises on malformed or DTD/entity-bearing XML."""
    data = path.read_bytes()
    inst = Instance(path=path, sha256=hashlib.sha256(data).hexdigest())
    uri_to_prefix: dict[str, str] = {}

    from io import BytesIO

    for _event, (prefix, uri) in SafeET.iterparse(BytesIO(data), events=("start-ns",)):
        inst.namespaces.setdefault(prefix, uri)
        uri_to_prefix.setdefault(uri, prefix)

    def qname(tag: str) -> str:
        if tag.startswith("{"):
            uri, local = tag[1:].split("}", 1)
            prefix = uri_to_prefix.get(uri)
            return f"{prefix}:{local}" if prefix else tag
        return tag

    root = SafeET.fromstring(data)
    for child in root:
        local = _local(child.tag)
        ns = child.tag[1:].split("}", 1)[0] if child.tag.startswith("{") else ""
        if ns == XBRLI and local == "context":
            ctx = _read_context(child)
            inst.contexts[ctx.id] = ctx
        elif ns == XBRLI and local == "unit":
            unit = _read_unit(child)
            inst.units[unit.id] = unit
        elif ns == _LINK and local == "schemaRef":
            href = next((v for k, v in child.attrib.items() if _local(k) == "href"), None)
            if href:
                inst.schema_refs.append(href)
        elif "contextRef" in child.attrib:
            inst.facts.append(
                Fact(
                    element=qname(child.tag),
                    context_id=child.attrib["contextRef"],
                    unit_id=child.attrib.get("unitRef"),
                    decimals=child.attrib.get("decimals"),
                    precision=child.attrib.get("precision"),
                    value=(child.text or "").strip(),
                    nil=child.attrib.get(f"{{{XSI}}}nil", "").lower() in ("true", "1"),
                )
            )
    return inst


def _text(parent, ns: str, name: str) -> str | None:
    node = parent.find(f"{{{ns}}}{name}")
    return (node.text or "").strip() if node is not None else None


def _read_context(node) -> Context:
    entity = node.find(f"{{{XBRLI}}}entity")
    ident = entity.find(f"{{{XBRLI}}}identifier") if entity is not None else None
    scheme = ident.attrib.get("scheme", "") if ident is not None else ""
    entity_text = f"{scheme}|{(ident.text or '').strip() if ident is not None else ''}"

    period = node.find(f"{{{XBRLI}}}period")
    if period is None:
        period_text = ""
    elif period.find(f"{{{XBRLI}}}instant") is not None:
        period_text = f"instant:{_text(period, XBRLI, 'instant')}"
    elif period.find(f"{{{XBRLI}}}startDate") is not None:
        period_text = f"{_text(period, XBRLI, 'startDate')}..{_text(period, XBRLI, 'endDate')}"
    else:
        period_text = "forever"

    dims = []
    for container in (entity, node.find(f"{{{XBRLI}}}scenario")):
        if container is None:
            continue
        for seg in container.iter():
            local = _local(seg.tag)
            if local == "explicitMember":
                dims.append(f"{seg.attrib.get('dimension', '?')}={(seg.text or '').strip()}")
            elif local == "typedMember":
                inner = "".join((e.text or "").strip() for e in seg.iter() if e is not seg)
                dims.append(f"{seg.attrib.get('dimension', '?')}={inner}")
    return Context(node.attrib.get("id", ""), entity_text, period_text, tuple(sorted(dims)))


def _read_unit(node) -> Unit:
    divide = node.find(f"{{{XBRLI}}}divide")
    if divide is not None:
        num = [
            m.text.strip()
            for m in divide.find(f"{{{XBRLI}}}unitNumerator").iter(f"{{{XBRLI}}}measure")
        ]
        den = [
            m.text.strip()
            for m in divide.find(f"{{{XBRLI}}}unitDenominator").iter(f"{{{XBRLI}}}measure")
        ]
        return Unit(node.attrib.get("id", ""), f"{'*'.join(num)}/{'*'.join(den)}")
    measures = [m.text.strip() for m in node.iter(f"{{{XBRLI}}}measure")]
    return Unit(node.attrib.get("id", ""), "*".join(measures))


# ----------------------------------------------------------------------------------------------
# Inspection output
# ----------------------------------------------------------------------------------------------
def summarize(inst: Instance, *, max_elements: int | None = 40) -> str:
    """Human-readable overview: what a mapping author needs to see first."""
    numeric = [f for f in inst.facts if f.unit_id]
    lines = [
        f"file        {inst.path.name}",
        f"sha256      {inst.sha256}",
        f"schemaRef   {', '.join(inst.schema_refs) or '(none)'}",
        f"facts       {len(inst.facts)} ({len(numeric)} numeric, "
        f"{sum(f.nil for f in inst.facts)} nil)",
        f"contexts    {len(inst.contexts)}   units {len(inst.units)}",
        "",
        "units:",
        *(f"  {u.id:<20} {u.measure}" for u in sorted(inst.units.values(), key=lambda u: u.id)),
        "",
        "contexts (entity | period | dimensions), with fact counts:",
    ]
    per_ctx = Counter(f.context_id for f in inst.facts)
    for ctx in sorted(inst.contexts.values(), key=lambda c: (c.period, c.id)):
        dims = "; ".join(ctx.dimensions) or "-"
        lines.append(f"  {ctx.id:<14} {ctx.period:<24} {dims}  [{per_ctx.get(ctx.id, 0)} facts]")
    unknown = sorted({f.context_id for f in inst.facts} - set(inst.contexts))
    if unknown:
        lines.append(f"  WARNING facts reference undeclared contexts: {unknown}")

    counts = Counter(f.element for f in inst.facts)
    units_by_el: dict[str, set[str]] = defaultdict(set)
    for f in inst.facts:
        if f.unit_id:
            units_by_el[f.element].add(
                inst.units[f.unit_id].measure if f.unit_id in inst.units else f.unit_id
            )
    shown = counts.most_common(max_elements)
    lines += ["", f"elements ({len(counts)} distinct; showing {len(shown)}):"]
    for element, n in shown:
        lines.append(
            f"  {n:>4}  {element}  {'/'.join(sorted(units_by_el[element])) or ''}".rstrip()
        )
    return "\n".join(lines)


def write_facts_csv(inst: Instance, path: Path) -> int:
    """Every fact with its resolved context and unit, to study a real filing in a spreadsheet."""
    columns = [
        "element",
        "value",
        "nil",
        "unit",
        "decimals",
        "precision",
        "period",
        "entity",
        "dimensions",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        for f in inst.facts:
            ctx = inst.contexts.get(f.context_id)
            unit = inst.units.get(f.unit_id) if f.unit_id else None
            writer.writerow(
                [
                    f.element,
                    f.value,
                    f.nil,
                    unit.measure if unit else (f.unit_id or ""),
                    f.decimals or "",
                    f.precision or "",
                    ctx.period if ctx else "?",
                    ctx.entity if ctx else "?",
                    "; ".join(ctx.dimensions) if ctx else "",
                ]
            )
    return len(inst.facts)
