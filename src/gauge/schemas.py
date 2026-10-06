"""Output schema that every model response is validated against (spec §4.4).

Validation is strict on purpose: a rating of "3" or 3.0 is a format deviation that the repair step
and the parse-failure rate are meant to expose, not silently absorb.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    TypeAdapter,
    field_validator,
)

from gauge.vocab import MASKED_CODE_RE, T2Class

MAX_JUSTIFICATION_WORDS = 40
N_DRIVERS = 3

Rating = Annotated[StrictInt, Field(ge=1, le=5)]


class CompanyJudgment(BaseModel):
    """One company's judgment; the model returns a JSON array of these, one per company."""

    model_config = ConfigDict(extra="forbid")

    company_code: str
    t2_class: T2Class
    t3_rating: Rating
    t3_confidence: Rating
    top_drivers: list[str]
    justification: str
    insufficient_evidence: StrictBool

    @field_validator("company_code")
    @classmethod
    def _masked(cls, v: str) -> str:
        if not MASKED_CODE_RE.match(v):
            raise ValueError(f"company_code must look like CEM-03, got {v!r}")
        return v

    @field_validator("top_drivers")
    @classmethod
    def _drivers(cls, v: list[str]) -> list[str]:
        if len(v) != N_DRIVERS:
            raise ValueError(f"top_drivers must list exactly {N_DRIVERS} indicator names")
        if any(not d.strip() for d in v) or len({d.strip().lower() for d in v}) != N_DRIVERS:
            raise ValueError("top_drivers must be non-empty and distinct")
        return v

    @field_validator("justification")
    @classmethod
    def _justification(cls, v: str) -> str:
        words = len(v.split())
        if words == 0:
            raise ValueError("justification must not be empty")
        if words > MAX_JUSTIFICATION_WORDS:
            raise ValueError(
                f"justification has {words} words; the limit is {MAX_JUSTIFICATION_WORDS}"
            )
        return v


# A whole response: one JSON array. Per-element validation (to salvage valid companies and record
# parse_failure for the rest) is done in the parse layer using CompanyJudgment directly.
JudgmentArray = TypeAdapter(list[CompanyJudgment])
