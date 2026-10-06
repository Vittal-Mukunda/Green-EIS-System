"""Evidence, rule files and the C1/C2 prompt renderer (spec 4.3-4.5).

The headline checks: every C1 value appears identically in C2; C2 differs from C1 only by the added
context; the T2 class can be derived from the PROMPT TEXT ALONE and equals the rule's answer; no
real identity string can reach a prompt.
"""

from __future__ import annotations

import re
from decimal import Decimal

import numpy as np
import pytest
import yaml
from sqlalchemy import select, update

from gauge.db.models import Company, KpiValue
from gauge.db.session import session_scope
from gauge.render.evidence import EvidenceError, load_evidence
from gauge.render.prompts import (
    SEPARATOR,
    RenderError,
    assert_no_identity_leak,
    company_block,
    describe_t2_rule,
    fill,
    find_identity_leaks,
    identity_strings,
    load_templates,
    num,
    render_prompt,
)
from gauge.render.runs import prepare_render, render_condition, render_run_prompts
from gauge.rules.build import (
    build_t2_rule,
    check_rule_matches_evidence,
    load_t2_rule,
    rule_to_yaml,
    t2_path,
)
from gauge.rules.rounding import sig_round
from gauge.rules.t2 import apply_t2
from gauge.runner.mock import CODE_RE, codes_in_prompt

D = Decimal


# ---- number formatting ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, text",
    [
        ("5227.00", "5,227"),  # rounding to 6 s.f. must not read as extra precision
        ("75.20", "75.2"),
        ("100.0", "100"),
        ("1.093E+3", "1,093"),
        ("623800000", "623,800,000"),
        ("0.0001234", "0.0001234"),
        ("0", "0"),
        ("1000", "1,000"),
        ("12.99", "12.99"),
    ],
)
def test_num_formats_without_padding_or_exponent(value, text):
    assert num(D(value)) == text


# ---- evidence ------------------------------------------------------------------------------------
def test_evidence_is_rounded_once_from_the_database(world):
    with session_scope(world.engine) as session:
        ev = load_evidence(session, world.cfg, world.ind)
        stored = {(k.company_id, k.fy, k.kpi): k.value for k in session.scalars(select(KpiValue))}
        by_code = {c.code: c.id for c in session.scalars(select(Company))}
    assert len(ev.companies) == 6 and ev.synthetic and not ev.provisional and ev.has_trend
    for code, ce in ev.companies.items():
        for kpi, shown in ce.kpis.items():
            assert shown == sig_round(stored[(by_code[code], ev.analysis_fy, kpi)], 4)
            assert shown == ce.trend[kpi][ev.analysis_fy]  # same number in C1 and the C2 trend
        for value in [*ce.kpis.values(), *(v for t in ce.trend.values() for v in t.values())]:
            assert value is None or value == sig_round(value, 4)  # idempotent: rounded once


def test_planted_gap_is_stated_as_not_reported_never_filled(world):
    with session_scope(world.engine) as session:
        ev = load_evidence(session, world.cfg, world.ind)
    # the synthetic data omit SYNB3's FY2022-23 waste_generated: one waste-recovery trend cell
    assert ev.n_not_reported == 1
    gaps = [
        (ce.code, kpi, fy)
        for ce in ev.companies.values()
        for kpi, years in ce.trend.items()
        for fy, v in years.items()
        if v is None
    ]
    assert len(gaps) == 1 and gaps[0][1:] == ("waste_recovery_rate", "FY2022-23")


def test_a_missing_core_kpi_refuses_the_evidence_and_names_it(world):
    with session_scope(world.engine) as session:
        company = session.scalar(select(Company).order_by(Company.code))
        session.execute(
            update(KpiValue)
            .where(KpiValue.company_id == company.id, KpiValue.kpi == "water_intensity")
            .where(KpiValue.fy == "FY2023-24")
            .values(kpi="water_intensity_x")  # i.e. the value is no longer there
        )
    with session_scope(world.engine) as session:
        with pytest.raises(EvidenceError, match="core KPI water_intensity missing for"):
            load_evidence(session, world.cfg, world.ind)
        # without trends only the analysis year is needed, so it still loads
        assert load_evidence(session, world.cfg, world.ind, with_trend=False).companies


def test_only_included_companies_unless_provisional(world):
    with session_scope(world.engine) as session:
        company = session.scalar(select(Company).order_by(Company.code))
        company.selection_status = "candidate"
        code = company.code
    with session_scope(world.engine) as session:
        assert code not in load_evidence(session, world.cfg, world.ind).companies
        ev = load_evidence(session, world.cfg, world.ind, provisional=True)
        assert code in ev.companies and ev.provisional


def test_no_included_companies_is_a_clear_error(world):
    with session_scope(world.engine) as session:
        for c in session.scalars(select(Company)):
            c.selection_status = "candidate"
    with (
        session_scope(world.engine) as session,
        pytest.raises(EvidenceError, match="no `included` companies"),
    ):
        load_evidence(session, world.cfg, world.ind)


def test_real_and_synthetic_companies_never_mix(world):
    with session_scope(world.engine) as session:
        session.scalar(select(Company).order_by(Company.code)).is_synthetic = False
    with session_scope(world.engine) as session, pytest.raises(EvidenceError, match="mixed"):
        load_evidence(session, world.cfg, world.ind)


# ---- rule files ----------------------------------------------------------------------------------
def test_t2_cut_points_are_the_tertiles_of_the_displayed_data(world):
    """Independent check with numpy: the file's cut-points are the 1/3 and 2/3 quantiles (linear
    interpolation) of the sector's KPI values, rounded to 4 significant figures."""
    with session_scope(world.engine) as session:
        ev = load_evidence(session, world.cfg, world.ind)
        raw = {}
        by_company = {c.id: c for c in session.scalars(select(Company))}
        for k in session.scalars(select(KpiValue).where(KpiValue.fy == ev.analysis_fy)):
            sector = ev.companies[by_company[k.company_id].code].sector
            raw.setdefault((sector, k.kpi), []).append(float(k.value))
    rule = build_t2_rule(ev, world.cfg, world.ind)
    assert set(rule.cut_points) == {"Synthetic Alpha", "Synthetic Beta"}
    for sector, per_kpi in rule.cut_points.items():
        for kpi, cuts in per_kpi.items():
            values = raw[(sector, kpi)]
            low, high = np.percentile(values, [100 / 3, 200 / 3])
            assert float(cuts.p33) == pytest.approx(low, rel=1e-3)
            assert float(cuts.p67) == pytest.approx(high, rel=1e-3)
            assert cuts.n == len(values) == 3
            assert cuts.p33 == sig_round(cuts.p33, 4)


def test_rule_file_round_trips_and_stores_numbers_as_strings(ctx, world):
    path = t2_path(world.cfg)
    assert path.is_file()
    loaded = load_t2_rule(path)
    assert loaded == ctx.rule
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for per_kpi in raw["cut_points"].values():
        for cuts in per_kpi.values():
            assert isinstance(cuts["p33"], str) and "E" not in cuts["p33"].upper()
    assert "\r" not in path.read_text(encoding="utf-8")  # LF only: stable SHA-256
    assert rule_to_yaml(loaded).startswith("# T2 rule")


def test_stale_rule_is_detected(ctx, world):
    with session_scope(world.engine) as session:
        ev = load_evidence(session, world.cfg, world.ind)
    assert check_rule_matches_evidence(ctx.rule, ev) == []
    sector = next(iter(ctx.rule.cut_points))
    tampered = ctx.rule.model_copy(deep=True)
    tampered.cut_points[sector]["water_intensity"].p33 += 1
    problems = check_rule_matches_evidence(tampered, ev)
    assert len(problems) == 1 and "water_intensity" in problems[0]


def test_stale_rule_blocks_rendering(ctx, world):
    path = t2_path(world.cfg)
    text = path.read_text(encoding="utf-8")
    path.write_bytes(text.replace("n: 3", "n: 4", 1).encode("utf-8"))
    with (
        session_scope(world.engine) as session,
        pytest.raises(RenderError, match="does not match the current benchmarks"),
    ):
        prepare_render(session, world.cfg, world.ind)


# ---- templates -----------------------------------------------------------------------------------
def test_fill_is_strict_both_ways():
    assert fill("a {{X}} b", {"X": "1"}, name="t") == "a 1 b\n"
    with pytest.raises(RenderError, match="unfilled"):
        fill("a {{X}} {{Y}}", {"X": "1"}, name="t")
    with pytest.raises(RenderError, match="unused"):
        fill("a {{X}}", {"X": "1", "Z": "2"}, name="t")


def test_repository_templates_have_the_expected_placeholders(repo_root):
    from gauge.render.prompts import PLACEHOLDER_RE

    folder = repo_root / "registry" / "prompts"
    found = {
        p.name: set(PLACEHOLDER_RE.findall(p.read_text(encoding="utf-8")))
        for p in folder.glob("*.md")
    }
    assert found["system_v1.md"] == {
        "ANALYSIS_FY", "T2_RULE", "CUTPOINTS", "KPI_DEFINITIONS", "DRIVER_NAMES", "N_DRIVERS",
        "MAX_WORDS",
    }  # fmt: skip
    assert found["c1_user_v1.md"] == {"N_COMPANIES", "ANALYSIS_FY", "COMPANY_BLOCKS"}
    assert found["c2_user_v1.md"] == found["c1_user_v1.md"] | {"TREND_FYS"}
    for path in folder.glob("*.md"):
        assert "\r" not in path.read_text(encoding="utf-8", errors="strict"), path.name


def test_missing_template_is_reported(world):
    (world.cfg.path(world.cfg.paths.prompts_registry_dir) / "c2_user_v1.md").unlink()
    with pytest.raises(RenderError, match="c2_user_v1.md"):
        load_templates(world.cfg)


# ---- rendered prompts ----------------------------------------------------------------------------
def headings(user_text: str) -> list[str]:
    return re.findall(r"^## ([A-Z]{3}-\d{2})$", user_text, re.MULTILINE)


def test_c2_contains_every_c1_company_block_verbatim(ctx, world):
    c1 = render_condition(world.cfg, world.ind, ctx, "C1")
    c2 = render_condition(world.cfg, world.ind, ctx, "C2")
    assert len(headings(c1.user)) == len(headings(c2.user)) == 6
    for code, ce in ctx.evidence.companies.items():
        block = company_block(ce, world.ind, ctx.evidence.analysis_fy)
        assert block in c1.user and block in c2.user, code
    # and line by line: every table row of C1 is a row of C2
    c2_lines = set(c2.user.splitlines())
    missing = [
        line for line in c1.user.splitlines() if line.startswith("|") and line not in c2_lines
    ]
    assert missing == []


def test_c2_differs_from_c1_only_by_the_added_context(ctx, world):
    c1 = render_condition(world.cfg, world.ind, ctx, "C1")
    c2 = render_condition(world.cfg, world.ind, ctx, "C2")
    assert c1.system == c2.system  # identical instructions, rule and cut-points
    stripped = re.sub(
        r"\n\nContext for [A-Z]{3}-\d{2} .*?(?=\n\n## |\n\n# )", "", c2.user, flags=re.S
    )
    intro1 = re.search(r"# Evidence\n\n(.*?)\n\n## ", c1.user, re.S).group(1)
    intro2 = re.search(r"# Evidence\n\n(.*?)\n\n## ", stripped, re.S).group(1)
    assert intro1 != intro2 and "context table" in intro2 and "context table" not in intro1
    assert stripped.replace(intro2, intro1) == c1.user


def test_context_exists_only_in_c2_and_agrees_with_c1(ctx, world):
    c1 = render_condition(world.cfg, world.ind, ctx, "C1")
    c2 = render_condition(world.cfg, world.ind, ctx, "C2")
    assert "Context for" not in c1.user and "Sector median" not in c1.user + c1.system
    assert c2.user.count("Context for") == 6
    year_cols = (
        "| KPI | FY2022-23 | FY2023-24 | FY2024-25 "
        "| Sector P25 | Sector median | Sector P75 | Unit |"
    )
    assert c2.user.count(year_cols) == 6
    # the FY2024-25 column of every context table equals the C1 derived-KPI value
    for ce in ctx.evidence.companies.values():
        for kpi in world.ind.kpis:
            shown = ce.kpis[kpi.code]
            if shown is None:
                continue
            row = f"| {kpi.label} | {num(shown)} | {kpi.unit.replace('_', ' ')} |"
            assert row in c1.user
            assert f"| {num(ce.trend[kpi.code]['FY2024-25'])} |" in c2.user


def test_company_order_is_followed_and_complete(ctx, world):
    codes = sorted(ctx.evidence.companies)
    order = tuple(reversed(codes))
    prompt = render_condition(world.cfg, world.ind, ctx, "C2", order)
    assert tuple(headings(prompt.user)) == order
    with pytest.raises(RenderError, match="exactly once"):
        render_condition(world.cfg, world.ind, ctx, "C1", tuple(codes[:-1]))
    with pytest.raises(RenderError, match="exactly once"):
        render_condition(world.cfg, world.ind, ctx, "C1", (*codes, codes[0]))


def company_blocks(prompt) -> list[str]:
    body = prompt.user.split("\n\n# Your answer")[0]
    return re.split(r"\n\n(?=## [A-Z]{3}-\d{2}\n)", body)[1:]


def test_rendering_is_deterministic_and_order_changes_only_the_order(ctx, world):
    codes = sorted(ctx.evidence.companies)
    a = render_condition(world.cfg, world.ind, ctx, "C2", tuple(codes))
    assert a.sha256 == render_condition(world.cfg, world.ind, ctx, "C2", tuple(codes)).sha256
    b = render_condition(world.cfg, world.ind, ctx, "C2", tuple(reversed(codes)))
    assert a.sha256 != b.sha256 and a.system == b.system
    assert len(company_blocks(a)) == 6
    assert sorted(company_blocks(a)) == sorted(company_blocks(b))  # same blocks, other order


def test_the_mock_runner_finds_exactly_the_company_codes(ctx, world):
    """Instructions and tables must not contain anything shaped like a company code."""
    prompt = render_condition(world.cfg, world.ind, ctx, "C2")
    assert CODE_RE.findall(prompt.system) == []
    assert codes_in_prompt(prompt.combined) == headings(prompt.user)


def test_channel_split_is_the_same_text(ctx, world):
    p = render_condition(world.cfg, world.ind, ctx, "C1")
    assert p.combined == p.system.rstrip("\n") + SEPARATOR + p.user
    assert p.for_channel("cursor") == (p.combined, None)
    assert p.for_channel("mock") == (p.combined, None)
    assert p.for_channel("api") == (p.user, p.system)
    assert len({p.sha256, p.system_sha256, p.user_sha256}) == 3


def test_no_exponents_or_python_artifacts_in_prompts(ctx, world):
    for cond in ("C1", "C2"):
        text = render_condition(world.cfg, world.ind, ctx, cond).combined
        assert (
            not re.search(r"\d[eE][+-]?\d", text) and "Decimal(" not in text and "None" not in text
        )
        assert "\r" not in text and "{{" not in text and "}}" not in text


def test_t2_text_states_the_rule_the_code_applies(ctx, world):
    text = describe_t2_rule(ctx.rule, world.ind)
    assert (
        "| Emissions intensity (Scope 1+2) | lower | at most the low cut-point | above the low "
        in text
    )
    assert (
        "| Renewable energy share | higher | at least the high cut-point | at least the low "
        in text
    )
    assert "Total 5 to 6: Leader. Total 2 to 4: Average. Total 0 to 1: Laggard." in text
    assert "belongs to the better of the two tertiles" in text


# ---- the class is derivable from the prompt text alone ------------------------------------------
KPI_BETTER = {
    "Emissions intensity (Scope 1+2)": "lower",
    "Water intensity": "lower",
    "Renewable energy share": "higher",
}


def parse_cutpoints(system: str) -> dict[str, dict[str, tuple[Decimal, Decimal]]]:
    out: dict[str, dict[str, tuple[Decimal, Decimal]]] = {}
    sector = None
    for line in system.splitlines():
        if m := re.match(r"^Sector: (.+?) \(cut-points from", line):
            sector = m.group(1)
            out[sector] = {}
        elif m := re.match(r"^\| (.+?) \| .+? \| ([\d,.]+) \| ([\d,.]+) \|$", line):
            if sector and m.group(1) in KPI_BETTER:
                out[sector][m.group(1)] = (
                    D(m.group(2).replace(",", "")),
                    D(m.group(3).replace(",", "")),
                )
    return out


def classify_from_text(user: str, cuts) -> dict[str, str]:
    """An independent reader of the prompt: parse the tables, apply the printed rule."""
    result = {}
    for block in re.split(r"\n\n(?=## [A-Z]{3}-\d{2}\n)", user)[1:]:
        code = re.match(r"## ([A-Z]{3}-\d{2})", block).group(1)
        sector = re.search(r"^Sector: (.+)$", block, re.M).group(1)
        total = 0
        for label, better in KPI_BETTER.items():
            m = re.search(rf"^\| {re.escape(label)} \| ([\d,.]+) \| [^|]+ \|$", block, re.M)
            value = D(m.group(1).replace(",", ""))
            low, high = cuts[sector][label]
            if better == "lower":
                total += 2 if value <= low else (0 if value > high else 1)
            else:
                total += 2 if value >= high else (0 if value < low else 1)
        result[code] = "Leader" if total >= 5 else ("Average" if total >= 2 else "Laggard")
    return result


@pytest.mark.parametrize("condition", ["C1", "C2"])
def test_t2_class_is_derivable_from_the_prompt_text_alone(ctx, world, condition):
    prompt = render_condition(world.cfg, world.ind, ctx, condition)
    from_text = classify_from_text(prompt.user, parse_cutpoints(prompt.system))
    assert len(from_text) == 6
    for code, ce in ctx.evidence.companies.items():
        values = {k.code: ce.kpis[k.code] for k in world.ind.core_kpis}
        assert from_text[code] == apply_t2(ctx.rule, ce.sector, values).t2_class, code
    # a rule that is not degenerate: the synthetic sample has more than one class
    assert len(set(from_text.values())) > 1


def test_t2_class_is_identical_under_c1_and_c2(ctx, world):
    cuts = parse_cutpoints(render_condition(world.cfg, world.ind, ctx, "C1").system)
    c1 = classify_from_text(render_condition(world.cfg, world.ind, ctx, "C1").user, cuts)
    c2 = classify_from_text(render_condition(world.cfg, world.ind, ctx, "C2").user, cuts)
    assert c1 == c2


# ---- masking (hard rule 9) -----------------------------------------------------------------------
def test_identity_leak_guard_uses_whole_words_only():
    ids = ["ACC", "Shree Cement", "INE070A01015", "Tata Steel"]
    assert find_identity_leaks("the acc figure", ids) == ["ACC"]
    assert find_identity_leaks("accurate accounts", ids) == []  # not a whole word
    assert find_identity_leaks("SHREE CEMENT reported", ids) == ["Shree Cement"]
    assert find_identity_leaks("isin ine070a01015.", ids) == ["INE070A01015"]
    assert find_identity_leaks("CEM-03 and STL-01", ids) == []


def make_real(world):
    """Turn the synthetic companies into 'real' ones, with names a leak would show."""
    with session_scope(world.engine) as session:
        for i, c in enumerate(session.scalars(select(Company).order_by(Company.code)), start=1):
            c.is_synthetic = False
            c.real_name = f"Acme{i} Industries Limited"
            c.nse_symbol = f"ACME{i}"
            c.isin = f"INE00000A{i:03d}"


def test_identities_come_from_names_symbols_and_isins(world):
    make_real(world)
    with session_scope(world.engine) as session:
        ids = identity_strings(session)
    assert "Acme1 Industries Limited" in ids and "Acme1 Industries" in ids
    assert "ACME1" in ids and "INE00000A001" in ids


def test_synthetic_companies_are_not_treated_as_identities(world):
    with session_scope(world.engine) as session:
        assert identity_strings(session) == []


def test_a_leaking_template_is_refused(ctx, world):
    make_real(world)
    folder = world.cfg.path(world.cfg.paths.prompts_registry_dir)
    path = folder / "c1_user_v1.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nSource: Acme3 Industries Limited.\n", encoding="utf-8"
    )
    with session_scope(world.engine) as session:
        # the rule file must still match: real flags do not change the numbers
        rctx = prepare_render(session, world.cfg, world.ind)
    assert rctx.identities  # the guard is armed
    with pytest.raises(RenderError, match="identity strings .*Acme3 Industries"):
        render_condition(world.cfg, world.ind, rctx, "C1")
    render_condition(world.cfg, world.ind, rctx, "C2")  # C2 template is untouched: renders
    prompt = render_prompt(
        cfg=world.cfg, indicators=world.ind, evidence=rctx.evidence, rule=rctx.rule,
        templates=rctx.templates, condition="C1",
    )  # fmt: skip
    with pytest.raises(RenderError):
        assert_no_identity_leak(prompt, rctx.identities)


def test_real_data_prompts_carry_codes_only(ctx, world):
    make_real(world)
    with session_scope(world.engine) as session:
        rctx = prepare_render(session, world.cfg, world.ind)
    for cond in ("C1", "C2"):
        text = render_condition(world.cfg, world.ind, rctx, cond).combined
        assert "Acme" not in text and "INE0" not in text and "ACME" not in text


# ---- one prompt per run ------------------------------------------------------------------
def test_every_planned_run_gets_its_own_order_and_a_matching_prompt(ctx, world):
    runs = render_run_prompts(world.cfg, world.ind, world.models, ctx)
    assert len(runs) == 20 and len({r.planned.run_id for r in runs}) == 20
    for rp in runs:
        assert tuple(headings(rp.prompt.user)) == rp.planned.company_order
        assert rp.prompt.condition == rp.planned.condition
    assert len({rp.planned.company_order for rp in runs}) > 1  # orders really are shuffled
    again = render_run_prompts(world.cfg, world.ind, world.models, ctx)
    assert [r.prompt.sha256 for r in runs] == [r.prompt.sha256 for r in again]


def test_the_prompt_never_depends_on_the_model_name(ctx, world):
    """Only (condition, order) matter: renaming a model cannot change a frozen prompt."""
    before = {
        r.planned.run_id: r.prompt.sha256
        for r in render_run_prompts(world.cfg, world.ind, world.models, ctx)
    }
    renamed = world.models.model_copy(deep=True)
    for m in renamed.models:
        m.name = m.name + "-renamed"
    after = {
        r.planned.run_id: r.prompt.sha256
        for r in render_run_prompts(world.cfg, world.ind, renamed, ctx)
    }
    assert before == after


def test_disabled_models_are_planned_only_on_request(ctx, world):
    models = world.models.model_copy(deep=True)
    models.models[-1].enabled = False
    default = render_run_prompts(world.cfg, world.ind, models, ctx)
    everything = render_run_prompts(world.cfg, world.ind, models, ctx, include_disabled=True)
    assert len(everything) == len(default) + 4  # 1 model x 2 conditions x 2 repetitions
