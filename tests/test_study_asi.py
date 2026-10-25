"""The ASI reader against real records and against hand-built ones.

Real fixture: factory 100002 (anonymised DSL) copied verbatim from the downloaded 2023-24 file. It is open
(status 1), has 8 persons in total (Block E serial 10), and buys electricity (item 9990500, unit 28 = kWh):
219,021.74 kWh for Rs 1,007,500 at Rs 4.60. Its petrol/diesel/oil line (9990600) has a value and no quantity.

Constructed records are laid out with the field widths printed in Data_Structure_ASI_2023_24.pdf, which are
independent of the offsets hard-coded in the reader.
"""

from __future__ import annotations

import pytest

from greeneis.study import asi, cases

REAL = """\
24A 100002999991999912007019929999  1 1             0             0             0306  0306      11466542  0    1.00000000
24E 10000210    2047       0      2047       8      2469        720500
24H 100002  10325001 27         86.00       6108767      71032.17
24H 100002 149990800  0          0.00         23220          0.00
24H 100002 169990500 28     219021.74       1007500          4.60
24H 100002 179990600  0          0.00        272000          0.00
24H 100003 169990500 28     100000.00        900000          9.00
"""
REAL_A_NOT_OPEN = "24A 100003999991999912007019929999  1 3             0             0             0  0  0  0             0  0    1.00000000\n"

A_WIDTHS = [2, 2, 6, 5, 1, 4, 5, 2, 2, 1, 4, 3, 2, 14, 14, 14, 3, 3, 3, 14, 3, 14]
E_WIDTHS = [2, 2, 6, 2, 8, 8, 10, 8, 10, 14]
H_WIDTHS = [2, 2, 6, 3, 7, 3, 14, 14, 14]


def line(widths, values):
    """A fixed-width record: values right-justified in their widths, padded to 206 characters."""
    return "".join(str(v).rjust(w) for w, v in zip(widths, values, strict=True)).ljust(206) + "\n"


def a_rec(dsl, nic5="17111", state="24", status=1, scheme=1):
    v = (
        ["24", "A", dsl, "99999", scheme, "9999", nic5, state, "99", 2, "9999", 1, status]
        + [0] * 6
        + [0, 1, 1]
    )
    # BONUS PF WELFARE MWDAYS NWDAYS WDAYS COSTOP EXPSHARE MULT -> filler values of the right widths
    v = v[:13] + [0, 0, 0, 0, 0, 0, 5000000, 0, 1]
    return line(A_WIDTHS, v)


def e_rec(dsl, persons, sl=10):
    return line(E_WIDTHS, ["24", "E", dsl, sl, 0, 0, 0, persons, 0, 0])


def h_rec(dsl, item, unit, qty, value, sl=1):
    return line(
        H_WIDTHS,
        ["24", "H", dsl, sl, item, unit, f"{qty:.2f}", value, f"{value / qty if qty else 0:.2f}"],
    )


def write(tmp_path, *records):
    path = tmp_path / "ASI_test.TXT"
    path.write_text("".join(records), encoding="latin-1")
    return path


# ---- real records -------------------------------------------------------------------------------
def test_real_records_parse_as_the_data_structure_says(tmp_path):
    blocks = asi.read_blocks(write(tmp_path, REAL, REAL_A_NOT_OPEN))
    a = blocks.a.set_index("dsl")
    assert a.loc["100002", "status"] == 1 and a.loc["100002", "state"] == "01"
    assert a.loc["100002", "nic5"] == "12007" and a.loc["100002", "scheme"] == 1
    assert a.loc["100003", "status"] == 3
    e = blocks.e
    assert e[(e["dsl"] == "100002") & (e["sl"] == 10)]["persons"].iloc[0] == 8
    h = blocks.h
    elec = h[(h["dsl"] == "100002") & (h["item"] == "9990500")].iloc[0]
    assert (elec["unit"], elec["qty"], elec["value"], elec["rate"]) == (28, 219021.74, 1007500, 4.6)
    oil = h[(h["dsl"] == "100002") & (h["item"] == "9990600")].iloc[0]
    assert oil["qty"] == 0 and oil["value"] == 272000  # a value and no quantity: unusable


def test_the_real_factory_gives_one_electricity_case(tmp_path):
    blocks = asi.read_blocks(write(tmp_path, REAL, REAL_A_NOT_OPEN))
    built = asi.build_cases(blocks, max_employees=50)
    c = built.cases
    assert len(c) == 1
    r = c.iloc[0]
    assert r["unit_id"] == "ASI2023-24-100002" and r["item_id"] == "grid_electricity"
    assert r["quantity"] == pytest.approx(219021.74) and r["value_inr"] == 1007500
    assert r["scale"] == 8 and r["sector"] == "NIC12" and r["price_group"] == "01-2023-24"
    assert bool(r["synthetic"]) is False
    # the oil line (no quantity), the packing line (no quantity) and the unopened factory are not cases
    assert built.log["open factories"] == 1 and built.log["factories in file"] == 2
    cases.validate(c)  # the shape every later stage expects


# ---- constructed records ------------------------------------------------------------------------
def build(tmp_path, *records, **kw):
    return asi.build_cases(asi.read_blocks(write(tmp_path, *records)), **kw)


def small_factory(dsl="200001", persons=12, nic5="17111", state="24", status=1):
    return [a_rec(dsl, nic5, state, status), e_rec(dsl, persons)]


def test_coal_tonnes_become_kilograms_and_gas_becomes_lpg_by_default(tmp_path):
    recs = small_factory() + [
        h_rec("200001", "9990500", 28, 50000, 400000),
        h_rec("200001", "9990700", 27, 120, 1080000, sl=2),
        h_rec("200001", "9990900", 9, 300, 21000, sl=3),
    ]
    c = build(tmp_path, *recs).cases.set_index("item_id")
    assert c.loc["coal", "quantity"] == 120000.0 and c.loc["coal", "value_inr"] == 1080000
    assert c.loc["lpg", "quantity"] == 300.0
    assert c.loc["grid_electricity", "quantity"] == 50000.0
    assert (c["scale"] == 12).all() and (c["sector"] == "NIC17").all()


def test_gas_can_be_mapped_to_natural_gas_instead(tmp_path):
    recs = small_factory() + [h_rec("200001", "9990900", 9, 300, 21000)]
    assert list(build(tmp_path, *recs, gas_item="natural_gas").cases["item_id"]) == ["natural_gas"]
    with pytest.raises(ValueError, match="gas_item"):
        build(tmp_path, *recs, gas_item="diesel")


def test_megawatt_units_convert_and_unconvertible_units_are_counted_not_guessed(tmp_path):
    recs = small_factory() + [
        h_rec("200001", "9990500", 13, 40, 320000),  # 40 MW-hours -> 40,000 kWh
        h_rec("200001", "9990700", 12, 500, 4500000, sl=2),  # coal in litres: nonsense, skipped
    ]
    built = build(tmp_path, *recs)
    assert built.cases["quantity"].tolist() == [40000.0]
    assert built.log["dropped: unit code not convertible"] == 1


def test_factories_are_filtered_by_status_size_and_industry_code(tmp_path):
    recs = []
    for dsl, persons, nic5, status in [
        ("300001", 12, "17111", 1),  # kept
        ("300002", 12, "17111", 4),  # deleted frame unit
        ("300003", 80, "17111", 1),  # too large
        ("300004", 12, "99999", 1),  # no usable industry code
    ]:
        recs += small_factory(dsl, persons, nic5, "24", status) + [
            h_rec(dsl, "9990500", 28, 1000, 8000)
        ]
    built = build(tmp_path, *recs, max_employees=50)
    assert built.cases["unit_id"].tolist() == ["ASI2023-24-300001"]
    log = built.log
    assert log["factories in file"] == 4 and log["open factories"] == 3
    assert (
        log["small (persons <= max_employees)"] == 2 and log["dropped: industry code unusable"] == 1
    )


def test_a_factory_without_a_persons_record_is_dropped(tmp_path):
    # factory 400001 has no block E record; 400099 only keeps the file's block E non-empty
    recs = [a_rec("400001"), h_rec("400001", "9990500", 28, 1000, 8000), e_rec("400099", 5)]
    built = build(tmp_path, *recs)
    assert built.cases.empty and built.log["open with persons recorded"] == 0


def test_log_counts_items_and_multi_item_factories(tmp_path):
    recs = (
        small_factory("500001", 10)
        + [
            h_rec("500001", "9990500", 28, 1000, 8000),
            h_rec("500001", "9990700", 27, 5, 50000, sl=2),
        ]
        + small_factory("500002", 10)
        + [h_rec("500002", "9990500", 28, 2000, 16000)]
    )
    log = build(tmp_path, *recs).log
    assert log["item records"] == 3 and log["factories with at least one item"] == 2
    assert log["factories with two or more items"] == 1
    assert log["records: grid_electricity"] == 2 and log["records: coal"] == 1


def test_a_file_without_input_records_is_refused(tmp_path):
    with pytest.raises(ValueError, match="merged ASI file"):
        asi.read_blocks(write(tmp_path, a_rec("600001"), e_rec("600001", 5)))
