"""Render the C1 and C2 prompts from the frozen templates, rules and the evidence (spec §4.3-4.5).

C1 = the instructions (with the T2 rule and the sector cut-points) plus, per company, the reported
indicators and derived KPIs for the analysis year. C2 = exactly the C1 text for each company, then a
context table (3-year KPI trend, sector P25 / median / P75). Because each C2 company block CONTAINS
its C1 block verbatim, "every C1 value appears identically in C2" holds by construction and is also
tested. Prompts carry masked codes only; a leak check refuses any prompt that contains a real name,
NSE symbol or ISIN.

A prompt has two parts. Cursor models get them concatenated into one message (`combined`); the API
baseline gets `system` as the system message and `user` as the user message, so the instructions are
identical on both channels.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig, StudyConfig
from gauge.db.models import Company
from gauge.render.evidence import CompanyEvidence, Evidence
from gauge.rules.rounding import grouped
from gauge.rules.t2 import T2Rule
from gauge.schemas import MAX_JUSTIFICATION_WORDS, N_DRIVERS

SYSTEM_FILE = "system_v1.md"
USER_FILES = {"C1": "c1_user_v1.md", "C2": "c2_user_v1.md"}
TEMPLATE_FILES = (SYSTEM_FILE, *USER_FILES.values())
SEPARATOR = "\n\n---\n\n"  # between the system and user parts of a combined prompt

UNIT_TEXT = {"INR_crore": "INR crore", "t": "tonnes"}
NOT_REPORTED = "not reported"
ASSURANCE_TEXT = {True: "assured", False: "not assured", None: "not stated"}
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_SUFFIX_RE = re.compile(r"\s+(limited|ltd\.?|inc\.?|corporation|corp\.?)$", re.IGNORECASE)


class RenderError(RuntimeError):
    """A prompt cannot be rendered safely (missing template, stale rule, identity leak, ...)."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- templates -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Templates:
    system: str
    user: dict[str, str]  # condition -> template text
    directory: Path


def templates_dir(cfg: StudyConfig) -> Path:
    return cfg.path(cfg.paths.prompts_registry_dir)


def load_templates(cfg: StudyConfig) -> Templates:
    folder = templates_dir(cfg)
    missing = [name for name in TEMPLATE_FILES if not (folder / name).is_file()]
    if missing:
        raise RenderError(f"prompt template(s) not found in {folder}: {missing}")

    def read(name: str) -> str:
        return (folder / name).read_text(encoding="utf-8")

    return Templates(
        system=read(SYSTEM_FILE),
        user={cond: read(name) for cond, name in USER_FILES.items()},
        directory=folder,
    )


def fill(template: str, values: dict[str, str], *, name: str) -> str:
    """Replace every {{PLACEHOLDER}}. Unknown or unused placeholders are errors, never silent."""
    wanted = set(PLACEHOLDER_RE.findall(template))
    if wanted != set(values):
        extra, absent = sorted(set(values) - wanted), sorted(wanted - set(values))
        raise RenderError(
            f"{name}: placeholders mismatch (unused values {extra}, unfilled {absent})"
        )
    return PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], template).strip("\n") + "\n"


# ---- number and text formatting ------------------------------------------------------------------
def unit_text(unit: str) -> str:
    return UNIT_TEXT.get(unit, unit)


def shown(value: Decimal | None) -> str:
    """A number as printed in a prompt (thousands separators); a gap is stated, never filled."""
    return NOT_REPORTED if value is None else num(value)


def num(value: Decimal) -> str:
    """Thousands separators, no exponent, and no padding zeros after the decimal point: rounding to
    N significant figures must not read as extra precision (5,227 not 5,227.00)."""
    return grouped(value.normalize())


def _row(*cells: str) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(header: list[str], rows: list[list[str]], right: Iterable[int] = ()) -> str:
    right = set(right)
    rule = ["---:" if i in right else "---" for i in range(len(header))]
    return "\n".join([_row(*header), _row(*rule), *[_row(*r) for r in rows]])


def kpi_definitions(indicators: IndicatorsConfig) -> str:
    """Each derived KPI's formula written with the indicator labels shown in the prompt."""
    label = {i.code: i.label for i in indicators.indicators}
    lines = []
    for k in indicators.kpis:
        formula = re.sub(r"[a-z][a-z0-9_]*", lambda m: label.get(m.group(0), m.group(0)), k.formula)
        lines.append(f"- {k.label}: {formula} (unit: {unit_text(k.unit)})")
    return "\n".join(lines)


def describe_t2_rule(rule: T2Rule, indicators: IndicatorsConfig) -> str:
    """The rule in words and a table, generated from the rule object so they cannot diverge."""
    kpi = {k.code: k for k in indicators.kpis}
    s, fy = rule.scores, rule.analysis_fy
    rows = []
    for m in rule.metrics:
        if m.better == "lower":
            cells = [
                "at most the low cut-point",
                "above the low cut-point and at most the high cut-point",
                "above the high cut-point",
            ]
        else:
            cells = [
                "at least the high cut-point",
                "at least the low cut-point and below the high cut-point",
                "below the low cut-point",
            ]
        rows.append([kpi[m.kpi].label, m.better, *cells])
    table = _table(
        ["KPI", "Better when", f"Score {s['best']}", f"Score {s['middle']}", f"Score {s['worst']}"],
        rows,
    )
    top = len(rule.metrics) * s["best"]
    totals = ". ".join(
        f"Total {lo} to {hi}: {name}" if lo != hi else f"Total {lo}: {name}"
        for name, (lo, hi) in rule.classes.items()
    )
    return (
        f"For each of the {len(rule.metrics)} KPIs in the table, compare the company's {fy} value "
        f"with the low and high cut-point of the company's own sector (listed below) and give the "
        f"KPI a score. The value is the one printed in the company's block; do not recompute "
        f"it.\n\n"
        f"{table}\n\n"
        f"Add the scores to get a total from 0 to {top}. {totals}. "
        f"{rule.tie_rule[0].upper()}{rule.tie_rule[1:]}."
    )


def cutpoint_tables(rule: T2Rule, indicators: IndicatorsConfig, sectors: list[str]) -> str:
    kpi = {k.code: k for k in indicators.kpis}
    blocks = []
    for sector in sectors:
        cuts = rule.cut_points[sector]
        n = next(iter(cuts.values())).n
        rows = [
            [kpi[m.kpi].label, unit_text(kpi[m.kpi].unit),
             num(cuts[m.kpi].p33), num(cuts[m.kpi].p67)]
            for m in rule.metrics
        ]  # fmt: skip
        blocks.append(
            f"Sector: {sector} (cut-points from the {n} companies of this sector in the study "
            f"sample, {rule.analysis_fy})\n\n"
            + _table(["KPI", "Unit", "Low cut-point", "High cut-point"], rows, right=(2, 3))
        )
    return "\n\n".join(blocks)


# ---- company blocks ------------------------------------------------------------------------------
def company_block(ce: CompanyEvidence, indicators: IndicatorsConfig, fy: str) -> str:
    """The C1 block for one company. C2 reuses this text verbatim."""
    raw_rows = [
        [i.label, shown(ce.indicators[i.code]), unit_text(i.unit)] for i in indicators.indicators
    ]
    kpi_rows = [[k.label, shown(ce.kpis[k.code]), unit_text(k.unit)] for k in indicators.kpis]
    return "\n".join(
        [
            f"## {ce.code}",
            "",
            f"Sector: {ce.sector}",
            f"Reporting boundary: {ce.boundary or 'not stated'}",
            f"Assurance status: {ASSURANCE_TEXT[ce.assured]}",
            "",
            _table([f"Reported indicator ({fy})", "Value", "Unit"], raw_rows, right=(1,)),
            "",
            _table([f"Derived KPI ({fy})", "Value", "Unit"], kpi_rows, right=(1,)),
        ]
    )


def context_block(ce: CompanyEvidence, evidence: Evidence, indicators: IndicatorsConfig) -> str:
    """The C2-only context for one company: KPI by year, and the sector's FY P25 / median / P75."""
    if not evidence.has_trend:
        raise RenderError("C2 needs 3-year trends, but the evidence was loaded without them")
    sector = evidence.sectors[ce.sector]
    rows = []
    for k in indicators.kpis:
        stats = sector.stats.get(k.code, {})
        years = [shown(ce.trend[k.code][fy]) for fy in evidence.trend_fys]
        sector_cells = [shown(stats.get(name)) for name in ("p25", "median", "p75")]
        rows.append([k.label, *years, *sector_cells, unit_text(k.unit)])
    header = ["KPI", *evidence.trend_fys, "Sector P25", "Sector median", "Sector P75", "Unit"]
    return "\n".join(
        [
            f"Context for {ce.code} (sector statistics: {ce.sector}, {sector.n} companies, "
            f"{evidence.analysis_fy})",
            "",
            _table(header, rows, right=range(1, len(header) - 1)),
        ]
    )


# ---- rendering -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class RenderedPrompt:
    condition: str
    company_order: tuple[str, ...]
    system: str
    user: str

    @property
    def combined(self) -> str:
        """What a Cursor model receives: instructions and evidence in one message."""
        return self.system.rstrip("\n") + SEPARATOR + self.user

    @property
    def sha256(self) -> str:
        return sha256_text(self.combined)

    @property
    def system_sha256(self) -> str:
        return sha256_text(self.system)

    @property
    def user_sha256(self) -> str:
        return sha256_text(self.user)

    def for_channel(self, channel: str) -> tuple[str, str | None]:
        """(prompt, system_prompt) for `execute_run`: API channels split the message in two."""
        if channel == "api":
            return self.user, self.system
        return self.combined, None


def render_prompt(
    *,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    evidence: Evidence,
    rule: T2Rule,
    templates: Templates,
    condition: str,
    company_order: Iterable[str] | None = None,
) -> RenderedPrompt:
    if condition not in templates.user:
        raise RenderError(f"unknown condition {condition!r}")
    order = tuple(company_order) if company_order is not None else tuple(sorted(evidence.companies))
    if set(order) != set(evidence.companies) or len(order) != len(evidence.companies):
        raise RenderError("company order must list every company in the evidence exactly once")
    sectors = [s.name for s in cfg.study.sectors if s.name in evidence.sectors]
    if set(sectors) != set(evidence.sectors):
        raise RenderError("evidence has a sector that is not in the study configuration")
    if set(rule.cut_points) != set(sectors):
        raise RenderError(
            f"T2 rule covers sectors {sorted(rule.cut_points)}, evidence has {sorted(sectors)}"
        )

    system = fill(
        templates.system,
        {
            "ANALYSIS_FY": evidence.analysis_fy,
            "T2_RULE": describe_t2_rule(rule, indicators),
            "CUTPOINTS": cutpoint_tables(rule, indicators, sectors),
            "KPI_DEFINITIONS": kpi_definitions(indicators),
            "DRIVER_NAMES": "\n".join(f"- {label}" for label in indicators.driver_labels),
            "N_DRIVERS": str(N_DRIVERS),
            "MAX_WORDS": str(MAX_JUSTIFICATION_WORDS),
        },
        name=SYSTEM_FILE,
    )

    blocks = []
    for code in order:
        ce = evidence.companies[code]
        block = company_block(ce, indicators, evidence.analysis_fy)
        if condition == "C2":
            block += "\n\n" + context_block(ce, evidence, indicators)
        blocks.append(block)

    values = {
        "ANALYSIS_FY": evidence.analysis_fy,
        "N_COMPANIES": str(len(order)),
        "COMPANY_BLOCKS": "\n\n".join(blocks),
    }
    if condition == "C2":
        values["TREND_FYS"] = f"{', '.join(evidence.trend_fys[:-1])} and {evidence.trend_fys[-1]}"
    user = fill(templates.user[condition], values, name=USER_FILES[condition])
    return RenderedPrompt(condition, order, system, user)


# ---- identity-leak guard (hard rule 9) -------------------------------------------------
def identity_strings(session: Session) -> list[str]:
    """Real names (with and without a corporate suffix), NSE symbols and ISINs of real companies."""
    found: set[str] = set()
    for c in session.scalars(select(Company).where(~Company.is_synthetic)):
        names = [c.real_name, _SUFFIX_RE.sub("", c.real_name), c.nse_symbol, c.isin]
        found.update(n.strip() for n in names if n and len(n.strip()) >= 3)
    return sorted(found)


def find_identity_leaks(text: str, identities: Iterable[str]) -> list[str]:
    """Identity strings that occur in `text` as whole words (case-insensitive)."""
    leaks = []
    for ident in identities:
        pattern = rf"(?<![A-Za-z0-9]){re.escape(ident)}(?![A-Za-z0-9])"
        if re.search(pattern, text, re.IGNORECASE):
            leaks.append(ident)
    return leaks


def assert_no_identity_leak(prompt: RenderedPrompt, identities: Iterable[str]) -> None:
    leaks = find_identity_leaks(prompt.combined, list(identities))
    if leaks:
        raise RenderError(
            f"{prompt.condition} prompt contains company identity strings {leaks}; "
            "prompts must carry masked codes only (hard rule 9)"
        )
