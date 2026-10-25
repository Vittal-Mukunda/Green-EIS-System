"""The trust score: how far to believe each number, and the footprint as a whole.

Each input is Measured, Estimated or Default (ref section 6.5). A class has a score s and an indicative
uncertainty u. With E_i the CO2e of activity i:

    trust index  T = sum(E_i x s_i) / sum(E_i)                 (0 to 1)
    uncertainty  U = sqrt(sum((E_i x u_i)^2)) / sum(E_i)       (root-sum-square, independent errors)

**The default values below are uncalibrated placeholders** (V-11). They are design choices, not findings;
the study (H1-H3) exists to test them. Change them only through a ``TrustConfig``, never in place, and
never after seeing study results (sensitivity analysis only). Root-sum-square assumes independent errors,
which is optimistic when one proxy (one price, one load factor) feeds several inputs (V-12).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from .engine import DATA_CLASSES, Footprint

PLACEHOLDER_SCORES = {
    "measured": Decimal("1.0"),
    "estimated": Decimal("0.6"),
    "default": Decimal("0.3"),
}
PLACEHOLDER_UNCERTAINTY = {
    "measured": Decimal("0.05"),
    "estimated": Decimal("0.25"),
    "default": Decimal("0.50"),
}


@dataclass(frozen=True)
class TrustConfig:
    scores: dict[str, Decimal] = field(default_factory=lambda: dict(PLACEHOLDER_SCORES))
    uncertainty: dict[str, Decimal] = field(default_factory=lambda: dict(PLACEHOLDER_UNCERTAINTY))
    high_from: Decimal = Decimal("0.8")  # index >= this is "high"
    medium_from: Decimal = Decimal("0.5")  # index >= this is "medium", below is "low"
    status: str = "placeholder"  # "placeholder" or "calibrated"

    def __post_init__(self) -> None:
        for mapping in (self.scores, self.uncertainty):
            if set(mapping) != set(DATA_CLASSES):
                raise ValueError(f"trust config needs exactly the classes {DATA_CLASSES}")


def trust_index(fp: Footprint, cfg: TrustConfig | None = None) -> Decimal | None:
    cfg = cfg or TrustConfig()
    total = fp.total_co2e_t
    if total == 0:
        return None
    return (
        sum((r.co2e_t * cfg.scores[r.activity.data_class] for r in fp.results), Decimal(0)) / total
    )


def total_uncertainty(fp: Footprint, cfg: TrustConfig | None = None) -> Decimal | None:
    """Relative half-width U of the total (0.129 means plus or minus 12.9%)."""
    cfg = cfg or TrustConfig()
    total = fp.total_co2e_t
    if total == 0:
        return None
    squares = sum(
        ((r.co2e_t * cfg.uncertainty[r.activity.data_class]) ** 2 for r in fp.results), Decimal(0)
    )
    return squares.sqrt() / total


def band(index: Decimal | None, cfg: TrustConfig | None = None) -> str:
    cfg = cfg or TrustConfig()
    if index is None:
        return "not available"
    if index >= cfg.high_from:
        return "high"
    if index >= cfg.medium_from:
        return "medium"
    return "low"


def interval(fp: Footprint, cfg: TrustConfig | None = None) -> tuple[Decimal, Decimal] | None:
    """The total with its indicative range: total x (1 - U) to total x (1 + U)."""
    u = total_uncertainty(fp, cfg)
    if u is None:
        return None
    total = fp.total_co2e_t
    return total * (1 - u), total * (1 + u)


def variance_contributions(fp: Footprint, cfg: TrustConfig | None = None) -> dict[int, Decimal]:
    """Each activity's share of the squared-uncertainty sum, by position in the footprint. The largest
    entries are where better data would shrink the total uncertainty most."""
    cfg = cfg or TrustConfig()
    squares = {
        i: (r.co2e_t * cfg.uncertainty[r.activity.data_class]) ** 2
        for i, r in enumerate(fp.results)
    }
    whole = sum(squares.values(), Decimal(0))
    if whole == 0:
        return {i: Decimal(0) for i in squares}
    return {i: v / whole for i, v in squares.items()}


def flag_counts(fp: Footprint) -> Counter[str]:
    """How many activities carry each assumption flag (assumed_density, coal_grade_assumed, ...)."""
    counts: Counter[str] = Counter()
    for r in fp.results:
        counts.update(r.flags)
    return counts


FLAG_TEXT = {
    "assumed_density": "A fuel density was assumed to convert litres to kilograms.",
    "coal_grade_assumed": "The coal grade is unknown, so the sub-bituminous factor was used.",
    "factor_not_source_verified": "The emission factor has not been verified against its source.",
}
