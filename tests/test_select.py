"""Sample selection: rank order, completeness, exclusion log, spares, renumbering, refusals."""

from __future__ import annotations

import shutil
from decimal import Decimal

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from gauge.cli import app
from gauge.config import load_indicators, load_models, load_study
from gauge.db.models import Company, IndicatorValue, Report, Run, Sector
from gauge.db.session import init_db, make_engine, session_scope
from gauge.ingest.pool import PoolEntry
from gauge.ingest.select import SelectionError, run_selection
from gauge.registry import sync_registry

FYS = ["FY2022-23", "FY2023-24", "FY2024-25"]
CODES = [
    "revenue_from_operations",
    "energy_total",
    "energy_renewable",
    "scope1_emissions",
    "scope2_emissions",
    "water_withdrawal",
    "water_consumption",
    "waste_generated",
    "waste_recovered",
]


def pool_for(symbols_by_rank: list[tuple[str, str]]) -> dict[str, PoolEntry]:
    """[(symbol, 'primary'|'spare')] in rank order for sector Cement."""
    return {
        f"INE{i:09d}": PoolEntry(f"INE{i:09d}", "Cement", kind, sym, sym, i + 1, "")
        for i, (sym, kind) in enumerate(symbols_by_rank)
    }


@pytest.fixture
def world(proj):
    cfg = load_study("config/study.yaml")
    cfg.study.companies_per_sector = 2  # keep the arithmetic small
    cfg.study.sectors = cfg.study.sectors[:1]
    ind = load_indicators(cfg)
    engine = make_engine(cfg.database_url())
    init_db(engine)
    with session_scope(engine) as s:
        sync_registry(s, cfg, load_models(cfg))
    yield cfg, ind, engine, proj
    engine.dispose()


def add_company(engine, pool, symbol, *, fys=FYS, drop=(), code=None):
    entry = next(e for e in pool.values() if e.nse_symbol == symbol)
    with session_scope(engine) as s:
        sector = s.scalar(select(Sector).where(Sector.code == "CEM"))
        c = Company(
            code=code or f"CEM-{entry.amfi_rank:02d}",
            real_name=symbol,
            nse_symbol=symbol,
            isin=entry.isin,
            sector_id=sector.id,
            selection_status="candidate",
        )
        s.add(c)
        s.flush()
        for fy in fys:
            r = Report(company_id=c.id, fy=fy, entry_method="xbrl")
            s.add(r)
            s.flush()
            for code in CODES:
                if (fy, code) not in drop:
                    s.add(
                        IndicatorValue(report_id=r.id, indicator=code, value=Decimal(1), unit="x")
                    )


def go(world, pool, **kw):
    cfg, ind, engine, _ = world
    with session_scope(engine) as s:
        return run_selection(s, cfg, ind, pool, **kw)


def status(engine):
    with session_scope(engine) as s:
        return {
            c.nse_symbol: (c.selection_status, c.exclusion_reason, c.code)
            for c in s.scalars(select(Company))
        }


def test_complete_primaries_are_included(world):
    pool = pool_for([("AAA", "primary"), ("BBB", "primary"), ("CCC", "spare")])
    for sym in ("AAA", "BBB"):
        add_company(world[2], pool, sym)
    r = go(world, pool)
    assert (
        r.complete
        and r.sectors[0].included == ["AAA", "BBB"]
        and r.sectors[0].not_needed == ["CCC"]
    )
    assert {k: v[0] for k, v in status(world[2]).items()} == {"AAA": "included", "BBB": "included"}


def test_an_incomplete_primary_is_excluded_with_its_reason_and_a_spare_steps_in(world):
    pool = pool_for([("AAA", "primary"), ("BBB", "primary"), ("CCC", "spare")])
    add_company(world[2], pool, "AAA")
    add_company(
        world[2],
        pool,
        "BBB",
        drop={("FY2023-24", "water_withdrawal"), ("FY2022-23", "scope1_emissions")},
    )
    add_company(world[2], pool, "CCC")
    r = go(world, pool)
    out = r.sectors[0]
    assert out.included == ["AAA", "CCC"] and r.complete
    assert (
        "FY2022-23: scope1_emissions" in out.excluded["BBB"]
        and "FY2023-24: water_withdrawal" in out.excluded["BBB"]
    )
    st = status(world[2])
    assert st["BBB"][0] == "excluded" and "incomplete core indicators" in st["BBB"][1]
    assert st["CCC"][0] == "included" and st["AAA"][1] is None


def test_a_company_missing_a_whole_year_is_incomplete(world):
    pool = pool_for([("AAA", "primary"), ("CCC", "primary"), ("BBB", "spare")])
    add_company(world[2], pool, "AAA")
    add_company(world[2], pool, "BBB")
    add_company(world[2], pool, "CCC", fys=["FY2024-25", "FY2023-24"])  # no FY2022-23 report
    out = go(world, pool, apply=False).sectors[0]
    assert "FY2022-23: no report" in out.excluded["CCC"]
    assert out.included == ["AAA", "BBB"]  # the spare steps in


def test_shortfall_names_the_spares_to_download(world):
    pool = pool_for([("AAA", "primary"), ("BBB", "primary"), ("CCC", "spare")])
    add_company(world[2], pool, "AAA")
    add_company(world[2], pool, "BBB", drop={("FY2024-25", "energy_total")})
    r = go(world, pool)
    out = r.sectors[0]
    assert not r.complete and out.short_by == 1 and out.wanted_spares == ["CCC"]


def test_a_primary_that_was_never_loaded_is_reported(world):
    pool = pool_for([("AAA", "primary"), ("BBB", "primary")])
    add_company(world[2], pool, "AAA")
    out = go(world, pool).sectors[0]
    assert out.excluded["BBB"] == "no filings loaded for this primary company" and out.short_by == 1


def test_selection_refuses_while_a_whole_year_is_missing(world):
    pool = pool_for([("AAA", "primary"), ("BBB", "primary")])
    for sym in ("AAA", "BBB"):
        add_company(world[2], pool, sym, fys=["FY2024-25"])  # the downloads have not arrived
    with pytest.raises(SelectionError, match="no reports are loaded for FY2022-23, FY2023-24"):
        go(world, pool)
    assert {v[0] for v in status(world[2]).values()} == {"candidate"}  # nothing was changed


def test_dry_run_changes_nothing(world):
    pool = pool_for([("AAA", "primary"), ("BBB", "primary")])
    for sym in ("AAA", "BBB"):
        add_company(world[2], pool, sym)
    go(world, pool, apply=False)
    assert {v[0] for v in status(world[2]).values()} == {"candidate"}


def test_codes_are_renumbered_without_gaps_and_independent_of_rank(world):
    pool = pool_for([("AAA", "primary"), ("BBB", "primary"), ("CCC", "spare")])
    add_company(world[2], pool, "AAA", code="CEM-04")
    add_company(world[2], pool, "BBB", code="CEM-07")
    r = go(world, pool)
    assert sorted(v[2] for v in status(world[2]).values()) == ["CEM-01", "CEM-02"]
    assert set(r.renumbered.values()) <= {"CEM-01", "CEM-02"}


def test_an_incomplete_sample_is_not_renumbered(world):
    pool = pool_for([("AAA", "primary"), ("BBB", "primary")])
    add_company(world[2], pool, "AAA", code="CEM-04")
    add_company(world[2], pool, "BBB", code="CEM-07", drop={("FY2024-25", "energy_total")})
    assert go(world, pool).renumbered == {}
    assert status(world[2])["AAA"][2] == "CEM-04"


def test_renumbering_can_be_switched_off(world):
    pool = pool_for([("AAA", "primary"), ("BBB", "primary")])
    add_company(world[2], pool, "AAA", code="CEM-04")
    add_company(world[2], pool, "BBB", code="CEM-07")
    assert go(world, pool, renumber=False).renumbered == {}
    assert sorted(v[2] for v in status(world[2]).values()) == ["CEM-04", "CEM-07"]


def test_codes_cannot_change_once_runs_exist(world):
    pool = pool_for([("AAA", "primary"), ("BBB", "primary")])
    add_company(world[2], pool, "AAA", code="CEM-04")
    add_company(world[2], pool, "BBB", code="CEM-07")
    from gauge.db.models import Condition, Model

    with session_scope(world[2]) as s:
        m, c = s.scalar(select(Model)), s.scalar(select(Condition))
        s.add(
            Run(
                run_id="P1_C1_r1",
                model_id=m.id,
                condition_id=c.id,
                repetition=1,
                seed=1,
                mode="mock",
            )
        )
    with pytest.raises(SelectionError, match="runs already exist"):
        go(world, pool)


def test_cli_refuses_while_years_are_missing(world, repo_root):
    _, _, _, proj = world
    (proj / "data" / "reference").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        repo_root / "data" / "reference" / "candidate_pool.csv", proj / "data" / "reference"
    )
    result = CliRunner().invoke(app, ["--config", "config/study.yaml", "select", "--dry-run"])
    assert result.exit_code == 1 and "selection not run: no reports are loaded for" in result.output
