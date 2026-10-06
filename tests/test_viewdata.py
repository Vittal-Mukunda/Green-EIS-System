"""The dashboard's data layer (no browser): queries, annotation writes and annotator agreement."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from gauge import vocab
from gauge.config import load_indicators, load_models, load_study
from gauge.db.models import Annotation, Claim, DisagreementFlag, Judgment
from gauge.db.session import make_engine, session_scope
from gauge.evaluate.standards import load_standards
from gauge.pipeline import run_all_dry
from gauge.viewdata import (
    AnnotationError,
    CompanyRow,
    annotator_agreement,
    audit_runs,
    benchmark_position,
    claims_to_annotate,
    company_flags,
    disagreement_queue,
    display_name,
    evidence_markdown,
    indicator_table,
    judgments_for_company,
    judgments_for_taxonomy,
    kpi_history,
    list_companies,
    report_attributes,
    run_detail,
    save_annotation,
    sdg_relevance,
    search_runs,
)


@pytest.fixture
def dry(proj):
    run_all_dry(root=proj)
    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    yield SimpleNamespace(
        cfg=cfg, ind=load_indicators(cfg), models=load_models(cfg), engine=engine, root=proj
    )
    engine.dispose()


# ---- companies and KPIs ------------------------------------------------------------------------------
def test_companies_are_listed_with_masked_or_real_names(dry):
    with session_scope(dry.engine) as s:
        companies = list_companies(s)
    assert len(companies) == 6 and [c.sector for c in companies] == sorted(
        c.sector for c in companies
    )
    first = companies[0]
    assert first.synthetic and first.status == "included"
    assert display_name(first, real=False) == first.code
    assert display_name(first, real=True) == f"{first.code} ({first.real_name})"
    assert isinstance(first, CompanyRow) and first.real_name.startswith("Synthetic ")


def test_kpi_history_has_every_kpi_and_year(dry):
    with session_scope(dry.engine) as s:
        code = list_companies(s)[0].code
        history = kpi_history(s, code, dry.ind)
    assert set(history["fy"]) == {"FY2022-23", "FY2023-24", "FY2024-25"}
    assert set(history["kpi"]) == {k.code for k in dry.ind.kpis}
    assert len(history) in (14, 15)  # one synthetic gap exists in the sample
    row = history[(history["kpi"] == "water_intensity") & (history["fy"] == "FY2024-25")].iloc[0]
    assert row["label"] == "Water intensity" and row["unit"] == "kL per INR crore"
    assert row["change_2y_pct"] is not None


def test_benchmark_position_places_the_company_against_its_sector(dry):
    with session_scope(dry.engine) as s:
        code = list_companies(s)[0].code
        bench = benchmark_position(s, code, "FY2024-25", dry.ind)
        history = kpi_history(s, code, dry.ind)
    assert len(bench) == 5 and bench["n_sector"].eq(3).all()
    assert (bench["p25"] <= bench["median"]).all() and (bench["median"] <= bench["p75"]).all()
    water = bench[bench["kpi"] == "water_intensity"].iloc[0]
    stored = history[(history["kpi"] == "water_intensity") & (history["fy"] == "FY2024-25")][
        "value"
    ].iloc[0]
    assert water["value"] == pytest.approx(stored) and water["better"] == "lower"
    with session_scope(dry.engine) as s:
        assert benchmark_position(s, "ZZZ-99", "FY2024-25", dry.ind).empty


def test_indicator_table_and_report_attributes(dry):
    with session_scope(dry.engine) as s:
        code = list_companies(s)[0].code
        table = indicator_table(s, code, "FY2024-25", dry.ind)
        attrs = report_attributes(s, code, "FY2024-25")
        missing = report_attributes(s, code, "FY1999-00")
    assert len(table) == 9 and table["indicator"].iloc[0] == "Revenue from operations"
    assert (
        attrs["boundary"] in ("standalone", "consolidated") and attrs["entry_method"] == "synthetic"
    )
    assert missing == {}


def test_quality_flags_and_sdg_relevance(dry):
    with session_scope(dry.engine) as s:
        flagged = [c.code for c in list_companies(s) if len(company_flags(s, c.code))]
        sdg = sdg_relevance(s, dry.ind)
    assert flagged  # the synthetic defects are flagged on some companies
    assert len(sdg) == 13 and set(sdg["sdg"]) == {6, 7, 12, 13}
    assert vocab.SDG_CAPTION == "mapping indicates relevance, not achievement"


# ---- judgments and the queue ---------------------------------------------------------------------------
def test_every_models_output_for_a_company_side_by_side(dry):
    with session_scope(dry.engine) as s:
        code = list_companies(s)[0].code
        out = judgments_for_company(s, code)
    assert len(out) == 20 and set(out["model_key"]) == {"B1", "P1", "P2", "P3", "P4"}
    assert set(out["condition"]) == {"C1", "C2"} and set(out["repetition"]) == {1, 2}
    assert out["valid"].all() and out["justification"].str.len().gt(0).all()
    assert ";" in out["drivers"].iloc[0]  # the three drivers are joined
    with session_scope(dry.engine) as s:
        assert judgments_for_company(s, "ZZZ-99").empty


def test_disagreement_queue_matches_the_stored_flags(dry):
    with session_scope(dry.engine) as s:
        queue = disagreement_queue(s)
        n = s.scalar(select(func.count()).select_from(DisagreementFlag))
    assert len(queue) == n > 0
    assert set(queue["type"]) <= set(vocab.DISAGREEMENT_FLAG_TYPES)
    flips = queue[queue["type"] == "t2_flip"]
    assert flips["model"].notna().all() and "C1=" in flips["detail"].iloc[0]


def test_evidence_shows_the_blocks_models_saw_per_condition(dry):
    with session_scope(dry.engine) as s:
        code = list_companies(s)[0].code
        c1 = evidence_markdown(s, dry.cfg, dry.ind, code, "C1")
        c2 = evidence_markdown(s, dry.cfg, dry.ind, code, "C2")
    assert c1.startswith(f"## {code}") and "Context for" not in c1
    assert c2.startswith(c1) and f"Context for {code}" in c2


# ---- annotation ----------------------------------------------------------------------------------------
def test_claims_to_annotate_and_saving(dry):
    with session_scope(dry.engine) as s:
        todo = claims_to_annotate(s, "alice")
        total = s.scalar(select(func.count()).select_from(Claim))
    assert len(todo) == total == 240 and set(todo["automatic_status"]) == {"pending_annotation"}
    assert {"claim_id", "company", "model", "clause", "indicator"} <= set(todo.columns)
    first = int(todo.iloc[0]["claim_id"])
    with session_scope(dry.engine) as s:
        row = save_annotation(s, annotator="alice", kind="claim_support", label="supported",
                              claim_id=first, note="matches the table")  # fmt: skip
        judgment_id = s.scalar(select(Claim.judgment_id).where(Claim.id == first))
        assert row.judgment_id == judgment_id  # inferred from the claim
        assert len(claims_to_annotate(s, "alice")) == 239  # done for alice ...
        assert len(claims_to_annotate(s, "bob")) == 240  # ... not for bob
        assert len(claims_to_annotate(s, "alice", include_done=True)) == 240


def test_saving_twice_updates_one_row_per_annotator(dry):
    with session_scope(dry.engine) as s:
        claim_id = int(claims_to_annotate(s, "alice").iloc[0]["claim_id"])
        save_annotation(
            s, annotator="alice", kind="claim_support", label="supported", claim_id=claim_id
        )
        save_annotation(
            s, annotator="alice", kind="claim_support", label="wrong", claim_id=claim_id, note="n"
        )
        save_annotation(
            s, annotator="bob", kind="claim_support", label="supported", claim_id=claim_id
        )
        rows = list(s.scalars(select(Annotation).where(Annotation.claim_id == claim_id)))
    assert sorted((r.annotator, r.label) for r in rows) == [
        ("alice", "wrong"),
        ("bob", "supported"),
    ]
    assert next(r for r in rows if r.annotator == "alice").note == "n"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (dict(kind="claim_support", label="maybe", claim_id=1), "not a claim_support label"),
        (dict(kind="taxonomy", label="supported", judgment_id=1), "not a taxonomy label"),
        (dict(kind="other", label="supported", claim_id=1), "unknown annotation kind"),
        (dict(kind="claim_support", label="supported"), "needs a claim or a judgment"),
        (dict(kind="claim_support", label="supported", judgment_id=1), "target a claim"),
        (dict(kind="taxonomy", label="objective_error", claim_id=1), "target a judgment"),
        (
            dict(kind="taxonomy", label="objective_error", claim_id=1, judgment_id=1),
            "target a judgment",
        ),
    ],
)
def test_invalid_annotations_are_refused(dry, kwargs, message):
    with session_scope(dry.engine) as s, pytest.raises(AnnotationError, match=message):
        save_annotation(s, annotator="alice", **kwargs)


def test_an_annotator_name_is_required(dry):
    with session_scope(dry.engine) as s, pytest.raises(AnnotationError, match="annotator name"):
        save_annotation(s, annotator="  ", kind="taxonomy", label="objective_error", judgment_id=1)


def test_taxonomy_queue_suggests_automatic_categories_and_hides_done_items(dry):
    with session_scope(dry.engine) as s:
        truth = {c: r.t2_class for c, r in load_standards(s, dry.cfg, dry.ind).t2.items()}
        todo = judgments_for_taxonomy(s, "alice", truth)
        wrong = int(
            s.scalar(
                select(func.count()).select_from(Judgment).where(Judgment.parse_status == "ok")
            )
            or 0
        )
    assert wrong == 120 and not todo.empty
    assert set(todo["automatic_suggestion"]) <= {
        "objective_error",
        "unsupported_claim",
        "models_disagree",
    }
    errors = todo[todo["automatic_suggestion"] == "objective_error"]
    assert (
        errors["t2_class"] != errors["rule_class"]
    ).all()  # exactly the judgments with a wrong class
    with session_scope(dry.engine) as s:
        jid = int(todo.iloc[0]["judgment_id"])
        save_annotation(
            s,
            annotator="alice",
            kind="taxonomy",
            label="interpretation_difference",
            judgment_id=jid,
        )
        again = judgments_for_taxonomy(s, "alice", truth)
        assert jid not in set(again["judgment_id"]) and len(again) == len(todo) - 1
        assert jid in set(judgments_for_taxonomy(s, "bob", truth)["judgment_id"])


def test_annotator_agreement_is_cohens_kappa_over_shared_items(dry):
    with session_scope(dry.engine) as s:
        ids = [int(i) for i in claims_to_annotate(s, "x")["claim_id"].head(4)]
        a = ["supported", "supported", "unsupported", "unsupported"]
        b = ["supported", "supported", "unsupported", "supported"]
        for claim_id, la, lb in zip(ids, a, b, strict=True):
            save_annotation(s, annotator="alice", kind="claim_support", label=la, claim_id=claim_id)
            save_annotation(s, annotator="bob", kind="claim_support", label=lb, claim_id=claim_id)
        lonely = int(claims_to_annotate(s, "x")["claim_id"].iloc[10])  # labelled by alice only
        save_annotation(s, annotator="alice", kind="claim_support", label="wrong", claim_id=lonely)
        result = annotator_agreement(s, "claim_support")
        empty = annotator_agreement(s, "taxonomy")
    # po = 3/4; alice labels half/half, bob 3/1: pe = (2*3 + 2*1) / 16 = .5; kappa = (.75 - .5) / .5
    assert result["annotators"] == ["alice", "bob"] and result["n_both"] == 4
    assert result["agreement"] == 0.75 and result["kappa"] == pytest.approx(0.5)
    assert empty["n_both"] == 0 and empty["kappa"] != empty["kappa"]  # NaN


# ---- audit trail ------------------------------------------------------------------------------------------
def test_audit_table_search_and_detail(dry):
    with session_scope(dry.engine) as s:
        runs = audit_runs(s)
        detail = run_detail(s, "P1_C2_r1")
        unknown = run_detail(s, "NOPE")
    assert len(runs) == 25 and {"run_id", "model", "status", "prompt_sha256", "mode"} <= set(
        runs.columns
    )
    assert set(runs["mode"]) == {"mock"} and runs["is_repair"].sum() == 5
    assert set(search_runs(runs, "p1_c2")["run_id"]) == {"P1_C2_r1", "P1_C2_r2"}
    assert len(search_runs(runs, "  ")) == 25 and search_runs(runs, "no-such-text").empty
    assert len(search_runs(runs, "__repair")) == 5
    assert detail["run_id"] == "P1_C2_r1" and len(detail["prompt_sha256"]) == 64
    assert "mock-runner" in detail["command"] and "# Instructions" in detail["prompt_text"]
    assert unknown is None
