"""Metric rows: one tidy record per number (the `evaluation_result` table), at any scope.

Scopes: model_condition (one model, one condition), model (across conditions), condition (across the
primary panel in one condition), panel (the primary panel as a whole), baseline (controlled baseline
compared with the panel), judgment (one judgment). Every row names the evaluation `version` that wrote
it; `evaluate` and `stats` each replace only their own rows.
"""

from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from gauge.db.models import Condition, EvaluationResult, Model

EVAL_VERSION = "eval-1"
STATS_VERSION = "stats-1"
SCOPES = ("judgment", "model_condition", "model", "condition", "panel", "baseline")


def clean(value: Any) -> Any:
    """JSON/Float-safe: NaN and infinities become None, numpy scalars become Python numbers."""
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        with contextlib.suppress(ValueError, AttributeError):
            value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


@dataclass
class Metric:
    metric: str
    scope: str
    value: float | None = None
    model: str | None = None  # model key
    condition: str | None = None
    repetition: int | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    n: int | None = None
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.scope not in SCOPES:
            raise ValueError(f"unknown scope {self.scope!r}")
        self.value, self.ci_low, self.ci_high = (
            clean(x) for x in (self.value, self.ci_low, self.ci_high)
        )
        self.detail = clean(self.detail)
        self.n = None if self.n is None else int(self.n)


def replace_metrics(session: Session, version: str, metrics: list[Metric]) -> int:
    """Delete every row of `version` and store `metrics`. Returns the number written."""
    session.execute(delete(EvaluationResult).where(EvaluationResult.eval_version == version))
    model_id = {m.key: m.id for m in session.scalars(select(Model))}
    condition_id = {c.code: c.id for c in session.scalars(select(Condition))}
    for m in metrics:
        session.add(
            EvaluationResult(
                eval_version=version,
                metric=m.metric,
                scope=m.scope,
                model_id=model_id.get(m.model) if m.model else None,
                condition_id=condition_id.get(m.condition) if m.condition else None,
                repetition=m.repetition,
                value=m.value,
                ci_low=m.ci_low,
                ci_high=m.ci_high,
                n=m.n,
                detail=m.detail or None,
            )
        )
    session.flush()
    return len(metrics)


def load_metrics(session: Session, version: str | None = None) -> list[Metric]:
    """The stored rows as Metric objects (model and condition as keys again)."""
    model_key = {m.id: m.key for m in session.scalars(select(Model))}
    condition_code = {c.id: c.code for c in session.scalars(select(Condition))}
    query = select(EvaluationResult).order_by(EvaluationResult.id)
    if version is not None:
        query = query.where(EvaluationResult.eval_version == version)
    return [
        Metric(
            metric=r.metric,
            scope=r.scope,
            value=r.value,
            model=model_key.get(r.model_id),
            condition=condition_code.get(r.condition_id),
            repetition=r.repetition,
            ci_low=r.ci_low,
            ci_high=r.ci_high,
            n=r.n,
            detail=r.detail or {},
        )
        for r in session.scalars(query)
    ]
