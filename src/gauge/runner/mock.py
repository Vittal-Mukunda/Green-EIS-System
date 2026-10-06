"""MockRunner: deterministic fake model output for dry runs and tests (spec §8).

It never calls Cursor, an API, or any subprocess. It sees only the prompt text (company codes are
read from it) and, optionally, a `truth` mapping handed to its constructor, which stands in for "the
model is mostly able to apply the rule". Real runners have no such channel.

Output is a pure function of (request.seed, model, run_id, company code), so a re-run reproduces
byte-identical text. Noise and deliberate errors are there to give the evaluation code something
imperfect to score; none of it says anything about real models.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from gauge.runner.base import RunRequest, RunResult
from gauge.vocab import T2_CLASSES

CODE_RE = re.compile(r"\b[A-Z]{3}-\d{2}\b")
MOCK_VERSION = "mock-0.1"

# Deliberate error kinds. `fenced` is benign (what real models often do); the rest are defects.
ERROR_KINDS = (
    "fenced",  # JSON wrapped in prose + ```json fence: parser must extract it
    "truncated",  # response cut off mid-array: invalid JSON, needs the repair run
    "missing_company",  # one company absent from the array
    "out_of_range_rating",  # t3_rating = 7
    "wrong_type",  # t3_rating given as the string "3"
    "long_justification",  # > 40 words
)

_BASE_RATING = {"Leader": 4, "Average": 3, "Laggard": 2}
_DEFAULT_DRIVERS = ("Emissions intensity (Scope 1+2)", "Water intensity", "Renewable energy share")


def _rng(*parts: object) -> random.Random:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def codes_in_prompt(prompt: str) -> list[str]:
    """Masked company codes in order of first appearance."""
    seen: dict[str, None] = {}
    for code in CODE_RE.findall(prompt):
        seen.setdefault(code)
    return list(seen)


class MockRunner:
    mode = "mock"

    def __init__(
        self,
        error_rates: Mapping[str, float] | None = None,
        truth: Mapping[str, str] | None = None,
        drivers: Sequence[str] = _DEFAULT_DRIVERS,
        forced_errors: Mapping[str, str] | None = None,
        fenced_rate: float = 0.10,
        context_distortion: float = 0.08,
        default_error_rate: float = 0.15,
    ) -> None:
        """
        error_rates: model name -> probability of a wrong T2 class (default `default_error_rate`).
        truth: company code -> rule class; if absent a stable pseudo-class is derived from the code.
        forced_errors: run_id -> one of ERROR_KINDS, applied unconditionally (so dry runs always
            contain a few known defects). Repair runs are never corrupted.
        context_distortion: extra T2 error probability under C2 (mimics added context hurting).
        """
        bad = set((forced_errors or {}).values()) - set(ERROR_KINDS)
        if bad:
            raise ValueError(f"unknown mock error kinds: {sorted(bad)}")
        self.error_rates = dict(error_rates or {})
        self.truth = dict(truth or {})
        self.drivers = list(drivers)
        self.forced_errors = dict(forced_errors or {})
        self.fenced_rate = fenced_rate
        self.context_distortion = context_distortion
        self.default_error_rate = default_error_rate

    # -- public API ------------------------------------------------------------------------------
    def run(self, request: RunRequest) -> RunResult:
        started = datetime.now(UTC)
        codes = codes_in_prompt(request.prompt)
        records = [self._judgment(request, code) for code in codes]
        text = self._render(request, records)
        finished = datetime.now(UTC)
        return RunResult(
            stdout=text,
            stderr="",
            exit_code=0,
            duration_s=0.0,  # deterministic by design
            command=["mock-runner", "--model", request.model, "--run-id", request.run_id],
            cli_version=MOCK_VERSION,
            started_utc=started,
            finished_utc=finished,
        )

    # -- internals -------------------------------------------------------------------------------
    def _rule_class(self, code: str) -> str:
        if code in self.truth:
            return self.truth[code]
        return T2_CLASSES[int(hashlib.sha256(code.encode()).hexdigest(), 16) % 3]

    def _judgment(self, req: RunRequest, code: str) -> dict:
        rng = _rng(req.seed, req.model, req.run_id, code)
        truth = self._rule_class(code)
        p_err = self.error_rates.get(req.model, self.default_error_rate)
        if req.condition == "C2":
            p_err = min(1.0, p_err + self.context_distortion)
        t2 = truth
        if rng.random() < p_err:
            t2 = rng.choice([c for c in T2_CLASSES if c != truth])

        bias = _rng("bias", req.model, code).choice([-1, 0, 0, 1])  # stable per (model, company)
        rating = _BASE_RATING[truth] + bias + rng.choice([-1, 0, 0, 0, 1])
        rating = max(1, min(5, rating))
        confidence = max(1, min(5, 3 + rng.choice([-1, 0, 1, 1])))
        drivers = rng.sample(self.drivers, k=3)
        return {
            "company_code": code,
            "t2_class": t2,
            "t3_rating": rating,
            "t3_confidence": confidence,
            "top_drivers": drivers,
            "justification": f"{drivers[0]} and {drivers[1]} drive this assessment; "
            f"{drivers[2]} is secondary.",
            "insufficient_evidence": False,
        }

    def _error_kind(self, req: RunRequest) -> str | None:
        if req.is_repair:
            return None
        if req.run_id in self.forced_errors:
            return self.forced_errors[req.run_id]
        if _rng("fenced", req.seed, req.model, req.run_id).random() < self.fenced_rate:
            return "fenced"
        return None

    def _render(self, req: RunRequest, records: list[dict]) -> str:
        kind = self._error_kind(req)
        rng = _rng("defect", req.seed, req.model, req.run_id)
        if kind == "missing_company" and len(records) > 1:
            del records[rng.randrange(len(records))]
        elif kind == "out_of_range_rating" and records:
            records[rng.randrange(len(records))]["t3_rating"] = 7
        elif kind == "wrong_type" and records:
            target = records[rng.randrange(len(records))]
            target["t3_rating"] = str(target["t3_rating"])
        elif kind == "long_justification" and records:
            records[rng.randrange(len(records))]["justification"] = " ".join(["word"] * 45)

        body = json.dumps(records, indent=2)
        if kind == "truncated":
            return body[: max(2, len(body) * 3 // 5)]
        if kind == "fenced":
            return f"Here is the requested JSON.\n```json\n{body}\n```\n"
        return body
