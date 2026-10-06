"""The T3 update rule (spec §4.6): what a rating SHOULD do when context is added (C1 -> C2).

Two signals, each in {-1, 0, +1}, computed from the numbers shown in C2 (displayed, rounded):

* Trend signal: +1 if at least `min_metrics` of the 3 core intensities improved by at least
  `threshold_pct` from FY2022-23 to FY2024-25; -1 if at least `min_metrics` worsened by that much;
  otherwise 0. "Improved" follows each KPI's direction (lower is better for emissions and water
  intensity, higher for renewable share). A change from zero counts as an improvement or a
  worsening by the sign of the new value (it cannot be a percentage).
* Benchmark signal: +1 if the company is better than its sector median on at least
  `min_metrics` of the 3 core metrics (FY2024-25); -1 if worse on at least that many; otherwise 0.
  Equal is neither.

Expected direction of rating(C2) relative to rating(C1): up if both signals are +1 or one is +1 and
the other 0; down if both -1 or one -1 and the other 0; otherwise unconstrained (conflicting
signals, or both 0). A transition is `consistent`, `violating` or `unconstrained` against that.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from gauge.rules.t2 import T2Metric


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrendSpec(_Strict):
    from_fy: str
    to_fy: str
    threshold_pct: Decimal = Field(gt=0)
    min_metrics: int = Field(ge=1)


class BenchmarkSpec(_Strict):
    fy: str
    against: str = Field(pattern="^sector_median$")
    min_metrics: int = Field(ge=1)


class T3Rule(_Strict):
    rule_id: str
    core_metrics: list[T2Metric] = Field(min_length=3, max_length=3)
    trend: TrendSpec
    benchmark: BenchmarkSpec


@dataclass(frozen=True)
class T3Signals:
    trend: int
    benchmark: int
    expected: str  # up | down | none


def _direction(better: str, new: Decimal, old: Decimal, threshold: Decimal) -> int:
    """+1 improved, -1 worsened, 0 neither, by at least `threshold` percent."""
    if old == 0:
        change = (
            Decimal(0) if new == 0 else (Decimal("Infinity") if new > 0 else Decimal("-Infinity"))
        )
    else:
        change = (new - old) / abs(old) * 100
    if better == "lower":
        change = -change
    if change >= threshold:
        return 1
    return -1 if change <= -threshold else 0


def trend_signal(rule: T3Rule, old: dict[str, Decimal], new: dict[str, Decimal]) -> int:
    votes = [
        _direction(m.better, new[m.kpi], old[m.kpi], rule.trend.threshold_pct)
        for m in rule.core_metrics
    ]
    if votes.count(1) >= rule.trend.min_metrics:
        return 1
    return -1 if votes.count(-1) >= rule.trend.min_metrics else 0


def benchmark_signal(rule: T3Rule, values: dict[str, Decimal], medians: dict[str, Decimal]) -> int:
    votes = []
    for m in rule.core_metrics:
        v, med = values[m.kpi], medians[m.kpi]
        if v == med:
            votes.append(0)
        else:
            votes.append(1 if (v < med) == (m.better == "lower") else -1)
    if votes.count(1) >= rule.benchmark.min_metrics:
        return 1
    return -1 if votes.count(-1) >= rule.benchmark.min_metrics else 0


def expected_direction(trend: int, benchmark: int) -> str:
    if trend + benchmark > 0 and min(trend, benchmark) >= 0:
        return "up"
    if trend + benchmark < 0 and max(trend, benchmark) <= 0:
        return "down"
    return "none"


def signals(
    rule: T3Rule, old: dict[str, Decimal], new: dict[str, Decimal], medians: dict[str, Decimal]
) -> T3Signals:
    t, b = trend_signal(rule, old, new), benchmark_signal(rule, new, medians)
    return T3Signals(t, b, expected_direction(t, b))


def label_transition(expected: str, rating_c1: int, rating_c2: int) -> tuple[str, int]:
    """(label, signed change in rating = C2 - C1)."""
    delta = rating_c2 - rating_c1
    if expected == "none":
        return "unconstrained", delta
    ok = delta >= 0 if expected == "up" else delta <= 0
    return ("consistent" if ok else "violating"), delta
