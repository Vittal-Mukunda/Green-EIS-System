"""Parse-failure rates per model (spec 4.8: "report parse-failure rates per model").

Reported at two points, because the repair attempt changes the picture: the *first-attempt* rate
is the share of company judgments that were invalid in the first reply (a property of the model's
format compliance), the *final* rate is what is left after the one repair attempt (what the
analysis loses). Technical failures (a call that returned nothing, a usage limit) are counted
separately: they are not format deviations.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.db.models import Judgment, Model, Run


@dataclass(frozen=True)
class ModelParseRate:
    model_key: str
    model_name: str
    runs: int  # runs with a usable raw reply (status success, not repairs)
    runs_not_ok_first: int  # runs whose first reply had at least one invalid company
    runs_repaired: int
    runs_failed_final: int  # runs with a company still invalid after the repair
    companies: int  # judgments expected
    first_attempt_failures: int
    final_failures: int
    call_failures: int  # runs with status failed / usage_limit (no reply to parse)

    @property
    def first_attempt_rate(self) -> float | None:
        return self.first_attempt_failures / self.companies if self.companies else None

    @property
    def final_rate(self) -> float | None:
        return self.final_failures / self.companies if self.companies else None


def parse_rates(session: Session) -> list[ModelParseRate]:
    out = []
    for model in session.scalars(select(Model).order_by(Model.key)):
        runs = list(
            session.scalars(select(Run).where(Run.model_id == model.id, Run.is_repair.is_(False)))
        )
        if not runs:
            continue
        usable = [r for r in runs if r.status == "success"]
        judgments = [
            j
            for run in usable
            for j in session.scalars(select(Judgment).where(Judgment.run_id == run.id))
        ]
        first = sum(
            j.parse_status == "parse_failure"
            or (j.parse_error or "").startswith(("repaired:", "after repair:"))
            for j in judgments
        )
        final = sum(j.parse_status == "parse_failure" for j in judgments)
        out.append(
            ModelParseRate(
                model_key=model.key,
                model_name=model.name,
                runs=len(usable),
                runs_not_ok_first=sum(
                    r.parse_status in ("repaired", "parse_failure") for r in usable
                ),
                runs_repaired=sum(r.parse_status == "repaired" for r in usable),
                runs_failed_final=sum(r.parse_status == "parse_failure" for r in usable),
                companies=len(judgments),
                first_attempt_failures=first,
                final_failures=final,
                call_failures=len(runs) - len(usable),
            )
        )
    return out


def rates_table(rates: list[ModelParseRate]) -> str:
    """A plain-text table for the terminal."""
    header = (
        f"{'model':<6}{'runs':>5}{'first-reply bad':>17}{'repaired':>10}"
        f"{'still bad':>11}{'first %':>9}{'final %':>9}{'call fails':>12}"
    )
    lines = [header]
    pct = lambda x: "n/a" if x is None else f"{100 * x:.1f}"  # noqa: E731
    for r in rates:
        lines.append(
            f"{r.model_key:<6}{r.runs:>5}{r.runs_not_ok_first:>17}{r.runs_repaired:>10}"
            f"{r.runs_failed_final:>11}{pct(r.first_attempt_rate):>9}{pct(r.final_rate):>9}"
            f"{r.call_failures:>12}"
        )
    return "\n".join(lines)
