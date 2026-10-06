"""Convert ingested indicator values to canonical units, keeping the as-reported value for audit.

Ingest stores values exactly as reported (`value`/`unit`, `original_*` empty). Standardizing moves
the as-reported pair into `original_value`/`original_unit` and writes the converted `value` in the
canonical unit. A row with `original_unit` set is already standardized, so re-running is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig
from gauge.db.models import IndicatorValue
from gauge.standardize.units import UnitError, factor_to_canonical


class NotStandardizedError(RuntimeError):
    """Downstream steps compare values across units; they need standardized data."""


@dataclass
class StandardizeSummary:
    converted: int = 0
    already_canonical: int = 0
    skipped_done: int = 0
    errors: list[str] = field(default_factory=list)


def standardize_indicators(session: Session, indicators: IndicatorsConfig) -> StandardizeSummary:
    canonical = {i.code: i.unit for i in indicators.indicators}
    summary = StandardizeSummary()
    summary.skipped_done = session.scalar(
        select(func.count())
        .select_from(IndicatorValue)
        .where(IndicatorValue.original_unit.is_not(None))
    )
    pending = session.scalars(
        select(IndicatorValue)
        .where(IndicatorValue.original_unit.is_(None))
        .order_by(IndicatorValue.id)
    )
    for row in pending:
        target = canonical.get(row.indicator)
        if target is None:
            summary.errors.append(f"indicator_value {row.id}: unknown indicator {row.indicator!r}")
            continue
        try:
            factor = factor_to_canonical(row.unit, target)
        except UnitError as exc:
            summary.errors.append(f"indicator_value {row.id} ({row.indicator}): {exc}")
            continue
        row.original_value, row.original_unit = row.value, row.unit
        row.value, row.unit = row.value * factor, target
        if factor == 1:
            summary.already_canonical += 1
        else:
            summary.converted += 1
    session.flush()
    return summary


def assert_standardized(session: Session) -> None:
    n = session.scalar(
        select(func.count())
        .select_from(IndicatorValue)
        .where(IndicatorValue.original_unit.is_(None))
    )
    if n:
        raise NotStandardizedError(
            f"{n} indicator values are not standardized: run `gauge standardize`"
        )
