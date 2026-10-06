from __future__ import annotations

import json
import re
import socket
import subprocess

import pytest
from pydantic import ValidationError

from gauge.runner.base import RunRequest
from gauge.runner.mock import ERROR_KINDS, MockRunner, codes_in_prompt
from gauge.schemas import JudgmentArray

CODES = ["CEM-01", "CEM-02", "STL-01", "STL-02", "ITS-01"]
PROMPT = "Evidence follows.\n" + "\n".join(f"## {c}\n| x | 1 |" for c in CODES)


def req(
    run_id="P1_C1_r1", *, model="mock-a", cond="C1", rep=1, seed=7, prompt=PROMPT, repair=False
):
    return RunRequest(
        run_id=run_id,
        model=model,
        condition=cond,
        repetition=rep,
        seed=seed,
        prompt=prompt,
        is_repair=repair,
    )


def clean(**kw) -> MockRunner:
    """A runner with no stochastic formatting noise, so tests control exactly what happens."""
    return MockRunner(fenced_rate=0.0, **kw)


def text(runner: MockRunner, request: RunRequest) -> str:
    return runner.run(request).stdout


def test_codes_are_read_from_the_prompt_in_order():
    assert codes_in_prompt("zzz STL-02 and CEM-01, then STL-02 again, ITS-10") == [
        "STL-02",
        "CEM-01",
        "ITS-10",
    ]
    assert codes_in_prompt(PROMPT) == CODES


def test_output_is_valid_and_follows_prompt_order():
    out = JudgmentArray.validate_json(text(clean(), req()))
    assert [j.company_code for j in out] == CODES


def test_run_result_carries_logging_fields():
    res = clean().run(req())
    assert res.exit_code == 0 and res.stderr == "" and res.duration_s == 0.0
    assert res.command[0] == "mock-runner" and res.cli_version.startswith("mock")
    assert res.started_utc.tzinfo is not None and res.finished_utc >= res.started_utc


def test_deterministic_for_same_request():
    a, b = clean(), clean()
    assert text(a, req()) == text(b, req()) == text(a, req())


def test_seed_and_repetition_change_the_noise():
    r = clean(default_error_rate=0.5)
    base = text(r, req(seed=1, rep=1, run_id="X_C1_r1"))
    assert text(r, req(seed=2, rep=1, run_id="X_C1_r1")) != base
    assert text(r, req(seed=1, rep=2, run_id="X_C1_r2")) != base


def test_does_not_use_subprocess_or_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("MockRunner must never spawn processes or open sockets")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(socket, "socket", boom)
    assert text(MockRunner(), req())


def test_truth_is_used_when_error_rate_is_zero():
    truth = dict.fromkeys(CODES, "Laggard")
    out = JudgmentArray.validate_json(
        text(clean(truth=truth, default_error_rate=0.0, context_distortion=0.0), req())
    )
    assert {j.t2_class for j in out} == {"Laggard"}


def test_error_rate_one_always_deviates_from_truth():
    truth = dict.fromkeys(CODES, "Leader")
    out = JudgmentArray.validate_json(text(clean(truth=truth, default_error_rate=1.0), req()))
    assert all(j.t2_class != "Leader" for j in out)


def test_per_model_error_rates():
    codes = [f"{a}{b}{c}-{n:02d}" for a in "AB" for b in "AB" for c in "ABC" for n in range(1, 30)]
    prompt = "\n".join(codes)
    truth = dict.fromkeys(codes, "Average")
    runner = clean(truth=truth, error_rates={"lo": 0.0, "hi": 0.6}, context_distortion=0.0)

    def acc(model):
        out = JudgmentArray.validate_json(text(runner, req(model=model, prompt=prompt)))
        return sum(j.t2_class == "Average" for j in out) / len(out)

    assert acc("lo") == 1.0
    assert 0.3 < acc("hi") < 0.5  # expectation 0.4 over 348 draws


def test_context_distortion_hurts_only_under_c2():
    codes = [
        f"{a}{b}{c}-{n:02d}" for a in "ABCD" for b in "ABCD" for c in "ABCD" for n in range(1, 8)
    ]
    prompt = "\n".join(codes)
    runner = clean(
        truth=dict.fromkeys(codes, "Average"), default_error_rate=0.0, context_distortion=0.3
    )
    wrong = {}
    for cond in ("C1", "C2"):
        out = JudgmentArray.validate_json(text(runner, req(cond=cond, prompt=prompt)))
        wrong[cond] = sum(j.t2_class != "Average" for j in out)
    assert wrong["C1"] == 0 and wrong["C2"] > 0.2 * len(codes)


# ---- deliberate defects -------------------------------------------------------------------------
def forced(kind: str) -> str:
    return text(MockRunner(forced_errors={"P1_C1_r1": kind}, fenced_rate=0.0), req())


def test_truncated_is_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        json.loads(forced("truncated"))


def test_fenced_is_extractable_but_not_bare_json():
    raw = forced("fenced")
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)
    body = re.search(r"```json\n(.*)\n```", raw, re.S).group(1)
    assert len(JudgmentArray.validate_json(body)) == len(CODES)


def test_missing_company_drops_exactly_one():
    out = JudgmentArray.validate_json(forced("missing_company"))
    assert len(out) == len(CODES) - 1


@pytest.mark.parametrize("kind", ["out_of_range_rating", "wrong_type", "long_justification"])
def test_schema_defects_fail_validation(kind):
    with pytest.raises(ValidationError):
        JudgmentArray.validate_json(forced(kind))


def test_every_defect_kind_is_covered_by_these_tests():
    assert set(ERROR_KINDS) == {
        "fenced",
        "truncated",
        "missing_company",
        "out_of_range_rating",
        "wrong_type",
        "long_justification",
    }


def test_repair_runs_are_never_corrupted():
    runner = MockRunner(forced_errors={"P1_C1_r1": "truncated"}, fenced_rate=1.0)
    out = JudgmentArray.validate_json(text(runner, req(repair=True)))
    assert len(out) == len(CODES)


def test_unknown_error_kind_rejected():
    with pytest.raises(ValueError, match="unknown mock error kinds"):
        MockRunner(forced_errors={"P1_C1_r1": "gremlins"})
