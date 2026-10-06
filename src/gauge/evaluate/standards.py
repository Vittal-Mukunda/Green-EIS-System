"""The standards the judgments are scored against: the frozen T2 rule and the T3 update rule applied
to the numbers the models were shown (no LLM-as-judge anywhere).

T2: the class is computed from the displayed FY2024-25 KPIs and the sector cut-points; it is the same
under C1 and C2. T3: the trend and benchmark signals come from the displayed C2 numbers; they do not
define a correct rating, only the direction in which adding context should move it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig, StudyConfig
from gauge.render.evidence import Evidence, EvidenceError, load_evidence
from gauge.rules.build import (
    RuleFileError,
    check_rule_matches_evidence,
    load_t2_rule,
    load_t3_rule,
    t2_path,
    t3_path,
)
from gauge.rules.t2 import T2Result, T2Rule, apply_t2
from gauge.rules.t3 import T3Rule, T3Signals, signals


class StandardsError(RuntimeError):
    """The standards cannot be computed (rules missing or stale, evidence incomplete)."""


@dataclass(frozen=True)
class Standards:
    evidence: Evidence
    t2_rule: T2Rule
    t3_rule: T3Rule
    t2: dict[str, T2Result]  # masked company code -> rule result
    t3: dict[str, T3Signals] = field(default_factory=dict)  # empty if trends are not available


def load_standards(session: Session, cfg: StudyConfig, indicators: IndicatorsConfig) -> Standards:
    try:
        evidence = load_evidence(session, cfg, indicators)
        t2_rule = load_t2_rule(t2_path(cfg))
        t3_rule = load_t3_rule(t3_path(cfg))
    except (EvidenceError, RuleFileError) as exc:
        raise StandardsError(str(exc)) from exc
    stale = check_rule_matches_evidence(t2_rule, evidence)
    if stale:
        raise StandardsError("the T2 rule file is stale: " + "; ".join(stale))

    core = [m.kpi for m in t2_rule.metrics]
    t2: dict[str, T2Result] = {}
    t3: dict[str, T3Signals] = {}
    for code, ce in evidence.companies.items():
        t2[code] = apply_t2(t2_rule, ce.sector, {k: ce.kpis[k] for k in core})
        if evidence.has_trend:
            rule = t3_rule
            old = {k: ce.trend[k][rule.trend.from_fy] for k in core}
            new = {k: ce.trend[k][rule.trend.to_fy] for k in core}
            medians = {k: evidence.sectors[ce.sector].stats[k]["median"] for k in core}
            t3[code] = signals(rule, old, new, medians)
    return Standards(evidence, t2_rule, t3_rule, t2, t3)
