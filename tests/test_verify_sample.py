"""verify-sample: matching values in PDF text, seeded sampling, recording human results."""

from __future__ import annotations

import csv
from decimal import Decimal

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from gauge.cli import app
from gauge.config import load_study
from gauge.db.models import Company, IndicatorValue, Report, Sector
from gauge.db.session import make_engine, session_scope
from gauge.quality.verify import (
    COLUMNS,
    as_filed,
    draw_sample,
    find_in_pages,
    number_tokens,
    record_results,
    write_csv,
)

D = Decimal
cli = CliRunner()


# ---- matching ----------------------------------------------------------------------------------
def test_number_tokens_ignore_grouping_style():
    assert number_tokens("Total 1,88,42,244 and 18,842,244; 486.60 and 0.4866 PJ") == {
        "18842244",
        "486.6",
        "0.4866",
    }


@pytest.mark.parametrize(
    "value, page, expected",
    [
        ("18842244", "recovered 1,88,42,244 tonnes", True),  # Indian grouping
        ("18842244", "recovered 18,842,244 tonnes", True),  # Western grouping
        ("486.6", "renewable 486.60 TJ", True),  # trailing zero
        ("88884246", "scope 1 88884246", True),
        ("88884246", "scope 1 888842460", False),  # a longer number is not a match
        ("88884246", "id 88884246x", True),  # tokens are digit runs
        ("11.2", "11.25", False),  # no substring matching
    ],
)
def test_find_in_pages_matches_whole_numbers_only(value, page, expected):
    assert bool(find_in_pages([page], D(value))) is expected


def test_find_in_pages_reports_all_pages_and_skips_short_numbers():
    pages = ["x 31408053", "none", "again 31,408,053"]
    assert find_in_pages(pages, D("31408053")) == [1, 3]
    assert find_in_pages(["64 and 64"], D("64")) == []  # too short to say anything


def test_negative_values_match_their_magnitude():
    assert find_in_pages(["loss (12,345)"], D("-12345")) == [1]


# ---- sampling ----------------------------------------------------------------------------------
@pytest.fixture
def db(proj):
    cfg = load_study("config/study.yaml")
    engine = make_engine(cfg.database_url())
    from gauge.config import load_models
    from gauge.db.session import init_db
    from gauge.registry import sync_registry

    init_db(engine)
    with session_scope(engine) as s:
        sync_registry(s, cfg, load_models(cfg))
        sector = s.scalar(select(Sector).where(Sector.code == "CEM"))
        for n in (1, 2):
            c = Company(
                code=f"CEM-0{n}",
                real_name=f"Real Co {n}",
                nse_symbol=f"SYM{n}",
                sector_id=sector.id,
                selection_status="candidate",
            )
            s.add(c)
            s.flush()
            for fy in ("FY2024-25", "FY2025-26"):
                r = Report(
                    company_id=c.id,
                    fy=fy,
                    entry_method="xbrl",
                    source_file=f"data/raw/xbrl/SYM{n}_FY2025-26.xml",
                )
                s.add(r)
                s.flush()
                for i, code in enumerate(("energy_total", "scope1_emissions", "water_consumption")):
                    s.add(
                        IndicatorValue(
                            report_id=r.id,
                            indicator=code,
                            value=D(1000 * (i + 1) * n),
                            unit="GJ",
                            page_ref=f"Element{i} [label]",
                        )
                    )
        # a synthetic company must never be sampled
        syn = Company(code="CEM-09", real_name="Synthetic", sector_id=sector.id, is_synthetic=True)
        s.add(syn)
    yield cfg, engine, proj
    engine.dispose()


def draw(db, **kw):
    cfg, engine, proj = db
    with session_scope(engine) as s:
        return draw_sample(s, proj, **kw)


def test_each_company_gets_its_own_share_rounded_up(db):
    items = draw(db, fraction=0.10)  # 6 values per company -> ceil(0.6) = 1 each
    assert sorted(i.company_code for i in items) == ["CEM-01", "CEM-02"]
    assert len(draw(db, fraction=0.5)) == 6  # ceil(3) per company
    assert len(draw(db, fraction=1.0)) == 12  # everything


def test_sampling_is_seeded(db):
    a = [i.item_id for i in draw(db, fraction=0.5, seed=7)]
    assert a == [i.item_id for i in draw(db, fraction=0.5, seed=7)]
    assert a != [i.item_id for i in draw(db, fraction=0.5, seed=8)]


def test_synthetic_companies_are_never_sampled(db):
    assert "CEM-09" not in {i.company_code for i in draw(db, fraction=1.0)}


def test_items_carry_what_a_human_needs(db):
    item = draw(db, fraction=1.0)[0]
    assert (item.company, item.nse_symbol) == ("Real Co 1", "SYM1")
    assert item.element.startswith("Element") and item.source_xml.endswith("SYM1_FY2025-26.xml")
    assert item.pdf == ""  # no PDF on file in this tmp root


def test_the_pdf_is_the_one_of_the_filing_not_of_the_year(db):
    cfg, engine, proj = db
    pdf = proj / "data" / "raw" / "pdf" / "SYM1_FY2025-26.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4")
    items = draw(db, fraction=1.0)
    # the FY2024-25 comparative of an FY2025-26 filing is checked in that same PDF
    assert {i.pdf for i in items if i.nse_symbol == "SYM1"} == {"data/raw/pdf/SYM1_FY2025-26.pdf"}


def test_as_filed_prefers_the_original_pair_after_standardizing():
    iv = IndicatorValue(
        indicator="energy_total",
        value=D("107249000"),
        unit="GJ",
        original_value=D("107249"),
        original_unit="TJ",
    )
    assert as_filed(iv) == (D("107249"), "TJ")
    assert as_filed(IndicatorValue(indicator="x", value=D("5"), unit="t")) == (D("5"), "t")


# ---- recording ---------------------------------------------------------------------------------
def make_csv(db, tmp_path):
    cfg, engine, proj = db
    with session_scope(engine) as s:
        items = draw_sample(s, proj, fraction=1.0)
    path = tmp_path / "sample.csv"
    write_csv(items, path)
    return path, items


def fill(path, results):
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    for row, (result, note) in zip(rows, results, strict=False):
        row["human_result"], row["human_note"] = result, note
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def test_csv_has_the_documented_columns_and_blank_human_fields(db, tmp_path):
    path, items = make_csv(db, tmp_path)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert list(rows[0]) == COLUMNS and len(rows) == len(items)
    assert all(r["human_result"] == "" and r["auto_check"] == "" for r in rows)


def test_recording_marks_values_and_reports_the_error_rate(db, tmp_path):
    cfg, engine, proj = db
    path, items = make_csv(db, tmp_path)
    fill(path, [("ok", ""), ("ok", ""), ("error", "PDF says 1,100"), ("OK", " fine ")])
    with session_scope(engine) as s:
        summary = record_results(s, path)
    assert (summary.ok, summary.error, summary.pending) == (3, 1, 8)
    assert summary.error_rate == pytest.approx(0.25)
    with session_scope(engine) as s:
        by_id = {iv.id: iv for iv in s.scalars(select(IndicatorValue))}
    assert by_id[items[0].item_id].verified is True
    assert (
        by_id[items[2].item_id].verified is False
        and by_id[items[2].item_id].verification_note == "PDF says 1,100"
    )
    assert by_id[items[3].item_id].verification_note == "fine"
    assert by_id[items[4].item_id].verified is None  # left blank, not verified


def test_a_changed_value_blocks_recording(db, tmp_path):
    cfg, engine, proj = db
    path, items = make_csv(db, tmp_path)
    fill(path, [("ok", "")])
    with session_scope(engine) as s:
        s.get(IndicatorValue, items[0].item_id).value = D("1")
    with pytest.raises(ValueError, match="no longer matches"), session_scope(engine) as s:
        record_results(s, path)


def test_accept_auto_found_only_accepts_found_rows(db, tmp_path):
    cfg, engine, proj = db
    path, items = make_csv(db, tmp_path)
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    rows[0]["auto_check"] = "found on page(s) 15"
    rows[1]["auto_check"] = "not found as printed (PDF may use another unit)"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with session_scope(engine) as s:
        summary = record_results(s, path, accept_auto_found=True)
        assert (summary.ok, summary.pending) == (1, len(rows) - 1)
        assert (
            "(auto: found on page(s) 15)"
            in s.get(IndicatorValue, items[0].item_id).verification_note
        )


# ---- command line ------------------------------------------------------------------------------
def gauge(*args):
    return cli.invoke(app, ["--config", "config/study.yaml", *args])


def test_cli_draws_then_records(db, tmp_path):
    cfg, engine, proj = db
    out = proj / "sample.csv"
    result = gauge("verify-sample", "--fraction", "0.5", "--out", str(out))
    assert result.exit_code == 0, result.output
    assert "6 values sampled (2 companies)" in result.output and out.is_file()
    fill(out, [("ok", ""), ("error", "mismatch"), ("ok", ""), ("ok", ""), ("ok", ""), ("ok", "")])
    rec = gauge("verify-sample", "--record", str(out))
    assert (
        rec.exit_code == 1 and "5 ok, 1 errors (16.7% error rate)" in rec.output
    )  # exit 1: an error exists


def test_cli_needs_data(proj):
    from gauge.config import load_models
    from gauge.db.session import init_db
    from gauge.registry import sync_registry

    cfg = load_study("config/study.yaml")
    engine = make_engine(cfg.database_url())
    init_db(engine)
    with session_scope(engine) as s:
        sync_registry(s, cfg, load_models(cfg))
    engine.dispose()
    result = gauge("verify-sample")
    assert result.exit_code == 1 and "gauge ingest" in result.output
