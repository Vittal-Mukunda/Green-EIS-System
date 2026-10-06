from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from gauge.schemas import MAX_JUSTIFICATION_WORDS, CompanyJudgment, JudgmentArray

GOOD = {
    "company_code": "CEM-03",
    "t2_class": "Leader",
    "t3_rating": 4,
    "t3_confidence": 3,
    "top_drivers": ["Emissions intensity (Scope 1+2)", "Water intensity", "Renewable energy share"],
    "justification": "Emissions intensity is low; water intensity is moderate.",
    "insufficient_evidence": False,
}


def make(**changes) -> dict:
    d = copy.deepcopy(GOOD)
    d.update(changes)
    return d


def test_valid_judgment_round_trips():
    j = CompanyJudgment(**GOOD)
    assert j.model_dump() == GOOD


def test_array_validates_every_element():
    out = JudgmentArray.validate_python([GOOD, make(company_code="STL-01")])
    assert [j.company_code for j in out] == ["CEM-03", "STL-01"]


@pytest.mark.parametrize(
    "bad",
    [
        make(company_code="Ultratech"),  # real names must never appear (rule 9)
        make(company_code="cem-03"),
        make(t2_class="Great"),
        make(t2_class="leader"),
        make(t3_rating=0),
        make(t3_rating=6),
        make(t3_rating="3"),  # strict: string rating is a format deviation
        make(t3_rating=3.0),
        make(t3_rating=True),
        make(t3_confidence=7),
        make(top_drivers=["a", "b"]),
        make(top_drivers=["a", "b", "c", "d"]),
        make(top_drivers=["a", "a", "b"]),
        make(top_drivers=["a", " ", "b"]),
        make(justification=""),
        make(justification=" ".join(["word"] * (MAX_JUSTIFICATION_WORDS + 1))),
        make(insufficient_evidence="no"),
        make(insufficient_evidence=0),
    ],
)
def test_invalid_judgments_rejected(bad):
    with pytest.raises(ValidationError):
        CompanyJudgment(**bad)


def test_justification_limit_is_inclusive():
    CompanyJudgment(**make(justification=" ".join(["word"] * MAX_JUSTIFICATION_WORDS)))


def test_missing_and_extra_fields_rejected():
    missing = {k: v for k, v in GOOD.items() if k != "t3_confidence"}
    with pytest.raises(ValidationError):
        CompanyJudgment(**missing)
    with pytest.raises(ValidationError):
        CompanyJudgment(**make(t4_score=1))


def test_array_rejects_non_list():
    with pytest.raises(ValidationError):
        JudgmentArray.validate_python(GOOD)
