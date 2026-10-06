"""Reply parsing (spec 4.8): extraction, per-company validation, the one repair, failure rates."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import delete, select

from gauge.db.models import (
    Claim,
    DisagreementFlag,
    Judgment,
    Run,
    RunCompanyPosition,
    TransitionResult,
)
from gauge.db.session import session_scope
from gauge.parse.extract import extract_json_array
from gauge.parse.judgments import parse_run, run_company_codes, validate_response
from gauge.parse.rates import parse_rates
from gauge.parse.repair import (
    REPAIR_SUFFIX,
    apply_repairs,
    correction_notice,
    pending_repairs,
    run_repairs,
)
from gauge.render.runs import render_run_prompts
from gauge.runcmd import stage_parse
from gauge.runner.execute import execute_run
from helpers import CannedRunner, good_item

LABELS = [
    "Revenue from operations",
    "Water intensity",
    "Energy intensity",
    "Waste recovery rate",
    "Emissions intensity (Scope 1+2)",
]
CODES = ["AAA-01", "AAA-02", "BBB-01"]


# ---- extraction ----------------------------------------------------------------------------------
def test_plain_array():
    ex = extract_json_array('[{"a": 1}, {"a": 2}]')
    assert ex.method == "plain" and ex.items == [{"a": 1}, {"a": 2}] and ex.error is None


def test_fenced_array_with_and_without_language():
    for fence in ("```json", "```"):
        ex = extract_json_array(f"Here you go:\n{fence}\n" + '[{"a": 1}]' + "\n```\nHope it helps.")
        assert ex.method == "fenced" and ex.items == [{"a": 1}]


def test_array_embedded_in_prose_and_inner_arrays_are_not_mistaken_for_it():
    ex = extract_json_array('Result: [ {"a": [1, 2], "b": ["x"]}, {"a": []} ] done.')
    assert ex.method == "embedded" and len(ex.items) == 2


def test_the_longest_array_of_objects_wins():
    text = 'Example: [{"a": 1}] and the real one: [{"a": 1}, {"a": 2}, {"a": 3}]'
    assert len(extract_json_array(text).items) == 3


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("", "empty"),
        ("   \n", "empty"),
        ("I cannot help with that.", "no valid JSON array"),
        ('{"companies": [1, 2]}', "no valid JSON array"),
        ('[{"a": 1}, {"a": 2},]', "no valid JSON array"),  # trailing comma: not JSON
        ("[{'a': 1}]", "no valid JSON array"),  # single quotes: not JSON
        ('[{"a": 1}, {"a": 2', "truncated"),
    ],
)
def test_text_that_is_not_a_json_array_is_reported_not_repaired(text, fragment):
    ex = extract_json_array(text)
    assert ex.items is None and ex.method == "none" and fragment in ex.error


# ---- validation ----------------------------------------------------------------------------------
def check(items, codes=CODES):
    return validate_response(json.dumps(items), codes, LABELS)


def test_a_good_reply_is_accepted_and_drivers_are_canonical():
    items = [good_item(c) for c in CODES]
    items[0]["top_drivers"] = ["  water INTENSITY", "ENERGY intensity", "Waste recovery rate"]
    result = check(items)
    assert result.ok and result.unexpected == []
    assert result.results["AAA-01"].judgment.top_drivers == [
        "Water intensity",
        "Energy intensity",
        "Waste recovery rate",
    ]


@pytest.mark.parametrize(
    "change, fragment",
    [
        ({"t3_rating": "3"}, "t3_rating"),  # a string, not an integer
        ({"t3_rating": 3.0}, "t3_rating"),  # a float, not an integer
        ({"t3_rating": 7}, "t3_rating"),
        ({"t3_rating": 0}, "t3_rating"),
        ({"t3_confidence": 6}, "t3_confidence"),
        ({"t2_class": "leader"}, "t2_class"),  # wrong case is not "fixed"
        ({"t2_class": "Excellent"}, "t2_class"),
        ({"insufficient_evidence": "false"}, "insufficient_evidence"),
        ({"justification": " ".join(["word"] * 41)}, "justification"),
        ({"justification": ""}, "justification"),
        ({"top_drivers": ["Water intensity", "Energy intensity"]}, "top_drivers"),
        ({"top_drivers": ["Water intensity", "water intensity", "Energy intensity"]}, "distinct"),
        ({"top_drivers": ["Water intensity", "Energy intensity", "Carbon vibes"]}, "not a listed"),
        ({"extra_key": 1}, "extra_key"),
        ({"company_code": "bad code"}, "company"),
    ],
)
def test_one_bad_company_fails_alone(change, fragment):
    items = [good_item(c) for c in CODES]
    items[1].update(change)
    result = check(items)
    bad = result.bad
    assert len(bad) == 1 and fragment in bad[0].error
    ok = [r for r in result.results.values() if r.judgment is not None]
    assert len(ok) == 2  # the other companies are kept


def test_a_missing_key_fails_that_company():
    items = [good_item(c) for c in CODES]
    del items[2]["t3_confidence"]
    (bad,) = check(items).bad
    assert bad.code == "BBB-01" and "t3_confidence" in bad.error


def test_missing_duplicate_and_unexpected_companies():
    items = [good_item("AAA-01"), good_item("AAA-01"), good_item("ZZZ-09")]
    result = check(items)
    assert result.results["AAA-01"].error == "the company appears 2 times in the reply"
    assert result.results["AAA-02"].error == "the company is missing from the reply"
    assert result.results["BBB-01"].error == "the company is missing from the reply"
    assert result.unexpected == ["ZZZ-09"] and "ignored" in result.notes[0]


def test_non_object_elements_and_unparseable_replies_fail_every_company():
    result = validate_response("[1, 2, 3]", CODES, LABELS)  # an array, but not of objects
    assert not result.ok and result.unexpected == []
    assert all("missing from the reply" in r.error for r in result.results.values())
    assert len(result.notes) == 3 and "element 0 has no usable company_code" in result.notes[0]
    text = validate_response('{"not": "an array"}', CODES, LABELS)
    assert all("no valid JSON array" in r.error for r in text.results.values())
    mixed = validate_response(json.dumps([good_item("AAA-01"), "text"]), CODES, LABELS)
    assert mixed.results["AAA-01"].judgment is not None and len(mixed.bad) == 2


# ---- the repair notice ---------------------------------------------------------------------------
def test_correction_notice_states_the_problem_without_new_information():
    one = correction_notice({"A-1": "x", "B-2": "x"})
    assert "# Correction" in one and "could not be used: x" in one and "- A-1" not in one
    many = correction_notice({f"C-{i}": f"problem {i}" for i in range(8)})
    assert "- C-0: problem 0" in many and "and 3 more" in many
    assert one.startswith("\n\n# Correction") and "the whole task again" in one


# ---- the dry run end to end ----------------------------------------------------------------------
@pytest.fixture
def dry(proj):
    from types import SimpleNamespace

    from gauge.config import load_indicators, load_models, load_study
    from gauge.db.session import make_engine
    from gauge.pipeline import run_all_dry

    run_all_dry(root=proj)
    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    yield SimpleNamespace(
        cfg=cfg, ind=load_indicators(cfg), models=load_models(cfg), engine=engine, root=proj
    )
    engine.dispose()


def rows(engine, model, *where):
    with session_scope(engine) as s:
        return list(s.scalars(select(model).where(*where)))


def test_every_company_of_every_run_has_a_judgment_and_all_end_valid(dry):
    runs = rows(dry.engine, Run, Run.is_repair.is_(False))
    assert len(runs) == 20
    judgments = rows(dry.engine, Judgment)
    assert len(judgments) == 20 * 6 and all(j.parse_status == "ok" for j in judgments)
    assert {r.parse_status for r in runs} == {"ok", "repaired"}
    assert {j.run_id for j in judgments} == {r.id for r in runs}  # none belong to a repair run


def test_the_five_planted_reply_defects_each_got_exactly_one_repair(dry):
    planted = {"P1_C1_r1", "P2_C1_r2", "P3_C2_r1", "P4_C2_r2", "B1_C1_r1"}
    repairs = rows(dry.engine, Run, Run.is_repair.is_(True))
    assert {r.run_id for r in repairs} == {f"{p}{REPAIR_SUFFIX}" for p in planted}
    originals = {r.id: r for r in rows(dry.engine, Run, Run.is_repair.is_(False))}
    for rep in repairs:
        original = originals[rep.repair_of_run_id]
        assert original.run_id + REPAIR_SUFFIX == rep.run_id
        assert original.parse_status == "repaired" and rep.parse_status == "ok"
        assert rep.status == "success" and rep.seed == original.seed
        assert rep.model_id == original.model_id and rep.condition_id == original.condition_id
        assert rep.prompt_text.startswith(original.prompt_text)
        assert "# Correction" in rep.prompt_text[len(original.prompt_text) :]
    assert {r.run_id for r in originals.values() if r.parse_status == "ok"}.isdisjoint(planted)
    positions = rows(
        dry.engine, RunCompanyPosition, RunCompanyPosition.run_id.in_([r.id for r in repairs])
    )
    assert positions == []  # a repair is not a new appearance of the companies


def test_only_the_invalid_companies_take_their_values_from_the_repair(dry):
    by_id = {r.run_id: r for r in rows(dry.engine, Run)}
    for run_id, n_repaired in (("P2_C1_r2", 1), ("P4_C2_r2", 1), ("B1_C1_r1", 1), ("P3_C2_r1", 6)):
        js = rows(dry.engine, Judgment, Judgment.run_id == by_id[run_id].id)
        marked = [j for j in js if (j.parse_error or "").startswith("repaired:")]
        assert len(js) == 6 and len(marked) == n_repaired, run_id
    clean = rows(dry.engine, Judgment, Judgment.run_id == by_id["P1_C2_r1"].id)
    assert all(j.parse_error is None for j in clean)


def test_failure_rates_count_first_attempt_and_final_separately(dry):
    with session_scope(dry.engine) as s:
        rates = {r.model_key: r for r in parse_rates(s)}
    assert set(rates) == {"B1", "P1", "P2", "P3", "P4"}
    assert rates["P3"].first_attempt_failures == 6 and rates["P3"].first_attempt_rate == 6 / 24
    for key in ("P1", "P2", "P4", "B1"):
        assert rates[key].first_attempt_failures == 1 and rates[key].companies == 24
    assert all(r.final_failures == 0 and r.final_rate == 0 for r in rates.values())
    assert all(
        r.runs == 4 and r.runs_repaired == 1 and r.call_failures == 0 for r in rates.values()
    )


def test_parsing_again_changes_nothing(dry):
    before = [(j.id, j.parse_status, j.parse_error) for j in rows(dry.engine, Judgment)]
    result = stage_parse(dry.engine, dry.cfg, dry.ind)
    assert result.status == "ok" and "0 runs parsed" in result.detail
    assert [(j.id, j.parse_status, j.parse_error) for j in rows(dry.engine, Judgment)] == before


def test_parsing_reads_the_raw_file_not_the_logged_copy(dry):
    run = rows(dry.engine, Run, Run.run_id == "P1_C2_r1")[0]
    raw = dry.root / run.raw_path
    assert raw.is_file()
    with session_scope(dry.engine) as s:
        # the dry run has been evaluated, so judgments have dependent rows; clear those first
        for model in (Claim, TransitionResult, DisagreementFlag):
            s.execute(delete(model))
        fresh = s.get(Run, run.id)
        fresh.parse_status = "not_parsed"
        for j in s.scalars(select(Judgment).where(Judgment.run_id == run.id)):
            s.delete(j)
    items = json.loads(raw.read_text(encoding="utf-8"))
    items[0]["t3_rating"] = 9  # the raw file is what gets judged
    raw.write_text(json.dumps(items), encoding="utf-8")
    stage_parse(dry.engine, dry.cfg, dry.ind)
    with session_scope(dry.engine) as s:
        assert s.get(Run, run.id).parse_status == "parse_failure"


# ---- one repair, no more -------------------------------------------------------------------------
@pytest.fixture
def mini(world, ctx):
    """Three planned runs of the first model, executed by a runner that returns canned text."""
    runs = render_run_prompts(world.cfg, world.ind, world.models, ctx)[:3]
    codes = sorted(ctx.evidence.companies)
    return world, runs, codes


def execute(world, runner, rp, **kw):
    with session_scope(world.engine) as s:
        prompt, system = rp.prompt.for_channel("cursor")
        return execute_run(s, world.cfg, runner, rp.planned, prompt, system_prompt=system, **kw)


def test_a_repair_that_is_still_invalid_is_final_and_never_retried(mini):
    world, runs, codes = mini
    labels = world.ind.driver_labels
    first = runs[0]
    bad = [good_item(c, labels) for c in codes]
    bad[0]["t3_rating"] = 99
    runner = CannedRunner({first.planned.run_id: bad, first.planned.run_id + REPAIR_SUFFIX: bad})
    execute(world, runner, first)
    with session_scope(world.engine) as s:
        run = s.scalar(select(Run).where(Run.run_id == first.planned.run_id))
        assert parse_run(s, world.cfg, run, labels).n_bad == 1
        assert [r.run_id for r in pending_repairs(s)] == [first.planned.run_id]
    result = stage_parse(world.engine, world.cfg, world.ind, runner=runner, repair=True)
    assert result.status == "ok" and "1 repair attempts (0 fully repaired)" in result.detail
    with session_scope(world.engine) as s:
        run = s.scalar(select(Run).where(Run.run_id == first.planned.run_id))
        assert run.parse_status == "parse_failure"
        bad_rows = list(
            s.scalars(
                select(Judgment).where(Judgment.run_id == run.id, Judgment.parse_status != "ok")
            )
        )
        assert len(bad_rows) == 1 and bad_rows[0].parse_error.startswith("after repair:")
        assert pending_repairs(s) == []  # the one attempt is spent
    again = stage_parse(world.engine, world.cfg, world.ind, runner=runner, repair=True)
    assert "0 repair attempts" in again.detail and len(runner.calls) == 2


def test_a_repair_call_that_fails_technically_can_be_tried_again(mini):
    world, runs, codes = mini
    labels = world.ind.driver_labels
    first = runs[0]
    bad = [good_item(c, labels) for c in codes]
    bad[1]["t3_rating"] = 99
    rid = first.planned.run_id
    runner = CannedRunner({rid: bad, rid + REPAIR_SUFFIX: ""})  # the repair call returns nothing
    execute(world, runner, first)
    stage_parse(world.engine, world.cfg, world.ind)
    result = stage_parse(world.engine, world.cfg, world.ind, runner=runner, repair=True)
    assert "1 repair attempts (0 fully repaired)" in result.detail
    with session_scope(world.engine) as s:
        assert [r.run_id for r in pending_repairs(s)] == [rid]  # still allowed: no reply was got
        rep = s.scalar(select(Run).where(Run.run_id == rid + REPAIR_SUFFIX))
        assert rep.status == "failed"
    runner.replies[rid + REPAIR_SUFFIX] = [good_item(c, labels) for c in codes]
    stage_parse(world.engine, world.cfg, world.ind, runner=runner, repair=True)
    with session_scope(world.engine) as s:
        assert s.scalar(select(Run.parse_status).where(Run.run_id == rid)) == "repaired"


def test_repairs_made_elsewhere_are_applied_by_apply_repairs(mini):
    """A manual repair is imported as a run first and applied on the next parse."""
    world, runs, codes = mini
    labels = world.ind.driver_labels
    first = runs[0]
    rid = first.planned.run_id
    bad = [good_item(c, labels) for c in codes]
    bad[2]["t2_class"] = "Maybe"
    runner = CannedRunner({rid: bad, rid + REPAIR_SUFFIX: [good_item(c, labels) for c in codes]})
    execute(world, runner, first)
    stage_parse(world.engine, world.cfg, world.ind)
    with session_scope(world.engine) as s:
        original = s.scalar(select(Run).where(Run.run_id == rid))
        from gauge.parse.repair import failed_companies, planned_from_row

        planned = planned_from_row(s, original)
        assert list(failed_companies(s, original)) == [codes[2]]
        from dataclasses import replace

        repair_plan = replace(planned, run_id=rid + REPAIR_SUFFIX)
        execute_run(
            s,
            world.cfg,
            runner,
            repair_plan,
            original.prompt_text + correction_notice({codes[2]: "x"}),
            system_prompt=original.system_prompt_text,
            repair_of=original,
        )
        assert apply_repairs(s, world.cfg, labels) == [(rid, True)]
        assert original.parse_status == "repaired"
        assert apply_repairs(s, world.cfg, labels) == []  # idempotent


def test_run_company_codes_follow_the_prompt_order(mini):
    world, runs, codes = mini
    runner = CannedRunner({}, default=[good_item(c, world.ind.driver_labels) for c in codes])
    execute(world, runner, runs[0])
    with session_scope(world.engine) as s:
        run = s.scalar(select(Run).where(Run.run_id == runs[0].planned.run_id))
        assert run_company_codes(s, run) == list(runs[0].planned.company_order)


def test_run_repairs_stops_at_a_usage_limit(mini):
    world, runs, codes = mini
    labels = world.ind.driver_labels
    bad = [good_item(c, labels) for c in codes]
    bad[0]["t3_rating"] = 9
    reps = {rp.planned.run_id: bad for rp in runs[:2]}
    runner = CannedRunner(reps, usage_limit_on={r + REPAIR_SUFFIX for r in reps})
    for rp in runs[:2]:
        execute(world, runner, rp)
    stage_parse(world.engine, world.cfg, world.ind)
    with session_scope(world.engine) as s:
        summary = run_repairs(s, world.cfg, runner, labels)
    assert summary.usage_limit and summary.attempted == 1  # stopped cleanly after the first
    assert summary.repaired == 0
