"""The judgments as one tidy table (pandas): one row per (model, condition, repetition, company).

Only the study's own runs are included: variant '' (the leave-one-indicator-out variants are separate),
not repair attempts (a repair's values live on the original run's judgments), and runs whose call
succeeded. A judgment that is still invalid after the repair stays in the table with `valid` False and
empty ratings; the analyses use valid judgments and the parse-failure rate reports the rest.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.db.models import (
    Company,
    Condition,
    Judgment,
    Model,
    Run,
    RunCompanyPosition,
    Sector,
)

COLUMNS = [
    "judgment_id",
    "run_id",
    "model_key",
    "role",
    "channel",
    "condition",
    "repetition",
    "company_code",
    "sector",
    "position",
    "valid",
    "repaired",
    "t2_class",
    "t3_rating",
    "t3_confidence",
    "top_drivers",
    "justification",
    "insufficient_evidence",
]


def load_frame(session: Session, *, variant: str = "") -> pd.DataFrame:
    rows = session.execute(
        select(
            Judgment.id,
            Run.run_id,
            Model.key,
            Model.role,
            Model.channel,
            Condition.code,
            Run.repetition,
            Company.code,
            Sector.name,
            RunCompanyPosition.position,
            Judgment.parse_status,
            Judgment.parse_error,
            Judgment.t2_class,
            Judgment.t3_rating,
            Judgment.t3_confidence,
            Judgment.top_drivers,
            Judgment.justification,
            Judgment.insufficient_evidence,
        )
        .join(Run, Run.id == Judgment.run_id)
        .join(Model, Model.id == Run.model_id)
        .join(Condition, Condition.id == Run.condition_id)
        .join(Company, Company.id == Judgment.company_id)
        .join(Sector, Sector.id == Company.sector_id)
        .join(
            RunCompanyPosition,
            (RunCompanyPosition.run_id == Run.id) & (RunCompanyPosition.company_id == Company.id),
        )
        .where(Run.variant == variant, Run.is_repair.is_(False), Run.status == "success")
        .order_by(Model.key, Condition.code, Run.repetition, RunCompanyPosition.position)
    ).all()
    records = []
    for r in rows:
        records.append(
            {
                "judgment_id": r[0],
                "run_id": r[1],
                "model_key": r[2],
                "role": r[3],
                "channel": r[4],
                "condition": r[5],
                "repetition": r[6],
                "company_code": r[7],
                "sector": r[8],
                "position": r[9],
                "valid": r[10] == "ok",
                "repaired": (r[11] or "").startswith("repaired:"),
                "t2_class": r[12],
                "t3_rating": r[13],
                "t3_confidence": r[14],
                "top_drivers": r[15],
                "justification": r[16],
                "insufficient_evidence": r[17],
            }
        )
    frame = pd.DataFrame.from_records(records, columns=COLUMNS)
    for column in ("repetition", "position"):
        frame[column] = frame[column].astype("int64")
    return frame


def valid_only(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["valid"]].copy()
