"""Rows derived from the judgments: C1 -> C2 transitions (T3 update rule) and disagreement flags.

Both tables are recomputed from scratch on every evaluation (they hold no human input), so a rebuild
after more runs or a repair is always consistent.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from gauge.db.models import Company, Condition, DisagreementFlag, Model, TransitionResult
from gauge.evaluate.frame import valid_only
from gauge.evaluate.standards import Standards, StandardsError
from gauge.rules.t3 import label_transition


@dataclass(frozen=True)
class DerivedCounts:
    transitions: int
    flags: dict[str, int]


def build_transitions(session: Session, frame: pd.DataFrame, standards: Standards) -> int:
    """One TransitionResult per (model, company, repetition) with a valid C1 and a valid C2 judgment."""
    if not standards.t3:
        raise StandardsError(
            "the T3 update rule needs the 3-year trend (FY2022-23 and FY2023-24 data) to compute "
            "its signals"
        )
    session.execute(delete(TransitionResult))
    model_id = {m.key: m.id for m in session.scalars(select(Model))}
    company_id = {c.code: c.id for c in session.scalars(select(Company))}
    ok = valid_only(frame)
    c1 = ok[ok["condition"] == "C1"].set_index(["model_key", "repetition", "company_code"])
    c2 = ok[ok["condition"] == "C2"].set_index(["model_key", "repetition", "company_code"])
    written = 0
    for key in sorted(c1.index.intersection(c2.index)):
        model, repetition, code = key
        a, b = c1.loc[key], c2.loc[key]
        signal = standards.t3[code]
        label, delta = label_transition(signal.expected, int(a["t3_rating"]), int(b["t3_rating"]))
        session.add(
            TransitionResult(
                model_id=model_id[model],
                company_id=company_id[code],
                repetition=int(repetition),
                variant="",
                c1_judgment_id=int(a["judgment_id"]),
                c2_judgment_id=int(b["judgment_id"]),
                trend_signal=signal.trend,
                benchmark_signal=signal.benchmark,
                expected_direction=signal.expected,
                delta_rating=delta,
                label=label,
                t2_changed=a["t2_class"] != b["t2_class"],
            )
        )
        written += 1
    session.flush()
    return written


def build_flags(session: Session, frame: pd.DataFrame, standards: Standards) -> dict[str, int]:
    """Company-level flags for the dashboard's disagreement queue."""
    session.execute(delete(DisagreementFlag))
    model_id = {m.key: m.id for m in session.scalars(select(Model))}
    condition_id = {c.code: c.id for c in session.scalars(select(Condition))}
    company_id = {c.code: c.id for c in session.scalars(select(Company))}
    counts: dict[str, int] = defaultdict(int)
    ok = valid_only(frame)
    primary = ok[ok["role"] == "primary"]

    for (code, condition, repetition), group in primary.groupby(
        ["company_code", "condition", "repetition"], sort=True
    ):
        classes = dict(zip(group["model_key"], group["t2_class"], strict=True))
        if len(set(classes.values())) > 1:
            session.add(
                DisagreementFlag(
                    company_id=company_id[code],
                    condition_id=condition_id[condition],
                    repetition=int(repetition),
                    flag_type="t2_models_disagree",
                    detail={"classes": classes, "rule_class": standards.t2[code].t2_class},
                )
            )
            counts["t2_models_disagree"] += 1

    c1 = ok[ok["condition"] == "C1"].set_index(["model_key", "repetition", "company_code"])
    c2 = ok[ok["condition"] == "C2"].set_index(["model_key", "repetition", "company_code"])
    for key in sorted(c1.index.intersection(c2.index)):
        model, repetition, code = key
        first, second = c1.loc[key], c2.loc[key]
        if first["t2_class"] != second["t2_class"]:
            session.add(
                DisagreementFlag(
                    company_id=company_id[code],
                    model_id=model_id[model],
                    repetition=int(repetition),
                    flag_type="t2_flip",
                    detail={
                        "C1": first["t2_class"],
                        "C2": second["t2_class"],
                        "rule_class": standards.t2[code].t2_class,
                    },
                )
            )
            counts["t2_flip"] += 1

    for row in session.scalars(
        select(TransitionResult).where(TransitionResult.label == "violating")
    ):
        session.add(
            DisagreementFlag(
                company_id=row.company_id,
                model_id=row.model_id,
                repetition=row.repetition,
                flag_type="rule_violation",
                detail={
                    "expected": row.expected_direction,
                    "delta_rating": row.delta_rating,
                    "trend_signal": row.trend_signal,
                    "benchmark_signal": row.benchmark_signal,
                },
            )
        )
        counts["rule_violation"] += 1
    session.flush()
    return dict(counts)
