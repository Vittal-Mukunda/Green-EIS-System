"""Loading BRSR XBRL filings into the database. Fake company (see xbrl_fixture); numbers by hand."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from gauge.cli import app
from gauge.config import load_indicators, load_models, load_study
from gauge.db.models import Company, IndicatorValue, KpiValue, QualityFlag, Report
from gauge.db.session import init_db, make_engine, session_scope
from gauge.ingest.pool import load_pool
from gauge.ingest.xbrl_load import discover, load_xbrl
from gauge.ingest.xbrl_map import Override, load_xbrl_mapping
from gauge.kpi.engine import compute_kpis
from gauge.quality.validators import run_validators
from gauge.registry import sync_registry
from gauge.standardize.run import standardize_indicators
from xbrl_fixture import FAKE_ISIN, PREVIOUS, build_instance

D = Decimal
POOL = (
    "sector,pool,amfi_rank,company_name,nse_symbol,isin,avg_mcap_cr,amfi_category,note\n"
    f"Cement,primary,1,Fake Cement Ltd,FAKECEM,{FAKE_ISIN},1000.00,Large Cap,\n"
)


@pytest.fixture
def world(proj):
    """Real study config in a tmp root, an initialised DB, and a one-company candidate pool."""
    (proj / "data" / "reference").mkdir(parents=True)
    (proj / "data" / "reference" / "candidate_pool.csv").write_text(POOL, encoding="utf-8")
    cfg = load_study("config/study.yaml")
    ind = load_indicators(cfg)
    engine = make_engine(cfg.database_url())
    init_db(engine)
    with session_scope(engine) as s:
        sync_registry(s, cfg, load_models(cfg))
    yield cfg, ind, engine, proj
    engine.dispose()


def run(world, paths, overrides=(), **kw):
    cfg, ind, engine, _ = world
    kw.setdefault("retrieved_on", date(2026, 10, 2))
    paths = paths if isinstance(paths, list) else [paths]
    mapping, pool = load_xbrl_mapping(cfg, ind), load_pool(cfg.root)
    with session_scope(engine) as s:
        return load_xbrl(s, cfg, ind, mapping, list(overrides), pool, paths, **kw)


def one(engine, query):
    with session_scope(engine) as s:
        return s.scalar(query)


def reports(engine):
    with session_scope(engine) as s:
        return {r.fy: r for r in s.scalars(select(Report))}


def values(engine, fy):
    with session_scope(engine) as s:
        rid = s.scalar(select(Report.id).where(Report.fy == fy))
        return {
            v.indicator: v
            for v in s.scalars(select(IndicatorValue).where(IndicatorValue.report_id == rid))
        }


# ---- what gets written ---------------------------------------------------------------------------
def test_company_and_both_years_are_loaded(world):
    _, _, engine, proj = world
    summary = run(world, build_instance(proj / "f.xml"))
    assert (summary.companies_created, summary.reports_written, summary.skipped) == (1, 2, 0)
    with session_scope(engine) as s:
        c = s.scalar(select(Company))
    assert (c.isin, c.nse_symbol, c.real_name, c.selection_status) == (
        FAKE_ISIN,
        "FAKECEM",
        "Fake Cement Limited",
        "candidate",
    )
    assert c.code.startswith("CEM-") and not c.is_synthetic
    r = reports(engine)
    assert set(r) == {"FY2024-25", "FY2025-26"}
    assert (r["FY2025-26"].entry_method, r["FY2024-25"].entry_method) == (
        "xbrl",
        "xbrl_comparative",
    )
    assert (r["FY2025-26"].boundary, r["FY2025-26"].assured) == ("standalone", True)
    assert (
        r["FY2024-25"].assured is None
    )  # assurance of the earlier year is not stated by this filing
    assert "previous-year column" in r["FY2024-25"].assurance_note
    assert r["FY2025-26"].retrieved_on == date(2026, 10, 2)


def test_values_are_stored_as_filed_with_element_provenance(world):
    _, _, engine, proj = world
    run(world, build_instance(proj / "f.xml"))
    v = values(engine, "FY2025-26")
    assert len(v) == 9 and all(x.original_unit is None for x in v.values())  # not yet standardized
    assert (v["energy_total"].value, v["energy_total"].unit) == (D("1000000"), "GJ")
    assert v["scope1_emissions"].page_ref == "TotalScope1Emissions [label]"
    assert v["revenue_from_operations"].page_ref == "RevenueFromOperations [magnitude]"
    assert values(engine, "FY2024-25")["scope1_emissions"].value == D("4800000")


def test_filing_is_copied_under_a_canonical_name(world):
    cfg, _, engine, proj = world
    src = build_instance(proj / "downloads_f.xml")
    run(world, src)
    stored = cfg.path(cfg.paths.raw_data_dir) / "xbrl" / "FAKECEM_FY2025-26.xml"
    assert stored.is_file() and stored.read_bytes() == src.read_bytes()
    r = reports(engine)["FY2025-26"]
    assert r.source_file == "data/raw/xbrl/FAKECEM_FY2025-26.xml"
    assert r.file_sha256 == hashlib.sha256(src.read_bytes()).hexdigest()


def test_a_different_file_never_overwrites_an_existing_copy(world):
    cfg, _, _, proj = world
    run(world, build_instance(proj / "a.xml"))
    run(world, build_instance(proj / "b.xml", name="Fake Cement Limited (revised)"))
    names = sorted(p.name for p in (cfg.path(cfg.paths.raw_data_dir) / "xbrl").glob("*.xml"))
    assert len(names) == 2 and "FAKECEM_FY2025-26.xml" in names


def test_copy_can_be_disabled(world):
    cfg, _, engine, proj = world
    src = build_instance(proj / "f.xml")
    run(world, src, copy_to_raw=False)
    assert not (cfg.path(cfg.paths.raw_data_dir) / "xbrl").exists()
    assert reports(engine)["FY2025-26"].source_file == "f.xml"


def test_reload_is_idempotent(world):
    _, _, engine, proj = world
    src = build_instance(proj / "f.xml")
    run(world, src)
    again = run(world, src)
    assert again.companies_created == 0
    with session_scope(engine) as s:
        assert [
            s.scalar(select(func.count()).select_from(t)) for t in (Company, Report, IndicatorValue)
        ] == [1, 2, 18]


def test_directories_are_searched_for_xml_only(world):
    _, _, _, proj = world
    folder = proj / "incoming"
    folder.mkdir()
    build_instance(folder / "one.xml")
    (folder / "notes.txt").write_text("x", encoding="utf-8")
    (folder / "doc.pdf").write_bytes(b"%PDF")
    assert [p.name for p in discover([folder])] == ["one.xml"]


# ---- refusals and skips --------------------------------------------------------------------------
def test_unknown_isin_is_refused_and_nothing_is_written(world):
    _, _, engine, proj = world
    summary = run(world, build_instance(proj / "f.xml", isin="INE999Z99999"))
    assert (
        len(summary.refused) == 1
        and "not in data/reference/candidate_pool.csv" in summary.refused[0].refused
    )
    assert one(engine, select(func.count()).select_from(Company)) == 0


def test_unverified_taxonomy_is_refused(world):
    _, _, engine, proj = world
    summary = run(world, build_instance(proj / "f.xml", schema="in-capmkt-ent-2024-01-01.xsd"))
    assert "not one this mapping has been checked against" in summary.refused[0].refused
    assert one(engine, select(func.count()).select_from(Report)) == 0


def test_an_unresolved_year_is_skipped_and_the_other_year_is_still_loaded(world):
    _, _, engine, proj = world
    summary = run(
        world, build_instance(proj / "f.xml", current={"TotalScope1Emissions": ("64", "MtCO2e")})
    )
    out = summary.outcomes[0]
    assert out.loaded == ["FY2024-25"] and list(out.skipped) == ["FY2025-26"]
    assert "scope1_emissions" in out.skipped["FY2025-26"] and set(reports(engine)) == {"FY2024-25"}


# ---- overrides and quality flags ----------------------------------------------------------------
def test_override_flag_is_stored_and_survives_validation(world):
    cfg, ind, engine, proj = world
    o = Override(
        isin=FAKE_ISIN,
        fy=["FY2025-26"],
        indicators=["scope1_emissions"],
        unit="Mn MT",
        evidence="verified on page 48 of the filing PDF",
    )
    run(
        world,
        build_instance(proj / "f.xml", current={"TotalScope1Emissions": ("64", "MtCO2e")}),
        [o],
    )
    with session_scope(engine) as s:
        standardize_indicators(s, ind)
        run_validators(s, cfg, ind)  # replaces validator flags only
        flags = s.scalars(
            select(QualityFlag).where(QualityFlag.rule == "xbrl_override_applied")
        ).all()
        assert len(flags) == 1 and "page 48" in flags[0].message and flags[0].fy == "FY2025-26"
        stored = s.scalar(
            select(IndicatorValue).where(
                IndicatorValue.indicator == "scope1_emissions",
                IndicatorValue.original_unit == "Mn MT",
            )
        )
        assert stored.value == D("64000000")  # 64 million tonnes, converted exactly


def test_reloading_does_not_duplicate_override_flags(world):
    _, _, engine, proj = world
    o = Override(
        isin=FAKE_ISIN,
        fy=["FY2025-26"],
        indicators=["scope1_emissions"],
        unit="Mn MT",
        evidence="verified on page 48 of the filing PDF",
    )
    src = build_instance(proj / "f.xml", current={"TotalScope1Emissions": ("64", "MtCO2e")})
    for _ in range(3):
        run(world, src, [o])
    assert (
        one(
            engine,
            select(func.count())
            .select_from(QualityFlag)
            .where(QualityFlag.rule == "xbrl_override_applied"),
        )
        == 1
    )


# ---- as-filed beats comparative, in either order -------------------------------------------
def _own_year_filing(proj, name, energy):
    """The company's FY2024-25 filing. Everything equals the FY2024-25 comparative that a later
    filing carries (the fixture's PREVIOUS values) except the total-energy figure."""
    return build_instance(
        proj / name,
        current_period=("2024-04-01", "2025-03-31"),
        previous_period=("2023-04-01", "2024-03-31"),
        current={
            **PREVIOUS,
            "TotalEnergyConsumedFromRenewableAndNonRenewableSources": (energy, "GJ"),
        },
    )


def test_as_filed_replaces_a_comparative_and_flags_the_restatement(world):
    _, _, engine, proj = world
    run(
        world, build_instance(proj / "later.xml")
    )  # FY2025-26; its FY2024-25 comparative has 950,000 GJ
    summary = run(world, _own_year_filing(proj, "own.xml", "1100000"))  # as filed: 1,100,000 GJ
    assert summary.restatements == 1
    r = reports(engine)["FY2024-25"]
    assert r.entry_method == "xbrl" and values(engine, "FY2024-25")["energy_total"].value == D(
        "1100000"
    )
    with session_scope(engine) as s:
        flag = s.scalar(select(QualityFlag).where(QualityFlag.rule == "xbrl_restatement"))
    assert flag.indicator == "energy_total" and "comparative vs as-filed" in flag.message


def test_a_comparative_never_replaces_an_as_filed_report(world):
    _, _, engine, proj = world
    run(world, _own_year_filing(proj, "own.xml", "1100000"))
    summary = run(world, build_instance(proj / "later.xml"))
    assert summary.outcomes[0].kept == ["FY2024-25"] and summary.restatements == 1
    assert reports(engine)["FY2024-25"].entry_method == "xbrl"
    assert values(engine, "FY2024-25")["energy_total"].value == D("1100000")
    with session_scope(engine) as s:
        assert "as-filed vs later comparative" in s.scalar(
            select(QualityFlag.message).where(QualityFlag.rule == "xbrl_restatement")
        )


def test_final_state_does_not_depend_on_load_order(world):
    cfg, ind, engine, proj = world
    own, later = _own_year_filing(proj, "own.xml", "1100000"), build_instance(proj / "later.xml")
    run(world, [later, own])
    first = {
        fy: (r.entry_method, {k: v.value for k, v in values(engine, fy).items()})
        for fy, r in reports(engine).items()
    }
    engine.dispose()
    (cfg.root / "data" / "processed" / "gauge.db").unlink()
    engine2 = make_engine(cfg.database_url())
    init_db(engine2)
    with session_scope(engine2) as s:
        sync_registry(s, cfg, load_models(cfg))
    run((cfg, ind, engine2, proj), [own, later])
    second = {
        fy: (r.entry_method, {k: v.value for k, v in values(engine2, fy).items()})
        for fy, r in reports(engine2).items()
    }
    engine2.dispose()
    assert first == second


def test_restatement_flags_are_not_duplicated_by_reloading(world):
    _, _, engine, proj = world
    own, later = _own_year_filing(proj, "own.xml", "1100000"), build_instance(proj / "later.xml")
    for _ in range(3):
        run(world, [own, later])
    assert (
        one(
            engine,
            select(func.count())
            .select_from(QualityFlag)
            .where(QualityFlag.rule == "xbrl_restatement"),
        )
        == 1
    )


def test_small_differences_are_not_restatements(world):
    _, _, engine, proj = world
    run(
        world, [_own_year_filing(proj, "own.xml", "950000"), build_instance(proj / "later.xml")]
    )  # identical
    assert (
        one(
            engine,
            select(func.count())
            .select_from(QualityFlag)
            .where(QualityFlag.rule == "xbrl_restatement"),
        )
        == 0
    )


def test_a_later_filing_does_not_rename_the_company(world):
    _, _, engine, proj = world
    run(world, build_instance(proj / "a.xml", previous=None))
    run(
        world,
        build_instance(proj / "b.xml", previous=None, name="Renamed Cement Limited"),
    )
    assert one(engine, select(Company.real_name)) == "Fake Cement Limited"


def test_a_filing_with_only_a_cin_loads_when_the_cin_is_known(world):
    _, _, engine, proj = world
    (proj / "data" / "reference" / "cin_isin.csv").write_text(
        f"cin,isin,nse_symbol,evidence\nL00000XX0000PLC000000,{FAKE_ISIN},FAKECEM,unit test\n",
        encoding="utf-8",
    )
    extra = (
        '<in-capmkt:CorporateIdentityNumber contextRef="DCYMain">'
        "L00000XX0000PLC000000</in-capmkt:CorporateIdentityNumber>"
    )
    summary = run(world, build_instance(proj / "cin.xml", isin=None, extra=extra))
    assert summary.refused == [] and summary.reports_written == 2
    assert one(engine, select(Company.isin)) == FAKE_ISIN


def test_a_manual_report_is_never_overwritten_by_xbrl(world):
    _, _, engine, proj = world
    run(
        world, build_instance(proj / "f.xml", previous=None)
    )  # creates the company with FY2025-26 only
    with session_scope(engine) as s:
        company = s.scalar(select(Company))
        manual = Report(
            company_id=company.id, fy="FY2024-25", entry_method="manual", boundary="standalone"
        )
        s.add(manual)
        s.flush()
        s.add(
            IndicatorValue(report_id=manual.id, indicator="energy_total", value=D("777"), unit="GJ")
        )
    summary = run(world, build_instance(proj / "g.xml"))
    assert summary.outcomes[0].kept == ["FY2024-25"]
    assert reports(engine)["FY2024-25"].entry_method == "manual"
    assert values(engine, "FY2024-25")["energy_total"].value == D("777")
    with session_scope(engine) as s:
        message = s.scalar(
            select(QualityFlag.message).where(QualityFlag.rule == "xbrl_restatement")
        )
    assert message is not None and "manual entry vs later comparative" in message


# ---- the whole chain on the loaded data ---------------------------------------------------------
def test_kpis_from_loaded_xbrl_match_hand_calculation(world):
    cfg, ind, engine, proj = world
    run(world, build_instance(proj / "f.xml"))
    with session_scope(engine) as s:
        standardize_indicators(s, ind)
        compute_kpis(s, cfg, ind)
        kpi = {(k.fy, k.kpi): k.value for k in s.scalars(select(KpiValue))}
    # FY2025-26: revenue 5e11 INR = 50,000 crore (x 1e-7)
    assert kpi[("FY2025-26", "energy_intensity")] == D("20")  # 1,000,000 GJ / 50,000
    assert kpi[("FY2025-26", "emissions_intensity")] == D("110")  # (5,000,000 + 500,000) / 50,000
    assert kpi[("FY2025-26", "water_intensity")] == D("40")  # 2,000,000 kL consumption / 50,000
    assert kpi[("FY2025-26", "renewable_share")] == D("20")  # 100 x 200,000 / 1,000,000
    assert kpi[("FY2025-26", "waste_recovery_rate")] == D("90")  # 100 x 90,000 / 100,000
    # FY2024-25: revenue 4.5e11 INR = 45,000 crore; 950,000 / 45,000 = 21.1111...
    assert kpi[("FY2024-25", "energy_intensity")] == D("21.111111111111")


def test_energy_reported_in_terajoules_converts_exactly(world):
    cfg, ind, engine, proj = world
    run(
        world,
        build_instance(
            proj / "f.xml",
            current={
                "TotalEnergyConsumedFromRenewableAndNonRenewableSources": ("1000", "TJ"),
                "TotalEnergyConsumedFromRenewableSources": ("200", "TJ"),
            },
        ),
    )
    with session_scope(engine) as s:
        standardize_indicators(s, ind)
        compute_kpis(s, cfg, ind)
        k = s.scalar(
            select(KpiValue.value).where(
                KpiValue.fy == "FY2025-26", KpiValue.kpi == "energy_intensity"
            )
        )
    assert k == D("20")  # 1000 TJ = 1,000,000 GJ: the same company, the same intensity


# ---- command line --------------------------------------------------------------------------------
cli = CliRunner()


def gauge(*args):
    return cli.invoke(app, ["--config", "config/study.yaml", *args])


def test_cli_loads_a_folder(world):
    _, _, engine, proj = world
    folder = proj / "incoming"
    folder.mkdir()
    build_instance(folder / "a.xml")
    result = gauge("ingest", "--xbrl", str(folder), "--retrieved-on", "2026-10-02")
    assert result.exit_code == 0, result.output
    assert (
        "1 filings: 2 company-years written, 0 skipped, 0 refused; 1 new companies" in result.output
    )
    assert one(engine, select(func.count()).select_from(Report)) == 2


def test_cli_exits_1_and_names_the_problem(world):
    _, _, _, proj = world
    build_instance(proj / "bad.xml", isin="INE999Z99999")
    result = gauge("ingest", "--xbrl", str(proj / "bad.xml"))
    assert (
        result.exit_code == 1
        and "REFUSED" in result.output
        and "candidate_pool.csv" in result.output
    )
    build_instance(proj / "skip.xml", current={"TotalScope1Emissions": ("64", "MtCO2e")})
    result = gauge("ingest", "--xbrl", str(proj / "skip.xml"))
    assert result.exit_code == 1 and "SKIPPED" in result.output and "FY2025-26" in result.output


def test_cli_needs_exactly_one_source(world):
    _, _, _, proj = world
    f = build_instance(proj / "a.xml")
    assert gauge("ingest").exit_code != 0
    assert gauge("ingest", "--xbrl", str(f), "--manual", "x.csv").exit_code != 0
    assert gauge("ingest", "--xbrl", str(f), "--inspect-xbrl", str(f)).exit_code != 0


def test_cli_without_a_database_says_init_db(proj):
    (proj / "data" / "reference").mkdir(parents=True)
    (proj / "data" / "reference" / "candidate_pool.csv").write_text(POOL, encoding="utf-8")
    f = build_instance(proj / "a.xml")
    result = gauge("ingest", "--xbrl", str(f))
    assert result.exit_code == 1 and "gauge init-db" in result.output
