from __future__ import annotations

from collections import Counter

from gauge.config import load_models
from gauge.runner.plan import derive_seed, plan_runs, run_id_for


def plan(cfg):
    return plan_runs(cfg, load_models(cfg), cfg.masked_codes())


def test_real_study_has_20_runs(real_cfg):
    runs = plan(real_cfg)
    assert len(runs) == 20
    assert Counter(r.role for r in runs) == {"primary": 16, "baseline": 4}
    assert Counter(r.model_key for r in runs) == {"P1": 4, "P2": 4, "P3": 4, "P4": 4, "B1": 4}
    assert Counter(r.condition for r in runs) == {"C1": 10, "C2": 10}
    assert Counter(r.repetition for r in runs) == {1: 10, 2: 10}


def test_dry_study_has_same_run_shape(dry_cfg):
    assert len(plan(dry_cfg)) == 20


def test_run_ids_and_seeds_are_unique(real_cfg):
    runs = plan(real_cfg)
    assert len({r.run_id for r in runs}) == 20
    assert len({r.seed for r in runs}) == 20  # "seed differs per run"
    assert run_id_for("P1", "C2", 1) == "P1_C2_r1"
    assert all(0 <= r.seed < 2**31 for r in runs)  # fits a 32-bit signed DB integer


def test_plan_is_deterministic(real_cfg):
    assert plan(real_cfg) == plan(real_cfg)


def test_master_seed_changes_order_and_seeds(real_cfg):
    other = real_cfg.model_copy(deep=True)
    other.runs.master_seed = 43
    a, b = plan(real_cfg), plan(other)
    assert [r.run_id for r in a] != [r.run_id for r in b]
    assert [r.seed for r in a] != [r.seed for r in b]


def test_repetition_two_is_gated_after_repetition_one(real_cfg):
    runs = plan(real_cfg)
    reps = [r.repetition for r in runs]
    assert reps == sorted(reps)  # all of rep 1 runs before any rep 2 run
    assert all(r.min_gap_minutes == 0 for r in runs if r.repetition == 1)
    assert all(r.min_gap_minutes >= 60 for r in runs if r.repetition == 2)


def test_order_is_shuffled_across_models_and_conditions(real_cfg):
    rep1 = [r for r in plan(real_cfg) if r.repetition == 1]
    canonical = [run_id_for(m, c, 1) for m in ("P1", "P2", "P3", "P4", "B1") for c in ("C1", "C2")]
    assert [r.run_id for r in rep1] != canonical
    assert sorted(r.run_id for r in rep1) == sorted(canonical)
    assert [r.order_index for r in plan(real_cfg)] == list(range(20))


def test_company_order_is_a_permutation_that_varies_per_run(real_cfg):
    runs = plan(real_cfg)
    codes = sorted(real_cfg.masked_codes())
    assert all(sorted(r.company_order) == codes for r in runs)
    assert len({r.company_order for r in runs}) > 15  # nearly every run has its own order


def test_derive_seed_is_stable():
    assert derive_seed(42, "P1", "C1", 1) == derive_seed(42, "P1", "C1", 1)
    assert derive_seed(42, "P1", "C1", 1) != derive_seed(42, "P1", "C1", 2)
