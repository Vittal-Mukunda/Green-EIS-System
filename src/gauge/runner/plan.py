"""Run grid: models x conditions x repetitions, seeded and reproducible (spec §4.7)."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from gauge.config import ModelsConfig, StudyConfig


@dataclass(frozen=True)
class PlannedRun:
    run_id: str
    model_key: str
    model_name: str
    role: str
    channel: str
    condition: str
    repetition: int
    seed: int  # differs per run; also seeds the company order
    order_index: int  # position in the global execution order (0-based)
    min_gap_minutes: float  # earliest start relative to the end of the previous repetition block
    company_order: tuple[str, ...]  # masked codes, shuffled with `seed`


def derive_seed(master_seed: int, *parts: object) -> int:
    """Stable 31-bit seed from the master seed and identifying parts."""
    digest = hashlib.sha256("|".join(str(p) for p in (master_seed, *parts)).encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def run_id_for(model_key: str, condition: str, repetition: int) -> str:
    return f"{model_key}_{condition}_r{repetition}"


def plan_runs(
    cfg: StudyConfig,
    models: ModelsConfig,
    company_codes: list[str],
    *,
    include_disabled: bool = False,
) -> list[PlannedRun]:
    """Plan every run for the enabled models (primary + baseline [+ sensitivity if enabled]).

    Execution order is shuffled with a seed per repetition block, across models and conditions;
    all of repetition 1 precedes repetition 2, which must start >= rep2_min_gap_minutes later.
    `include_disabled` also plans the disabled (optional) models; `freeze` uses it so that enabling
    the sensitivity model later does not require re-freezing the prompts.
    """
    master = cfg.runs.master_seed
    specs = models.models if include_disabled else models.enabled()
    codes = sorted(company_codes)
    planned: list[PlannedRun] = []
    for rep in range(1, cfg.runs.repetitions + 1):
        block = [(m, cond) for m in specs for cond in cfg.runs.conditions]
        random.Random(derive_seed(master, "order", rep)).shuffle(block)
        gap = cfg.runs.rep2_min_gap_minutes if rep >= 2 else 0.0
        for model, cond in block:
            seed = derive_seed(master, model.key, cond, rep)
            order = list(codes)
            random.Random(seed).shuffle(order)
            planned.append(
                PlannedRun(
                    run_id=run_id_for(model.key, cond, rep),
                    model_key=model.key,
                    model_name=model.name,
                    role=model.role,
                    channel=model.channel,
                    condition=cond,
                    repetition=rep,
                    seed=seed,
                    order_index=len(planned),
                    min_gap_minutes=gap,
                    company_order=tuple(order),
                )
            )
    return planned
