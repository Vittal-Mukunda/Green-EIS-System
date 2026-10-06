from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, StatementError

from gauge.db.base import Base
from gauge.db.ddl import generate_ddl
from gauge.db.models import (
    Annotation,
    Claim,
    Company,
    Condition,
    Judgment,
    KpiValue,
    Model,
    QualityFlag,
    Run,
    Sector,
)
from gauge.db.session import init_db, make_engine, session_scope

# The 19 tables of spec §7 plus quality_flag (documented in db/models.py).
SPEC_TABLES = {
    "sector",
    "company",
    "report",
    "indicator_value",
    "kpi_value",
    "sector_benchmark",
    "sdg_mapping",
    "rule",
    "condition",
    "prompt_template",
    "model",
    "run",
    "run_company_position",
    "judgment",
    "claim",
    "evaluation_result",
    "transition_result",
    "annotation",
    "disagreement_flag",
}


@pytest.fixture
def engine():
    eng = make_engine("sqlite:///:memory:")
    init_db(eng)
    yield eng
    eng.dispose()


def _sector(session) -> Sector:
    s = Sector(code="SYA", name="Synthetic Alpha")
    session.add(s)
    session.flush()
    return s


def _company(session, code="SYA-01", **kw) -> Company:
    s = session.query(Sector).first() or _sector(session)
    c = Company(code=code, real_name=f"Synthetic {code}", sector_id=s.id, **kw)
    session.add(c)
    session.flush()
    return c


def test_all_spec_tables_exist(engine):
    names = set(inspect(engine).get_table_names())
    assert names == SPEC_TABLES | {"quality_flag"}


def test_run_table_has_every_rule_5_field():
    cols = {c.name for c in Run.__table__.columns}
    required = {
        "run_id",
        "started_utc",
        "cli_version",
        "model_id",
        "condition_id",
        "repetition",
        "seed",
        "command",
        "prompt_text",
        "prompt_sha256",
        "stdout",
        "stderr",
        "exit_code",
        "duration_s",
        "mode",
        "raw_path",
    }
    assert required <= cols
    # §2.12 API parameters
    assert {
        "temperature",
        "top_p",
        "max_tokens",
        "api_seed",
        "provider_model",
        "request_json",
        "response_json",
        "rate_limit_headers",
        "system_prompt_text",
    } <= cols


def test_company_masked_code_and_real_name_are_separate_columns():
    cols = {c.name for c in Company.__table__.columns}
    assert {"code", "real_name"} <= cols


def test_foreign_keys_enforced_on_sqlite(engine):
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        session.add(Company(code="SYA-01", real_name="x", sector_id=999))


def test_excluded_company_needs_a_reason(engine):
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        _company(session, selection_status="excluded")
    with session_scope(engine) as session:
        _company(session, selection_status="excluded", exclusion_reason="no FY2022-23 BRSR filing")


def test_decimal_round_trips_exactly(engine):
    value = Decimal("12345678.123456789012")
    with session_scope(engine) as session:
        c = _company(session)
        session.add(
            KpiValue(
                company_id=c.id,
                fy="FY2024-25",
                kpi="x",
                value=value,
                change_2y_pct=Decimal("-0.1"),
                engine_version="t",
            )
        )
    with session_scope(engine) as session:
        row = session.query(KpiValue).one()
        assert row.value == value and isinstance(row.value, Decimal)
        assert row.change_2y_pct == Decimal("-0.1")


def test_decimal_column_refuses_float(engine):
    with pytest.raises(StatementError, match="refuses float"), session_scope(engine) as session:
        c = _company(session)
        session.add(
            KpiValue(company_id=c.id, fy="FY2024-25", kpi="x", value=0.1, engine_version="t")
        )


def test_datetimes_are_utc_aware_and_naive_is_refused(engine):
    ist = timezone(timedelta(hours=5, minutes=30))
    stamp = datetime(2026, 1, 1, 12, 0, tzinfo=ist)
    with session_scope(engine) as session:
        c = _company(session)
        session.add(
            QualityFlag(
                company_id=c.id, rule="r", severity="warning", message="m", created_utc=stamp
            )
        )
    with session_scope(engine) as session:
        back = session.query(QualityFlag).one().created_utc
        assert back.tzinfo is not None and back == stamp and back.utcoffset() == timedelta(0)
    with pytest.raises(StatementError, match="naive"), session_scope(engine) as session:
        c = session.query(Company).one()
        session.add(
            QualityFlag(
                company_id=c.id,
                rule="r",
                severity="warning",
                message="m",
                created_utc=datetime(2026, 1, 1),
            )
        )


def test_enum_like_checks(engine):
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        session.add(Condition(code="C3", description="d"))
        session.add(Model(key="P1", role="wizard", channel="cursor", vendor="v", name="n"))


def _run(session, model, cond, **kw) -> Run:
    r = Run(
        run_id=kw.pop("run_id", "P1_C1_r1"),
        model_id=model.id,
        condition_id=cond.id,
        repetition=kw.pop("repetition", 1),
        seed=1,
        mode="mock",
        **kw,
    )
    session.add(r)
    session.flush()
    return r


def test_run_uniqueness_and_repair_separation(engine):
    with session_scope(engine) as session:
        m = Model(key="P1", role="primary", channel="mock", vendor="v", name="n")
        c = Condition(code="C1", description="d")
        session.add_all([m, c])
        session.flush()
        first = _run(session, m, c)
        _run(session, m, c, run_id="P1_C1_r1__repair", is_repair=True, repair_of_run_id=first.id)
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        m = session.query(Model).one()
        c = session.query(Condition).one()
        _run(
            session, m, c, run_id="duplicate_cell"
        )  # same (model, condition, variant, rep, repair)


def test_judgment_value_checks(engine):
    with session_scope(engine) as session:
        m = Model(key="P1", role="primary", channel="mock", vendor="v", name="n")
        cond = Condition(code="C1", description="d")
        session.add_all([m, cond])
        session.flush()
        run = _run(session, m, cond)
        comp = _company(session)
        ids = (run.id, comp.id)
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        session.add(Judgment(run_id=ids[0], company_id=ids[1], parse_status="ok", t3_rating=6))
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        session.add(Judgment(run_id=ids[0], company_id=ids[1], parse_status="ok", t2_class="Great"))


def test_annotation_one_label_per_annotator_per_target(engine):
    with session_scope(engine) as session:
        m = Model(key="P1", role="primary", channel="mock", vendor="v", name="n")
        cond = Condition(code="C1", description="d")
        session.add_all([m, cond])
        session.flush()
        run = _run(session, m, cond)
        comp = _company(session)
        j = Judgment(run_id=run.id, company_id=comp.id, parse_status="ok")
        session.add(j)
        session.flush()
        cl = Claim(
            judgment_id=j.id,
            clause_index=0,
            clause_text="t",
            claim_type="indicator_only",
            status="pending_annotation",
        )
        session.add(cl)
        session.flush()
        session.add(
            Annotation(claim_id=cl.id, annotator="A", kind="claim_support", label="supported")
        )
        session.add(
            Annotation(claim_id=cl.id, annotator="B", kind="claim_support", label="supported")
        )
        session.add(Annotation(judgment_id=j.id, annotator="A", kind="taxonomy", label="ambiguity"))
        ids = (cl.id, j.id)
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        session.add(Annotation(claim_id=ids[0], annotator="A", kind="claim_support", label="wrong"))
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        session.add(Annotation(judgment_id=ids[1], annotator="A", kind="taxonomy", label="other"))
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        session.add(Annotation(annotator="A", kind="taxonomy", label="no target"))


# ---- DDL ---------------------------------------------------------------------------------------
def test_ddl_covers_every_table_in_both_dialects():
    for dialect in ("sqlite", "postgresql"):
        ddl = generate_ddl(dialect)
        for table in Base.metadata.sorted_tables:
            assert f"CREATE TABLE {table.name} " in ddl, (dialect, table.name)


def test_postgres_ddl_uses_numeric_and_sqlite_uses_text():
    pg, lite = generate_ddl("postgresql"), generate_ddl("sqlite")
    assert "NUMERIC(38, 12)" in pg and "NUMERIC(38, 12)" not in lite
    assert "TIMESTAMP WITH TIME ZONE" in pg


def test_ddl_is_deterministic():
    assert generate_ddl("postgresql") == generate_ddl("postgresql")


def test_committed_schema_files_are_current(repo_root):
    """docs/schema*.sql must match models.py; regenerate with `gauge init-db --ddl-only`."""
    for dialect, name in (("sqlite", "schema.sql"), ("postgresql", "schema_postgres.sql")):
        committed = (repo_root / "docs" / name).read_text(encoding="utf-8")
        assert committed == generate_ddl(dialect), f"docs/{name} is stale"
