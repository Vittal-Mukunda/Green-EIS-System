"""SQLAlchemy 2.x schema (spec §7). Portable to PostgreSQL: no ENUM types, no SQLite-only features.

Tables: the 19 listed in §7 plus `quality_flag` (§6.5 validators and the §9.1 dashboard view need a
place to store flags). Constraint names come from `Base.metadata.naming_convention`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gauge import vocab
from gauge.db.base import Base, DecimalValue, UTCDateTime, in_values, utcnow

FK_SECTOR = "sector.id"
FK_COMPANY = "company.id"
FK_REPORT = "report.id"
FK_MODEL = "model.id"
FK_CONDITION = "condition.id"
FK_RUN = "run.id"
FK_JUDGMENT = "judgment.id"
FK_CLAIM = "claim.id"


# ---------------------------------------------------------------------------------------------
# Data: sample, filings, indicators, KPIs
# ---------------------------------------------------------------------------------------------
class Sector(Base):
    __tablename__ = "sector"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(3), unique=True)  # masking prefix, e.g. CEM
    name: Mapped[str] = mapped_column(String(64), unique=True)


class Company(Base):
    """`code` is the masked identifier shown to models; `real_name` never leaves the DB (rule 9)."""

    __tablename__ = "company"
    __table_args__ = (
        in_values("selection_status", vocab.SELECTION_STATUSES, "selection_status"),
        CheckConstraint(
            "selection_status <> 'excluded' OR exclusion_reason IS NOT NULL",
            name="exclusion_reason",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    real_name: Mapped[str] = mapped_column(String(200))
    nse_symbol: Mapped[str | None] = mapped_column(String(32))
    isin: Mapped[str | None] = mapped_column(String(12), unique=True)
    sector_id: Mapped[int] = mapped_column(ForeignKey(FK_SECTOR), index=True)
    market_cap_inr_cr: Mapped[Decimal | None] = mapped_column(DecimalValue)
    market_cap_as_of: Mapped[date | None] = mapped_column(Date)
    selection_status: Mapped[str] = mapped_column(String(12), default="candidate")
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class Report(Base):
    """One company-year BRSR filing, with provenance (§6.3)."""

    __tablename__ = "report"
    __table_args__ = (
        UniqueConstraint("company_id", "fy"),
        in_values("boundary", vocab.BOUNDARIES, "boundary", nullable=True),
        in_values("entry_method", vocab.ENTRY_METHODS, "entry_method"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey(FK_COMPANY), index=True)
    fy: Mapped[str] = mapped_column(String(8))
    boundary: Mapped[str | None] = mapped_column(String(16))
    assured: Mapped[bool | None] = mapped_column(Boolean)
    assurance_note: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_file: Mapped[str | None] = mapped_column(Text)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    retrieved_on: Mapped[date | None] = mapped_column(Date)
    entry_method: Mapped[str] = mapped_column(String(20))


class IndicatorValue(Base):
    __tablename__ = "indicator_value"
    __table_args__ = (UniqueConstraint("report_id", "indicator"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey(FK_REPORT), index=True)
    indicator: Mapped[str] = mapped_column(String(40))  # code from config/indicators.yaml
    value: Mapped[Decimal] = mapped_column(DecimalValue)
    unit: Mapped[str] = mapped_column(String(16))  # canonical unit after standardization
    original_value: Mapped[Decimal | None] = mapped_column(DecimalValue)
    original_unit: Mapped[str | None] = mapped_column(String(32))
    source_url: Mapped[str | None] = mapped_column(Text)
    page_ref: Mapped[str | None] = mapped_column(String(128))
    verified: Mapped[bool | None] = mapped_column(Boolean)  # outcome of verify-sample (§6.4)
    verification_note: Mapped[str | None] = mapped_column(Text)


class QualityFlag(Base):
    """Output of the §6.5 validators; extra to the §7 list, needed by the dashboard (§9.1)."""

    __tablename__ = "quality_flag"
    __table_args__ = (in_values("severity", vocab.FLAG_SEVERITIES, "severity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey(FK_COMPANY), index=True)
    fy: Mapped[str | None] = mapped_column(String(8))
    indicator: Mapped[str | None] = mapped_column(String(40))
    rule: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)
    created_utc: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class KpiValue(Base):
    __tablename__ = "kpi_value"
    __table_args__ = (UniqueConstraint("company_id", "fy", "kpi"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey(FK_COMPANY), index=True)
    fy: Mapped[str] = mapped_column(String(8))
    kpi: Mapped[str] = mapped_column(String(40))
    value: Mapped[Decimal] = mapped_column(DecimalValue)
    change_2y_pct: Mapped[Decimal | None] = mapped_column(DecimalValue)
    engine_version: Mapped[str] = mapped_column(String(16))


class SectorBenchmark(Base):
    """Median/P25/P75 (and tertile cut-points P33/P67 for the T2 rule) from OUR small sample."""

    __tablename__ = "sector_benchmark"
    __table_args__ = (UniqueConstraint("sector_id", "fy", "kpi"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sector_id: Mapped[int] = mapped_column(ForeignKey(FK_SECTOR), index=True)
    fy: Mapped[str] = mapped_column(String(8))
    kpi: Mapped[str] = mapped_column(String(40))
    n: Mapped[int] = mapped_column(Integer)
    median: Mapped[Decimal] = mapped_column(DecimalValue)
    p25: Mapped[Decimal] = mapped_column(DecimalValue)
    p75: Mapped[Decimal] = mapped_column(DecimalValue)
    p33: Mapped[Decimal] = mapped_column(DecimalValue)
    p67: Mapped[Decimal] = mapped_column(DecimalValue)


class SdgMapping(Base):
    """Informational only; shown in the dashboard with SDG_CAPTION, never given to a model."""

    __tablename__ = "sdg_mapping"
    __table_args__ = (
        UniqueConstraint("indicator_code", "sdg_number"),
        CheckConstraint("sdg_number BETWEEN 1 AND 17", name="sdg_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    indicator_code: Mapped[str] = mapped_column(String(40))
    sdg_number: Mapped[int] = mapped_column(Integer)
    sdg_target: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------------------------
# Registry: rules, conditions, prompt templates, models
# ---------------------------------------------------------------------------------------------
class Rule(Base):
    __tablename__ = "rule"
    __table_args__ = (in_values("kind", vocab.RULE_KINDS, "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(40), unique=True)  # e.g. t2_v1
    kind: Mapped[str] = mapped_column(String(12))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    frozen_utc: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Condition(Base):
    __tablename__ = "condition"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(4), unique=True)  # C1, C2
    description: Mapped[str] = mapped_column(Text)


class PromptTemplate(Base):
    __tablename__ = "prompt_template"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    condition_id: Mapped[int | None] = mapped_column(ForeignKey(FK_CONDITION))  # NULL = shared
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    frozen_utc: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Model(Base):
    __tablename__ = "model"
    __table_args__ = (
        in_values("role", vocab.ROLES, "role"),
        in_values("channel", vocab.CHANNELS, "channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(8), unique=True)  # P1..P4, B1, S1
    role: Mapped[str] = mapped_column(String(12))
    channel: Mapped[str] = mapped_column(String(8))
    vendor: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(128))  # exact identifier; never "auto"
    provider: Mapped[str | None] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    listed_by_cli: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------------------------
# Runs and their parsed output
# ---------------------------------------------------------------------------------------------
class Run(Base):
    """One model call: every field of hard rule 5, plus the API parameters of rule 12."""

    __tablename__ = "run"
    __table_args__ = (
        in_values("mode", vocab.RUN_MODES, "mode"),
        in_values("status", vocab.RUN_STATUSES, "status"),
        in_values("parse_status", vocab.PARSE_STATUSES, "parse_status"),
        CheckConstraint("repetition >= 1", name="repetition"),
        UniqueConstraint("model_id", "condition_id", "variant", "repetition", "is_repair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64), unique=True
    )  # e.g. P1_C2_r1 (repair: ..__repair)
    model_id: Mapped[int] = mapped_column(ForeignKey(FK_MODEL), index=True)
    condition_id: Mapped[int] = mapped_column(ForeignKey(FK_CONDITION), index=True)
    variant: Mapped[str] = mapped_column(String(24), default="")  # '' or leave-one-out variant
    repetition: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(8))
    is_repair: Mapped[bool] = mapped_column(Boolean, default=False)
    repair_of_run_id: Mapped[int | None] = mapped_column(ForeignKey(FK_RUN))
    batch_part: Mapped[str | None] = mapped_column(String(32))  # sector code if the batch is split
    status: Mapped[str] = mapped_column(String(12), default="pending")
    parse_status: Mapped[str] = mapped_column(String(14), default="not_parsed")

    created_utc: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_utc: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_utc: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cli_version: Mapped[str | None] = mapped_column(String(64))
    command: Mapped[str | None] = mapped_column(Text)  # exact argv, JSON-encoded

    prompt_path: Mapped[str | None] = mapped_column(Text)
    prompt_text: Mapped[str | None] = mapped_column(Text)
    prompt_sha256: Mapped[str | None] = mapped_column(String(64))
    system_prompt_text: Mapped[str | None] = mapped_column(Text)  # API channel only
    system_prompt_sha256: Mapped[str | None] = mapped_column(String(64))

    raw_path: Mapped[str | None] = mapped_column(Text)
    stdout: Mapped[str | None] = mapped_column(Text)
    stderr: Mapped[str | None] = mapped_column(Text)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Float)

    temperature: Mapped[float | None] = mapped_column(Float)
    top_p: Mapped[float | None] = mapped_column(Float)
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    api_seed: Mapped[int | None] = mapped_column(Integer)
    provider_model: Mapped[str | None] = mapped_column(
        String(128)
    )  # model string the provider returned
    request_json: Mapped[dict | None] = mapped_column(JSON)  # request body minus API key
    response_json: Mapped[dict | None] = mapped_column(JSON)
    rate_limit_headers: Mapped[dict | None] = mapped_column(JSON)


class RunCompanyPosition(Base):
    """Position of each company in a run's prompt (1-based), for the position-effect analysis."""

    __tablename__ = "run_company_position"
    __table_args__ = (
        UniqueConstraint("run_id", "company_id"),
        UniqueConstraint("run_id", "position"),
        CheckConstraint("position >= 1", name="position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(FK_RUN), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey(FK_COMPANY))
    position: Mapped[int] = mapped_column(Integer)


class Judgment(Base):
    """Parsed per-company output. Unit of analysis: (model, condition, repetition, company)."""

    __tablename__ = "judgment"
    __table_args__ = (
        UniqueConstraint("run_id", "company_id"),
        in_values("t2_class", vocab.T2_CLASSES, "t2_class", nullable=True),
        in_values("parse_status", ("ok", "parse_failure"), "parse_status"),
        CheckConstraint("t3_rating IS NULL OR t3_rating BETWEEN 1 AND 5", name="t3_rating"),
        CheckConstraint(
            "t3_confidence IS NULL OR t3_confidence BETWEEN 1 AND 5", name="t3_confidence"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(FK_RUN), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey(FK_COMPANY), index=True)
    parse_status: Mapped[str] = mapped_column(String(14))
    parse_error: Mapped[str | None] = mapped_column(Text)
    t2_class: Mapped[str | None] = mapped_column(String(8))
    t3_rating: Mapped[int | None] = mapped_column(Integer)
    t3_confidence: Mapped[int | None] = mapped_column(Integer)
    top_drivers: Mapped[list | None] = mapped_column(JSON)
    justification: Mapped[str | None] = mapped_column(Text)
    insufficient_evidence: Mapped[bool | None] = mapped_column(Boolean)


class Claim(Base):
    """A clause of a justification that contains a number or names an indicator (§5 Grounding)."""

    __tablename__ = "claim"
    __table_args__ = (
        UniqueConstraint("judgment_id", "clause_index"),
        in_values("claim_type", vocab.CLAIM_TYPES, "claim_type"),
        in_values("status", vocab.CLAIM_STATUSES, "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    judgment_id: Mapped[int] = mapped_column(ForeignKey(FK_JUDGMENT), index=True)
    clause_index: Mapped[int] = mapped_column(Integer)
    clause_text: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(16))
    indicator_code: Mapped[str | None] = mapped_column(String(40))
    claimed_value: Mapped[Decimal | None] = mapped_column(DecimalValue)
    matched_value: Mapped[Decimal | None] = mapped_column(DecimalValue)
    status: Mapped[str] = mapped_column(String(20))


# ---------------------------------------------------------------------------------------------
# Evaluation outputs
# ---------------------------------------------------------------------------------------------
class EvaluationResult(Base):
    """Tidy long table: one metric value (optionally with CI) per row, at any scope."""

    __tablename__ = "evaluation_result"

    id: Mapped[int] = mapped_column(primary_key=True)
    eval_version: Mapped[str] = mapped_column(String(16))
    metric: Mapped[str] = mapped_column(String(60), index=True)
    scope: Mapped[str] = mapped_column(
        String(16)
    )  # judgment|model_condition|model|condition|panel|baseline
    model_id: Mapped[int | None] = mapped_column(ForeignKey(FK_MODEL))
    condition_id: Mapped[int | None] = mapped_column(ForeignKey(FK_CONDITION))
    company_id: Mapped[int | None] = mapped_column(ForeignKey(FK_COMPANY))
    judgment_id: Mapped[int | None] = mapped_column(ForeignKey(FK_JUDGMENT))
    repetition: Mapped[int | None] = mapped_column(Integer)
    value: Mapped[float | None] = mapped_column(Float)
    ci_low: Mapped[float | None] = mapped_column(Float)
    ci_high: Mapped[float | None] = mapped_column(Float)
    n: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict | None] = mapped_column(JSON)
    computed_utc: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TransitionResult(Base):
    """C1->C2 transition for one (model, company, repetition), labelled by the T3 update rule."""

    __tablename__ = "transition_result"
    __table_args__ = (
        UniqueConstraint("model_id", "company_id", "repetition", "variant"),
        in_values("label", vocab.TRANSITION_LABELS, "label"),
        in_values("expected_direction", vocab.EXPECTED_DIRECTIONS, "expected_direction"),
        CheckConstraint("trend_signal IN (-1, 0, 1)", name="trend_signal"),
        CheckConstraint("benchmark_signal IN (-1, 0, 1)", name="benchmark_signal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey(FK_MODEL), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey(FK_COMPANY), index=True)
    repetition: Mapped[int] = mapped_column(Integer)
    variant: Mapped[str] = mapped_column(String(24), default="")
    c1_judgment_id: Mapped[int] = mapped_column(ForeignKey(FK_JUDGMENT))
    c2_judgment_id: Mapped[int] = mapped_column(ForeignKey(FK_JUDGMENT))
    trend_signal: Mapped[int] = mapped_column(Integer)
    benchmark_signal: Mapped[int] = mapped_column(Integer)
    expected_direction: Mapped[str] = mapped_column(String(4))
    delta_rating: Mapped[int | None] = mapped_column(Integer)  # rating(C2) - rating(C1)
    label: Mapped[str] = mapped_column(String(14))
    t2_changed: Mapped[bool | None] = mapped_column(Boolean)  # T2 class differs C1 vs C2 (an error)


class Annotation(Base):
    """Human labels (2 annotators; Cohen's kappa). Targets a claim or a whole judgment."""

    __tablename__ = "annotation"
    __table_args__ = (
        in_values("kind", vocab.ANNOTATION_KINDS, "kind"),
        CheckConstraint("claim_id IS NOT NULL OR judgment_id IS NOT NULL", name="target"),
        # One label per annotator per target: two partial unique indexes, since NULLs never collide.
        Index(
            "uq_annotation_claim_annotator_kind",
            "claim_id",
            "annotator",
            "kind",
            unique=True,
            sqlite_where=text("claim_id IS NOT NULL"),
            postgresql_where=text("claim_id IS NOT NULL"),
        ),
        Index(
            "uq_annotation_judgment_annotator_kind",
            "judgment_id",
            "annotator",
            "kind",
            unique=True,
            sqlite_where=text("claim_id IS NULL"),
            postgresql_where=text("claim_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    judgment_id: Mapped[int | None] = mapped_column(ForeignKey(FK_JUDGMENT))
    claim_id: Mapped[int | None] = mapped_column(ForeignKey(FK_CLAIM))
    annotator: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    created_utc: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DisagreementFlag(Base):
    __tablename__ = "disagreement_flag"
    __table_args__ = (in_values("flag_type", vocab.DISAGREEMENT_FLAG_TYPES, "flag_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey(FK_COMPANY), index=True)
    condition_id: Mapped[int | None] = mapped_column(ForeignKey(FK_CONDITION))
    model_id: Mapped[int | None] = mapped_column(ForeignKey(FK_MODEL))
    repetition: Mapped[int | None] = mapped_column(Integer)
    flag_type: Mapped[str] = mapped_column(String(24))
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_utc: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
