from __future__ import annotations

import hashlib
import random
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from gauge.config import load_indicators, load_study
from gauge.db.models import Company, IndicatorValue, Report
from gauge.db.session import session_scope
from gauge.ingest.manual import (
    EXPECTED_COLUMNS,
    IngestError,
    assign_codes,
    load_manual,
    parse_manual_csv,
)
from helpers import manual_row as row
from helpers import write_manual_csv

D = Decimal


@pytest.fixture
def ctx(proj):
    cfg = load_study("config/study_dry.yaml")
    return cfg, load_indicators(cfg), proj


def parse(ctx, rows):
    cfg, ind, root = ctx
    return parse_manual_csv(write_manual_csv(root / "in.csv", rows), cfg, ind)


def errors(parsed) -> str:
    return "\n".join(i.message for i in parsed.errors)


# ---- validator ----------------------------------------------------------------------------------
def test_template_header_matches_expected_columns(repo_root):
    header = (repo_root / "data/manual_entry_template.csv").read_text(encoding="utf-8").strip()
    assert header.split(",") == EXPECTED_COLUMNS


def test_valid_file(ctx):
    parsed = parse(ctx, [row(), row(indicator="energy_total", value="500,000", unit="GJ")])
    assert parsed.ok and len(parsed.rows) == 2
    assert parsed.rows[1].value == D("500000")  # thousands separator stripped
    assert parsed.sha256 == hashlib.sha256(parsed.path.read_bytes()).hexdigest()


def test_indian_digit_grouping_and_decimals(ctx):
    parsed = parse(ctx, [row(value="12,34,567.89")])
    assert parsed.ok and parsed.rows[0].value == D("1234567.89")


def test_indicator_label_is_accepted(ctx):
    parsed = parse(ctx, [row(indicator="Scope 1 emissions", unit="tCO2e")])
    assert parsed.ok and parsed.rows[0].indicator == "scope1_emissions"


def test_fiscal_year_and_sector_are_normalized(ctx):
    parsed = parse(ctx, [row(fy="2024-25", sector="synthetic alpha")])
    assert parsed.ok
    assert (parsed.rows[0].fy, parsed.rows[0].sector) == ("FY2024-25", "Synthetic Alpha")


def test_blank_lines_and_bom_are_tolerated(ctx):
    cfg, ind, root = ctx
    path = write_manual_csv(root / "in.csv", [row(), {}, row(indicator="energy_total", unit="GJ")])
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    parsed = parse_manual_csv(path, cfg, ind)
    assert parsed.ok and len(parsed.rows) == 2


def test_missing_column_stops_early(ctx):
    cfg, ind, root = ctx
    path = root / "in.csv"
    path.write_text("company,sector,fy\nA,B,C\n", encoding="utf-8")
    parsed = parse_manual_csv(path, cfg, ind)
    assert not parsed.ok and "missing columns" in errors(parsed) and not parsed.rows


def test_extra_columns_only_warn(ctx):
    cfg, ind, root = ctx
    path = write_manual_csv(root / "in.csv", [row()])
    text = path.read_text(encoding="utf-8").replace("page_ref", "page_ref,notes", 1)
    path.write_text(text, encoding="utf-8")
    parsed = parse_manual_csv(path, cfg, ind)
    assert parsed.ok and any(i.level == "warning" for i in parsed.issues)


def test_empty_file(ctx):
    assert "no data rows" in errors(parse(ctx, []))


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        (dict(company=""), "company is empty"),
        (dict(sector="Cement"), "sector 'Cement' is not one of"),
        (dict(fy="FY25"), "fiscal year"),
        (dict(indicator="scope3_emissions"), "not in config/indicators.yaml"),
        (dict(value="abc"), "not a plain number"),
        (dict(value="1e3x"), "not a plain number"),
        (dict(value=""), "not a plain number"),
        (dict(unit="GJ"), "not a currency unit"),  # an energy unit on a revenue indicator
        (dict(unit="ton", indicator="waste_generated"), "ambiguous"),
        (dict(unit=""), "empty"),
        (dict(boundary="group"), "boundary"),
        (dict(assured="maybe"), "assured"),
        (dict(source_url=""), "source_url is required"),
        (dict(page_ref=""), "page_ref is required"),
    ],
)
def test_row_level_errors(ctx, overrides, fragment):
    parsed = parse(ctx, [row(**overrides)])
    assert not parsed.ok
    assert fragment in errors(parsed)
    assert parsed.errors[0].line == 2  # header is line 1


def test_errors_do_not_hide_each_other(ctx):
    parsed = parse(ctx, [row(sector="X", fy="bad", value="?")])
    assert len(parsed.errors) == 3


def test_negative_values_load_and_are_left_to_the_validators(ctx):
    parsed = parse(ctx, [row(value="-5")])
    assert parsed.ok and parsed.rows[0].value == D("-5")  # flagged later by non_negative


def test_duplicate_values(ctx):
    parsed = parse(ctx, [row(), row(value="3000")])
    assert "duplicate value" in errors(parsed) and "first at line 2" in errors(parsed)


def test_duplicate_detection_treats_symbol_case_insensitively(ctx):
    assert "duplicate" in errors(parse(ctx, [row(), row(nse_symbol="alpha")]))


def test_conflicting_boundary_within_one_report(ctx):
    rows = [row(), row(indicator="energy_total", unit="GJ", boundary="standalone")]
    assert "conflicting boundary" in errors(parse(ctx, rows))


def test_conflicting_assured_within_one_report(ctx):
    rows = [row(), row(indicator="energy_total", unit="GJ", assured="no")]
    assert "conflicting assured" in errors(parse(ctx, rows))


def test_boundary_may_differ_between_years(ctx):
    rows = [row(fy="FY2023-24", boundary="standalone"), row(fy="FY2024-25")]
    assert parse(ctx, rows).ok


def test_company_identity_conflicts(ctx):
    two_names = [row(), row(company="Alpha Limited", indicator="energy_total", unit="GJ")]
    assert "several company names" in errors(parse(ctx, two_names))
    two_sectors = [row(), row(sector="Synthetic Beta", indicator="energy_total", unit="GJ")]
    assert "several sectors" in errors(parse(ctx, two_sectors))
    two_symbols = [row(), row(nse_symbol="ALPH2", indicator="energy_total", unit="GJ")]
    assert "several NSE symbols" in errors(parse(ctx, two_symbols))


def test_company_without_symbol_is_identified_by_name(ctx):
    rows = [row(nse_symbol=""), row(nse_symbol="", indicator="energy_total", unit="GJ")]
    assert parse(ctx, rows).ok


# ---- masked codes -------------------------------------------------------------------------------
def test_codes_do_not_depend_on_input_order():
    keys = ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"]
    expected = assign_codes(set(), keys, "ITS", 42)
    shuffled = list(keys)
    random.Random(1).shuffle(shuffled)
    assert assign_codes(set(), shuffled, "ITS", 42) == expected
    assert sorted(expected.values()) == [f"ITS-0{i}" for i in range(1, 6)]


def test_codes_are_not_input_order_and_depend_on_the_seed():
    keys = [f"CO{i}" for i in range(10)]
    a = assign_codes(set(), keys, "CEM", 42)
    assert [a[k] for k in keys] != [f"CEM-{i:02d}" for i in range(1, 11)]  # not first-come order
    assert assign_codes(set(), keys, "CEM", 43) != a


def test_existing_codes_are_never_reused_or_changed():
    out = assign_codes({"CEM-01", "CEM-03"}, ["A", "B", "C"], "CEM", 42)
    assert sorted(out.values()) == ["CEM-02", "CEM-04", "CEM-05"]


# ---- loader -------------------------------------------------------------------------------------
def load(db, rows, **kw):
    path = write_manual_csv(db.root / "in.csv", rows)
    with session_scope(db.engine) as s:
        return load_manual(s, db.cfg, db.ind, path, **kw)


def test_load_stores_values_exactly_as_reported(db):
    rows = [
        row(value="250", unit="INR lakh"),
        row(indicator="energy_total", value="2", unit="MWh"),
    ]
    summary = load(db, rows, retrieved_on=date(2026, 9, 30))
    assert (summary.companies_created, summary.reports_touched, summary.values_written) == (1, 1, 2)
    with session_scope(db.engine) as s:
        company = s.scalar(select(Company))
        report = s.scalar(select(Report))
        values = {v.indicator: v for v in s.scalars(select(IndicatorValue))}
    assert company.code.startswith("SYA-") and company.selection_status == "candidate"
    assert company.real_name == "Alpha Ltd" and company.is_synthetic is False
    assert (report.boundary, report.assured, report.entry_method) == (
        "consolidated",
        True,
        "manual",
    )
    assert report.retrieved_on == date(2026, 9, 30)
    assert report.file_sha256 == hashlib.sha256((db.root / "in.csv").read_bytes()).hexdigest()
    assert report.source_file == "in.csv"
    rev = values["revenue_from_operations"]
    assert (rev.value, rev.unit, rev.original_unit) == (
        D("250"),
        "INR lakh",
        None,
    )  # not converted yet
    assert (rev.source_url, rev.page_ref) == ("https://example.org/alpha.pdf", "p. 12")


def test_synthetic_load_marks_companies_included(db):
    load(db, [row()], synthetic=True)
    with session_scope(db.engine) as s:
        c = s.scalar(select(Company))
    assert c.is_synthetic and c.selection_status == "included"


def test_reload_is_idempotent(db):
    rows = [row(), row(indicator="energy_total", unit="GJ")]
    load(db, rows)
    again = load(db, rows)
    assert again.companies_created == 0
    with session_scope(db.engine) as s:
        counts = [
            s.scalar(select(func.count()).select_from(t)) for t in (Company, Report, IndicatorValue)
        ]
    assert counts == [1, 1, 2]


def test_reload_with_a_changed_value_resets_standardization(db):
    load(db, [row(value="100")])
    with session_scope(db.engine) as s:
        v = s.scalar(select(IndicatorValue))
        v.original_value, v.original_unit = v.value, v.unit  # pretend `standardize` ran
    load(db, [row(value="120")])
    with session_scope(db.engine) as s:
        v = s.scalar(select(IndicatorValue))
    assert v.value == D("120") and v.original_unit is None


def test_codes_are_stable_when_more_companies_arrive(db):
    load(db, [row()])
    with session_scope(db.engine) as s:
        first = s.scalar(select(Company.code))
    load(
        db,
        [
            row(),
            row(company="Beta Ltd", nse_symbol="BETA"),
            row(company="Gamma Ltd", nse_symbol="GAMMA"),
        ],
    )
    with session_scope(db.engine) as s:
        codes = sorted(s.scalars(select(Company.code)))
    assert first in codes and len(set(codes)) == 3 == len(codes)


def test_invalid_file_loads_nothing(db):
    good, bad = row(), row(company="Beta Ltd", nse_symbol="BETA", value="oops")
    with pytest.raises(IngestError, match="not a plain number"):
        load(db, [good, bad])
    with session_scope(db.engine) as s:
        assert s.scalar(select(func.count()).select_from(Company)) == 0
        assert s.scalar(select(func.count()).select_from(IndicatorValue)) == 0


def test_company_cannot_silently_move_sector(db):
    load(db, [row()])
    with pytest.raises(IngestError, match="different sector"):
        load(db, [row(sector="Synthetic Beta")])


def test_unregistered_sectors_ask_for_init_db(proj):
    from gauge.db.session import init_db, make_engine

    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    init_db(engine)  # schema only, no sectors
    path = write_manual_csv(proj / "in.csv", [row()])
    with pytest.raises(LookupError, match="init-db"), session_scope(engine) as s:
        load_manual(s, cfg, load_indicators(cfg), path)
    engine.dispose()
