"""The EIS views (overview, exception report, filings register, verification) and the dashboard
config that selects them. Data-layer tests use a hand-built database with literal expectations."""

from __future__ import annotations

import math
import sys
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import select
from streamlit.testing.v1 import AppTest

from gauge.config import ConfigError, load_study
from gauge.db.models import (
    Company,
    IndicatorValue,
    KpiValue,
    QualityFlag,
    Report,
    Sector,
    SectorBenchmark,
)
from gauge.db.session import session_scope
from gauge.viewdata import (
    VerificationError,
    filings_register,
    flag_register,
    headline_counts,
    indicator_lineage,
    kpi_years,
    record_verification,
    sector_overview,
)

FY = "FY2024-25"
EIS_PAGES = [
    "Home",
    "Sectors",
    "KPI scorecard",
    "Companies",
    "Compare companies",
    "Query and chart",
    "Compliance check",
    "Data quality register",
    "Sources and filings",
    "Data verification",
    "Metrics guide",
    "About",
]
SHA = "ab" * 32


@pytest.fixture
def mini(db):
    """Two sectors, four companies, two filings, three flags.

    Test Alpha: XAA-01, XAA-02, XAA-03. Test Beta: XBB-01.
    Emissions intensity (lower is better): 10, 30, 20 and 500; median of Test Alpha is 20.
    Renewable share (higher is better): 5, 25, 15 for Test Alpha; no benchmark for it.
    """
    with session_scope(db.engine) as s:
        alpha = Sector(code="XAA", name="Test Alpha")
        beta = Sector(code="XBB", name="Test Beta")
        s.add_all([alpha, beta])
        s.flush()
        companies = {
            code: Company(code=code, real_name=f"{code} Ltd", sector_id=sector.id)
            for code, sector in (
                ("XAA-01", alpha),
                ("XAA-02", alpha),
                ("XAA-03", alpha),
                ("XBB-01", beta),
            )
        }
        s.add_all(companies.values())
        s.flush()
        for code, emissions, renewable in (
            ("XAA-01", 10, 5),
            ("XAA-02", 30, 25),
            ("XAA-03", 20, 15),
        ):
            s.add(
                KpiValue(
                    company_id=companies[code].id,
                    fy=FY,
                    kpi="emissions_intensity",
                    value=Decimal(emissions),
                    engine_version="t",
                )
            )
            s.add(
                KpiValue(
                    company_id=companies[code].id,
                    fy=FY,
                    kpi="renewable_share",
                    value=Decimal(renewable),
                    engine_version="t",
                )
            )
        s.add(
            KpiValue(
                company_id=companies["XBB-01"].id,
                fy=FY,
                kpi="emissions_intensity",
                value=Decimal(500),
                engine_version="t",
            )
        )
        s.add(
            SectorBenchmark(
                sector_id=alpha.id,
                fy=FY,
                kpi="emissions_intensity",
                n=3,
                median=Decimal(20),
                p25=Decimal(15),
                p75=Decimal(25),
                p33=Decimal(17),
                p67=Decimal(23),
            )
        )
        first = Report(
            company_id=companies["XAA-01"].id,
            fy=FY,
            boundary="standalone",
            assured=True,
            source_file="data/raw/xbrl/A1.xml",
            file_sha256=SHA,
            retrieved_on=date(2026, 10, 2),
            entry_method="xbrl",
        )
        second = Report(company_id=companies["XAA-02"].id, fy=FY, entry_method="xbrl")
        s.add_all([first, second])
        s.flush()
        s.add(
            IndicatorValue(
                report_id=first.id,
                indicator="scope1_emissions",
                value=Decimal(1500),
                unit="tCO2e",
                page_ref="Scope1 [label]",
                verified=True,
                verification_note="looked right",
            )
        )
        s.add(
            IndicatorValue(
                report_id=first.id,
                indicator="revenue_from_operations",
                value=Decimal(100),
                unit="INR_crore",
                original_value=Decimal(10**9),
                original_unit="INR",
                page_ref="Revenue [magnitude]",
            )
        )
        s.add_all(
            [
                QualityFlag(
                    company_id=companies["XAA-01"].id,
                    fy=FY,
                    rule="recovered_le_generated",
                    severity="error",
                    message="XAA-01: recovered exceeds generated",
                ),
                QualityFlag(
                    company_id=companies["XAA-02"].id,
                    fy=FY,
                    rule="xbrl_override_applied",
                    severity="warning",
                    message="XAA-02: unit override",
                ),
                QualityFlag(
                    company_id=companies["XBB-01"].id,
                    fy="FY2022-23",
                    rule="missing_indicator",
                    severity="error",
                    message="XBB-01: no report",
                ),
            ]
        )
    return db


# ---- data layer ----------------------------------------------------------------------
def test_headline_counts(mini):
    with session_scope(mini.engine) as s:
        assert headline_counts(s) == {
            "companies": 4,
            "filings": 2,
            "indicator values": 2,
            "KPI values": 7,
            "errors": 2,
            "warnings": 1,
            "values checked by a person": 1,
        }
        assert kpi_years(s) == [FY]


def test_overview_ranks_within_a_sector_in_the_direction_the_kpi_prefers(mini):
    with session_scope(mini.engine) as s:
        emissions = sector_overview(s, FY, "emissions_intensity", mini.ind)
        renewable = sector_overview(s, FY, "renewable_share", mini.ind)
    # Lower is better: 10 -> rank 1, 20 -> 2, 30 -> 3; the lone Test Beta company is its own rank 1.
    assert list(emissions["code"]) == ["XAA-01", "XAA-03", "XAA-02", "XBB-01"]
    assert list(emissions["rank in sector"]) == [1, 2, 3, 1]
    # Median 20: 10 is better, 20 is at the median, 30 is worse, Test Beta has no benchmark.
    assert list(emissions["vs sector median"]) == ["better", "at median", "worse", "n/a"]
    assert list(emissions["sector median"][:3]) == [20.0, 20.0, 20.0]
    assert math.isnan(emissions["sector median"][3])
    # Higher is better: 25 -> rank 1, 15 -> 2, 5 -> 3; no benchmark, so no comparison.
    assert list(renewable["code"]) == ["XAA-02", "XAA-03", "XAA-01"]
    assert list(renewable["rank in sector"]) == [1, 2, 3]
    # no stored benchmark is needed: the median of the three loaded companies is 15
    assert list(renewable["vs sector median"]) == ["better", "at median", "worse"]


def test_overview_is_empty_not_an_error_when_a_year_has_no_values(mini):
    with session_scope(mini.engine) as s:
        assert sector_overview(s, "FY1999-00", "emissions_intensity", mini.ind).empty


def test_the_flag_register_lists_errors_first_then_by_rule(mini):
    with session_scope(mini.engine) as s:
        flags = flag_register(s)
    assert list(zip(flags["code"], flags["rule"], flags["severity"], strict=True)) == [
        ("XBB-01", "missing_indicator", "error"),
        ("XAA-01", "recovered_le_generated", "error"),
        ("XAA-02", "xbrl_override_applied", "warning"),
    ]
    assert list(flags["sector"]) == ["Test Beta", "Test Alpha", "Test Alpha"]


def test_the_filings_register_carries_provenance_and_counts_values(mini):
    with session_scope(mini.engine) as s:
        register = filings_register(s)
    assert list(register["code"]) == ["XAA-01", "XAA-02"]
    first, second = (register.iloc[0], register.iloc[1])
    assert (first["SHA-256"], first["source file"], first["assured"]) == (
        SHA,
        "data/raw/xbrl/A1.xml",
        True,
    )
    assert (first["values"], first["checked"]) == (2, 1)
    assert (second["values"], second["checked"]) == (0, 0)  # a filing with no values still lists


def test_lineage_shows_the_value_beside_what_the_filing_stated(mini):
    with session_scope(mini.engine) as s:
        lineage = indicator_lineage(s, "XAA-01", FY, mini.ind)
    # Catalogue order: revenue comes before Scope 1.
    assert list(lineage["indicator"]) == ["Revenue from operations", "Scope 1 emissions"]
    revenue, scope1 = lineage.iloc[0], lineage.iloc[1]
    assert (revenue["value"], revenue["unit"]) == (100.0, "INR_crore")
    assert (revenue["as filed"], revenue["as-filed unit"]) == (1e9, "INR")
    assert revenue["review"] == "not yet checked"
    assert pd.isna(scope1["as filed"])
    assert scope1["review"] == "ok: looked right"


# ---- the one write: a person's check of a value ----------------------------------------
def _item(engine, indicator="revenue_from_operations") -> int:
    with session_scope(engine) as s:
        return (
            s.scalars(select(IndicatorValue).where(IndicatorValue.indicator == indicator)).one().id
        )


def test_a_verification_records_the_decision_who_made_it_and_when(mini):
    item = _item(mini.engine)
    with session_scope(mini.engine) as s:
        record_verification(s, item_id=item, reviewer="  Asha ", result="ok")
    today = datetime.now(UTC).date().isoformat()
    with session_scope(mini.engine) as s:
        iv = s.get(IndicatorValue, item)
        assert iv.verified is True
        assert iv.verification_note == f"checked by Asha via the dashboard on {today}"


def test_an_error_needs_a_reason_and_keeps_it(mini):
    item = _item(mini.engine)
    with session_scope(mini.engine) as s, pytest.raises(VerificationError, match="what is wrong"):
        record_verification(s, item_id=item, reviewer="Asha", result="error", note="  ")
    with session_scope(mini.engine) as s:
        assert s.get(IndicatorValue, item).verified is None  # the refusal changed nothing
        record_verification(s, item_id=item, reviewer="Asha", result="error", note="PDF says 90")
    with session_scope(mini.engine) as s:
        iv = s.get(IndicatorValue, item)
        assert iv.verified is False
        assert iv.verification_note.startswith("PDF says 90 (checked by Asha")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"reviewer": " ", "result": "ok"}, "enter your name"),
        ({"reviewer": "Asha", "result": "maybe"}, "ok or error"),
        ({"reviewer": "Asha", "result": "ok", "item_id": 987654}, "no stored value"),
    ],
)
def test_a_verification_that_cannot_be_traced_or_found_is_refused(mini, kwargs, message):
    arguments = {"item_id": _item(mini.engine), **kwargs}
    with session_scope(mini.engine) as s, pytest.raises(VerificationError, match=message):
        record_verification(s, **arguments)


# ---- config ------------------------------------------------------------------------------
def _config_with(proj, name: str, extra: str) -> str:
    base = (proj / "config" / "study_dry.yaml").read_text(encoding="utf-8")
    (proj / "config" / name).write_text(base.rstrip("\n") + "\n" + extra, encoding="utf-8")
    return f"config/{name}"


def test_the_default_offers_every_view(dry_cfg):
    assert dry_cfg.dashboard_views == [
        *EIS_PAGES,
        "Model reliability scorecard",
        "C1 vs C2",
        "Disagreement queue",
        "Annotation",
        "Audit trail",
    ]


def test_a_views_list_selects_views_but_keeps_the_display_order(proj):
    path = _config_with(proj, "x.yaml", 'dashboard:\n  views: ["Audit trail", "Companies"]\n')
    assert load_study(path).dashboard_views == ["Companies", "Audit trail"]


@pytest.mark.parametrize(
    "views",
    ['["No such view"]', "[]", '["Companies", "Companies"]'],
)
def test_a_bad_views_list_is_refused(proj, views):
    path = _config_with(proj, "x.yaml", f"dashboard:\n  views: {views}\n")
    with pytest.raises(ConfigError, match="views must be"):
        load_study(path)


def test_the_demo_config_offers_only_the_evidence_views(repo_root):
    demo = load_study("config/study_demo.yaml", root=repo_root)
    assert demo.dashboard_views == EIS_PAGES
    assert demo.dashboard.notice and "snapshot" in demo.dashboard.notice.lower()
    assert demo.paths.database_url == "sqlite:///data/demo/gauge_demo.db"
    # Everything else must match the study config, so the demo shows the same numbers.
    study = load_study("config/study.yaml", root=repo_root)
    assert demo.study == study.study and demo.stats == study.stats


# ---- the app -----------------------------------------------------------------------------
def _run(monkeypatch, repo_root, config: str) -> AppTest:
    monkeypatch.setattr(sys, "argv", ["app.py", "--config", config])
    return AppTest.from_file(str(repo_root / "dashboard" / "app.py"), default_timeout=120).run()


def go(at: AppTest, page: str) -> AppTest:
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_every_evidence_page_renders_on_the_synthetic_world(world, repo_root, monkeypatch):
    at = _run(monkeypatch, repo_root, "config/study_dry.yaml")
    assert not at.exception
    for page in EIS_PAGES:
        go(at, page)


def test_the_registers_show_company_names_and_the_switch_gives_codes(mini, repo_root, monkeypatch):
    at = go(_run(monkeypatch, repo_root, "config/study_dry.yaml"), "Data quality register")

    def register_companies():
        table = next(d.value for d in at.dataframe if "company" in d.value.columns)
        return set(table["company"])

    assert register_companies() == {"XAA-01 Ltd", "XAA-02 Ltd", "XBB-01 Ltd"}
    at.sidebar.toggle[0].set_value(False).run()
    assert register_companies() == {"XAA-01", "XAA-02", "XBB-01"}


def test_a_views_config_limits_the_sidebar_shows_the_notice_and_the_data_footer(
    world, proj, repo_root, monkeypatch
):
    path = _config_with(
        proj,
        "study_views.yaml",
        'dashboard:\n  views: ["Home", "Sources and filings"]\n  notice: "Shared demo."\n',
    )
    at = _run(monkeypatch, repo_root, path)
    assert not at.exception
    assert at.sidebar.radio[0].options == ["Home", "Sources and filings"]
    assert any("Shared demo." in i.value for i in at.sidebar.info)
    footer = " ".join(c.value for c in at.caption)
    assert "self-reported" in footer and "Model outputs" not in footer


def test_verification_needs_a_name_then_stores_one_decision(mini, repo_root, monkeypatch):
    at = go(_run(monkeypatch, repo_root, "config/study_dry.yaml"), "Data verification")
    assert any("Enter your name" in i.value for i in at.info)
    at.text_input(key="reviewer").set_value("dana").run()
    assert not at.exception
    # The first company with a filing is XAA-01; its first listed value is revenue.
    at.radio(key="verification_result").set_value("error").run()
    at.button(key="record_verification").click().run()
    assert [e.value for e in at.error] == ["say what is wrong with the value"]
    at.text_input(key="verification_note").set_value("PDF says 90").run()
    at.button(key="record_verification").click().run()
    assert not at.exception
    assert any("is error" in s.value for s in at.success)
    with session_scope(mini.engine) as s:
        rows = s.scalars(select(IndicatorValue).where(IndicatorValue.verified.is_not(None))).all()
        by_indicator = {r.indicator: r for r in rows}
    assert set(by_indicator) == {
        "scope1_emissions",
        "revenue_from_operations",
    }  # scope1 was already ok
    revenue = by_indicator["revenue_from_operations"]
    assert revenue.verified is False and "checked by dana" in revenue.verification_note


def test_the_entrypoint_runs_the_dashboard_with_the_config_from_the_environment(
    world, repo_root, monkeypatch
):
    monkeypatch.setenv("GAUGE_CONFIG", "config/study_dry.yaml")
    monkeypatch.setattr(sys, "argv", ["streamlit_app.py"])
    at = AppTest.from_file(str(repo_root / "streamlit_app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.sidebar.radio[0].options[0] == "Home"


def test_the_entrypoint_defaults_to_the_demo_config(repo_root, monkeypatch):
    monkeypatch.delenv("GAUGE_CONFIG", raising=False)
    monkeypatch.setattr(sys, "argv", ["streamlit_app.py"])
    at = AppTest.from_file(str(repo_root / "streamlit_app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.sidebar.radio[0].options == EIS_PAGES  # the demo's views, from the repo's snapshot
