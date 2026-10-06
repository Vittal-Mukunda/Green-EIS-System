from __future__ import annotations

import pytest
import yaml
from sqlalchemy.engine import make_url

from gauge import vocab
from gauge.config import (
    ConfigError,
    ModelsConfig,
    ModelSpec,
    assert_models_ready,
    is_placeholder,
    load_indicators,
    load_models,
    load_study,
)


# ---- study.yaml ---------------------------------------------------------------------------------
def test_real_study_sample(real_cfg):
    assert [s.name for s in real_cfg.study.sectors] == [
        "Cement",
        "Iron & Steel",
        "IT Services",
        "FMCG",
    ]
    assert real_cfg.study.companies_per_sector == 5
    assert real_cfg.n_companies == 20
    assert real_cfg.study.analysis_fy == "FY2024-25"
    assert real_cfg.study.trend_fys == ["FY2022-23", "FY2023-24", "FY2024-25"]


def test_masked_codes_are_unique_and_well_formed(real_cfg):
    codes = real_cfg.masked_codes()
    assert len(codes) == len(set(codes)) == 20
    assert all(vocab.MASKED_CODE_RE.match(c) for c in codes)
    assert codes[0] == "CEM-01" and codes[-1] == "FMC-05"


def test_run_settings(real_cfg):
    assert real_cfg.runs.conditions == ["C1", "C2"]
    assert real_cfg.runs.repetitions == 2
    assert real_cfg.runs.pause_seconds == 20
    assert real_cfg.runs.rep2_min_gap_minutes >= 60
    assert real_cfg.stats.bootstrap_resamples == 2000


def test_dry_study_is_2_by_3_and_isolated(dry_cfg):
    assert dry_cfg.n_companies == 6 and len(dry_cfg.study.sectors) == 2
    assert dry_cfg.paths.database_url.startswith("sqlite:///dry/")
    for rel in (dry_cfg.paths.runs_dir, dry_cfg.paths.rules_dir, dry_cfg.paths.sandbox_dir):
        assert rel.startswith("dry/")


def test_sqlite_url_is_anchored_at_root(real_cfg):
    db = make_url(real_cfg.database_url()).database
    assert db == (real_cfg.root / "data/processed/gauge.db").as_posix()


def _study_dict(real_cfg) -> dict:
    return yaml.safe_load((real_cfg.root / "config/study.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["study"].update(companies_per_sector=11),
        lambda d: d["study"].update(trend_fys=["FY2021-22", "FY2022-23", "FY2023-24"]),
        lambda d: d["study"].update(analysis_fy="2024-25"),
        lambda d: d["runs"].update(conditions=["C1", "C3"]),
        lambda d: d["runs"].update(typo_key=1),
    ],
)
def test_invalid_study_configs_are_rejected(real_cfg, proj, mutate):
    data = _study_dict(real_cfg)
    mutate(data)
    (proj / "config/bad.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_study("config/bad.yaml")


def test_missing_config_file(proj):
    with pytest.raises(ConfigError, match="not found"):
        load_study("config/nope.yaml")


# ---- models.yaml --------------------------------------------------------------------------------
def test_real_panel_shape(real_cfg):
    models = load_models(real_cfg)
    assert [m.key for m in models.by_role("primary")] == ["P1", "P2", "P3", "P4"]
    assert [m.key for m in models.by_role("baseline")] == ["B1"]
    assert models.by_role("sensitivity") == []  # disabled by default
    assert all(m.channel == "cursor" for m in models.by_role("primary"))
    base = models.by_role("baseline")[0]
    assert base.channel == "api" and base.name.endswith(":free")
    assert models.api.temperature == 0


@pytest.mark.parametrize("name", ["", "auto", "Auto", "TODO_FILL_FROM_CURSOR_LIST", "todo", "  "])
def test_placeholder_names_detected(name):
    assert is_placeholder(name)


@pytest.mark.parametrize("name", ["gpt-5", "gemini-2.5-pro", "openai/gpt-oss-120b:free"])
def test_real_looking_names_are_not_placeholders(name):
    assert not is_placeholder(name)


def test_real_config_refuses_to_run_with_placeholders(real_cfg):
    with pytest.raises(ConfigError, match="placeholder") as exc:
        assert_models_ready(load_models(real_cfg))
    for key in ("P1", "P2", "P3", "P4"):
        assert key in str(exc.value)
    assert "B1" not in str(exc.value)  # the baseline id is already a concrete name


def test_dry_models_pass_readiness_without_cursor(dry_cfg):
    models = load_models(dry_cfg)
    assert all(m.channel == "mock" for m in models.enabled())
    assert_models_ready(models)


def _spec(key="P1", **kw) -> dict:
    base = dict(key=key, role="primary", channel="cursor", vendor="vendor", name="model-x")
    return {**base, **kw}


def _panel(names, listed_baseline="oss/model:free") -> ModelsConfig:
    primaries = [_spec(f"P{i + 1}", vendor=f"v{i}", name=n) for i, n in enumerate(names)]
    baseline = dict(
        key="B1",
        role="baseline",
        channel="api",
        provider="openrouter",
        vendor="o",
        name=listed_baseline,
    )
    return ModelsConfig(models=[*primaries, baseline])


def test_model_must_appear_in_cli_listing():
    models = _panel(["a", "b", "c", "d"])
    assert_models_ready(models, cli_listed={"a", "b", "c", "d"})
    with pytest.raises(ConfigError, match="not in the Cursor CLI model list"):
        assert_models_ready(models, cli_listed={"a", "b", "c"})


def test_listing_is_not_applied_to_api_baseline():
    assert_models_ready(_panel(["a", "b", "c", "d"]), cli_listed={"a", "b", "c", "d"})


@pytest.mark.parametrize(
    "spec, message",
    [
        (
            dict(
                key="B1",
                role="baseline",
                channel="api",
                provider="openrouter",
                vendor="o",
                name="openai/gpt-oss-120b",
            ),
            "':free'",
        ),
        (_spec(vendor="Anthropic", name="some-model"), "Claude"),
        (_spec(name="claude-sonnet"), "Claude"),
        (dict(key="B1", role="baseline", channel="cursor", vendor="o", name="x"), "baseline"),
        (_spec(channel="api", provider="openrouter", name="x:free"), "primary panel"),
        (_spec(error_rate=0.1), "mock"),
    ],
)
def test_invalid_model_specs_rejected(spec, message):
    with pytest.raises(ValueError, match=message):
        ModelSpec(**spec)


def test_baseline_temperature_must_be_zero():
    good = _panel(["a", "b", "c", "d"])
    with pytest.raises(ValueError, match="temperature"):
        ModelsConfig(models=good.models, api={"temperature": 0.7})


def test_panel_needs_four_primaries_and_one_baseline():
    with pytest.raises(ValueError, match="exactly 4"):
        _panel(["a", "b", "c"])


def test_claude_sensitivity_model_allowed_when_enabled():
    sens = ModelSpec(**_spec("S1", role="sensitivity", vendor="Anthropic", name="claude-x"))
    models = ModelsConfig(models=[*_panel(["a", "b", "c", "d"]).models, sens])
    assert [m.key for m in models.by_role("sensitivity")] == ["S1"]


# ---- indicators.yaml ----------------------------------------------------------------------------
def test_indicator_catalogue(real_cfg):
    ind = load_indicators(real_cfg)
    assert len(ind.indicators) == 9
    assert {k.code for k in ind.core_kpis} == {
        "emissions_intensity",
        "water_intensity",
        "renewable_share",
    }
    better = {k.code: k.better for k in ind.kpis}
    assert better["emissions_intensity"] == "lower" and better["renewable_share"] == "higher"
    assert not any(i.rankable for i in ind.indicators)  # hard rule 10
    labels = ind.driver_labels
    assert len(labels) == len(set(labels))


def test_unverified_brsr_fields_are_marked_todo(real_cfg):
    """Hard rule 8: no BRSR/XBRL field name is guessed."""
    ind = load_indicators(real_cfg)
    assert all(
        i.brsr_ref == "TODO(verify)" and i.xbrl_element == "TODO(verify)" for i in ind.indicators
    )
