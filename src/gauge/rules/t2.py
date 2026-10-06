"""The T2 rule (spec §4.5): a tertile-based class from three intensities, within the sector.

For each core KPI, a company's FY2024-25 value is compared with its sector's two tertile cut-points:
the better tertile scores 2, the middle 1, the worse 0. The scores are summed: 5-6 Leader, 2-4
Average, 0-1 Laggard. "Better" is lower for emissions and water intensity, higher for renewable
share. A value equal to a cut-point falls in the BETTER tertile (the spec left ties open; this is
the choice made, and it is stated in the prompt).

Everything here works on the DISPLAYED numbers (4 significant figures by default), so the correct
class is exactly derivable from the prompt text, and is the same under C1 and C2.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CLASSES = ("Leader", "Average", "Laggard")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class T2Metric(_Strict):
    kpi: str
    better: str = Field(pattern="^(lower|higher)$")


class CutPoints(_Strict):
    p33: Decimal  # lower tertile cut (probability 1/3), as displayed
    p67: Decimal  # upper tertile cut (probability 2/3), as displayed
    n: int = Field(ge=3)

    @model_validator(mode="after")
    def _ordered(self) -> CutPoints:
        if self.p33 > self.p67:
            raise ValueError("p33 must not exceed p67")
        return self


class T2Rule(_Strict):
    rule_id: str
    analysis_fy: str
    display_significant_figures: int = Field(ge=2, le=8)
    metrics: list[T2Metric] = Field(min_length=3, max_length=3)
    scores: dict[str, int]  # best / middle / worst
    classes: dict[str, tuple[int, int]]  # class -> inclusive score range
    tie_rule: str
    cut_points: dict[str, dict[str, CutPoints]]  # sector -> kpi -> cut-points

    @model_validator(mode="after")
    def _check(self) -> T2Rule:
        if set(self.scores) != {"best", "middle", "worst"} or not (
            self.scores["best"] > self.scores["middle"] > self.scores["worst"]
        ):
            raise ValueError("scores must be best > middle > worst")
        if set(self.classes) != set(CLASSES):
            raise ValueError(f"classes must be exactly {CLASSES}")
        covered = sorted(s for lo, hi in self.classes.values() for s in range(lo, hi + 1))
        top = len(self.metrics) * self.scores["best"]
        if covered != list(range(top + 1)):
            raise ValueError(f"class ranges must cover every total score 0..{top} exactly once")
        kpis = {m.kpi for m in self.metrics}
        for sector, per_kpi in self.cut_points.items():
            if set(per_kpi) != kpis:
                raise ValueError(f"{sector}: cut-points must cover exactly {sorted(kpis)}")
        return self


@dataclass(frozen=True)
class T2Result:
    scores: dict[str, int]  # kpi -> 0/1/2
    total: int
    t2_class: str


def score_metric(value: Decimal, cuts: CutPoints, better: str, scores: dict[str, int]) -> int:
    if better == "lower":
        if value <= cuts.p33:
            return scores["best"]
        return scores["worst"] if value > cuts.p67 else scores["middle"]
    if value >= cuts.p67:
        return scores["best"]
    return scores["worst"] if value < cuts.p33 else scores["middle"]


def classify(total: int, classes: dict[str, tuple[int, int]]) -> str:
    for name, (lo, hi) in classes.items():
        if lo <= total <= hi:
            return name
    raise ValueError(f"total score {total} falls in no class")


def apply_t2(rule: T2Rule, sector: str, values: dict[str, Decimal]) -> T2Result:
    """`values` are the company's DISPLAYED FY2024-25 KPI values."""
    if sector not in rule.cut_points:
        raise KeyError(f"no cut-points for sector {sector!r}")
    scores = {
        m.kpi: score_metric(values[m.kpi], rule.cut_points[sector][m.kpi], m.better, rule.scores)
        for m in rule.metrics
    }
    total = sum(scores.values())
    return T2Result(scores, total, classify(total, rule.classes))
