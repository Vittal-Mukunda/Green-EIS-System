"""XBRL reader. The instance below is SYNTHETIC: its element names (`syn:`) are invented for the
test and are not BRSR names. The reader must work on any instance without knowing element names."""

from __future__ import annotations

import csv

import pytest
from defusedxml.common import DefusedXmlException
from typer.testing import CliRunner

from gauge.cli import app
from gauge.ingest.xbrl import read_instance, summarize, write_facts_csv

SYNTHETIC_INSTANCE = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
            xmlns:syn="http://example.invalid/synthetic">
  <link:schemaRef xlink:type="simple" xlink:href="synthetic-taxonomy.xsd"/>
  <xbrli:context id="D1">
    <xbrli:entity><xbrli:identifier scheme="http://example.invalid/id">SYN001</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-04-01</xbrli:startDate><xbrli:endDate>2025-03-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="I1">
    <xbrli:entity><xbrli:identifier scheme="http://example.invalid/id">SYN001</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2025-03-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:context id="D1_dim">
    <xbrli:entity>
      <xbrli:identifier scheme="http://example.invalid/id">SYN001</xbrli:identifier>
      <xbrli:segment><xbrldi:explicitMember dimension="syn:BoundaryAxis">syn:StandaloneMember</xbrldi:explicitMember></xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-04-01</xbrli:startDate><xbrli:endDate>2025-03-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
  <xbrli:unit id="Per"><xbrli:divide>
    <xbrli:unitNumerator><xbrli:measure>syn:gigajoule</xbrli:measure></xbrli:unitNumerator>
    <xbrli:unitDenominator><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unitDenominator>
  </xbrli:divide></xbrli:unit>
  <syn:SyntheticRevenue contextRef="D1" unitRef="INR" decimals="-5">1234500000</syn:SyntheticRevenue>
  <syn:SyntheticRevenue contextRef="D1_dim" unitRef="INR" decimals="-5">99</syn:SyntheticRevenue>
  <syn:SyntheticIntensity contextRef="D1" unitRef="Per" decimals="4">0.0123</syn:SyntheticIntensity>
  <syn:SyntheticMissing contextRef="D1" unitRef="INR" xsi:nil="true"/>
  <syn:SyntheticNote contextRef="I1">free text value</syn:SyntheticNote>
</xbrli:xbrl>
"""


@pytest.fixture
def instance_path(tmp_path):
    path = tmp_path / "synthetic.xml"
    path.write_text(SYNTHETIC_INSTANCE, encoding="utf-8")
    return path


def test_reads_facts_contexts_and_units(instance_path):
    inst = read_instance(instance_path)
    assert len(inst.facts) == 5 and len(inst.contexts) == 3 and len(inst.units) == 2
    assert inst.schema_refs == ["synthetic-taxonomy.xsd"]
    assert len(inst.sha256) == 64
    revenue = [f for f in inst.facts if f.element == "syn:SyntheticRevenue"]
    assert [f.value for f in revenue] == ["1234500000", "99"]
    assert revenue[0].decimals == "-5" and revenue[0].unit_id == "INR"


def test_context_periods_and_dimensions(instance_path):
    ctx = read_instance(instance_path).contexts
    assert ctx["D1"].period == "2024-04-01..2025-03-31" and ctx["D1"].dimensions == ()
    assert ctx["I1"].period == "instant:2025-03-31"
    assert ctx["D1_dim"].dimensions == ("syn:BoundaryAxis=syn:StandaloneMember",)
    assert ctx["D1"].entity == "http://example.invalid/id|SYN001"


def test_units_including_divide(instance_path):
    units = read_instance(instance_path).units
    assert units["INR"].measure == "iso4217:INR"
    assert units["Per"].measure == "syn:gigajoule/iso4217:INR"


def test_nil_and_non_numeric_facts(instance_path):
    facts = {f.element: f for f in read_instance(instance_path).facts}
    assert facts["syn:SyntheticMissing"].nil and facts["syn:SyntheticMissing"].value == ""
    assert facts["syn:SyntheticNote"].unit_id is None


def test_summary_mentions_what_a_mapping_author_needs(instance_path):
    text = summarize(read_instance(instance_path))
    for needle in (
        "5 (4 numeric, 1 nil)",
        "syn:SyntheticRevenue",
        "iso4217:INR",
        "syn:BoundaryAxis=syn:StandaloneMember",
        "2024-04-01..2025-03-31",
    ):
        assert needle in text


def test_summary_warns_about_undeclared_contexts(tmp_path):
    path = tmp_path / "x.xml"
    path.write_text(
        SYNTHETIC_INSTANCE.replace('contextRef="I1"', 'contextRef="NOPE"'), encoding="utf-8"
    )
    assert "undeclared contexts: ['NOPE']" in summarize(read_instance(path))


def test_facts_csv(instance_path, tmp_path):
    out = tmp_path / "facts.csv"
    assert write_facts_csv(read_instance(instance_path), out) == 5
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    dim = next(r for r in rows if r["value"] == "99")
    assert dim["dimensions"] == "syn:BoundaryAxis=syn:StandaloneMember"
    assert dim["unit"] == "iso4217:INR" and dim["period"] == "2024-04-01..2025-03-31"


def test_rejects_entity_expansion_attacks(tmp_path):
    bomb = tmp_path / "bomb.xml"
    bomb.write_text(
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">&b;</xbrli:xbrl>',
        encoding="utf-8",
    )
    with pytest.raises(DefusedXmlException):
        read_instance(bomb)


def test_rejects_external_entities(tmp_path):
    xxe = tmp_path / "xxe.xml"
    xxe.write_text(
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">&e;</xbrli:xbrl>',
        encoding="utf-8",
    )
    with pytest.raises(DefusedXmlException):
        read_instance(xxe)


def test_malformed_xml_raises(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<xbrli:xbrl", encoding="utf-8")
    with pytest.raises(Exception):  # noqa: B017 - any parse error is acceptable here
        read_instance(bad)


# ---- CLI ----------------------------------------------------------------------------------------
def test_cli_inspect_and_facts_csv(proj, instance_path, tmp_path):
    out = tmp_path / "f.csv"
    result = CliRunner().invoke(
        app, ["ingest", "--inspect-xbrl", str(instance_path), "--facts-csv", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "syn:SyntheticRevenue" in result.output and "wrote 5 facts" in result.output
    assert out.is_file()


def test_cli_ingest_needs_exactly_one_source(proj, instance_path):
    runner = CliRunner()
    assert runner.invoke(app, ["ingest"]).exit_code != 0
    both = ["ingest", "--manual", "x.csv", "--inspect-xbrl", str(instance_path)]
    assert runner.invoke(app, both).exit_code != 0
