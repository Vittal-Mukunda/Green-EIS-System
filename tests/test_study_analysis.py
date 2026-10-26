"""The analysis must be able to say no. Each hypothesis is checked on data built so that it should fail."""

from __future__ import annotations

import json
from decimal import Decimal as D

import numpy as np
import pandas as pd
import pytest

from greeneis.study import analysis, outcomes, proxies, synthetic
from greeneis.study.analysis import ClusterSampler, holm
from greeneis.study.cases import validate
from greeneis.study.run import SYNTHETIC_BANNER, run_study, write
from greeneis.trust import TrustConfig


def study(n=500, seed=3, **gen):
    frame = validate(synthetic.generate(n, seed, **gen)).cases
    return outcomes.evaluate(proxies.add_proxies(frame), seed=seed)


def test_holm_by_hand():
    # p = 0.01, 0.04, 0.03: sorted 0.01 x 3 = 0.03; 0.03 x 2 = 0.06; 0.04 x 1 = 0.04 -> raised to 0.06
    adj = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj == pytest.approx({"a": 0.03, "c": 0.06, "b": 0.06})
    assert holm({"a": 0.9}) == {"a": 0.9}
    assert max(holm({"a": 0.5, "b": 0.6}).values()) <= 1.0


def test_sampler_resamples_whole_clusters():
    df = pd.DataFrame({"cluster": ["a", "a", "b", "c", "c", "c"], "x": [1, 2, 3, 4, 5, 6]})
    s = ClusterSampler(df, ["x"])
    assert s.n_clusters == 3 and s.n_rows == 6
    assert s.draw(np.array([0, 0, 2])).get("x").tolist() == [1, 2, 1, 2, 4, 5, 6]
    assert s.draw(np.array([1])).get("x").tolist() == [3]


def test_h1_is_not_supported_when_estimated_is_the_worse_proxy():
    # prices vary enormously within a state-year while intensities barely vary: Default beats Estimated
    data = study(sigma_price=0.9, sigma_intensity=0.05)
    out = analysis.analyse(data, n_boot=200, seed=1)
    h1 = out["tests"]["H1"]
    assert h1["estimate"]["median_difference"] < 0
    assert h1["verdict"] == "not supported"


def test_h1_is_supported_in_the_opposite_regime():
    data = study(sigma_price=0.05, sigma_intensity=0.8)
    h1 = analysis.analyse(data, n_boot=200, seed=1)["tests"]["H1"]
    assert h1["estimate"]["median_difference"] > 0 and h1["verdict"] == "supported"


def test_h2_is_supported_for_the_placeholders_but_not_when_they_match_the_errors():
    frame = validate(synthetic.generate(600, 3)).cases
    with_proxies = proxies.add_proxies(frame)
    q90_e = with_proxies["eps_estimated"].abs().quantile(0.9)
    q90_d = with_proxies["eps_default"].abs().quantile(0.9)
    # the shipped placeholders (0.25, 0.50) are well below the synthetic errors (0.45, 0.91)
    off = analysis.analyse(outcomes.evaluate(with_proxies, seed=3), n_boot=200, seed=1)
    assert off["tests"]["H2"]["verdict"] == "supported"
    # ranges set to each class's own q90 give pooled coverage of about 92%, inside [80%, 95%]
    cfg = TrustConfig(
        uncertainty={
            "measured": D("0.01"),
            "estimated": D(str(round(q90_e, 3))),
            "default": D(str(round(q90_d, 3))),
        },
        status="calibrated",
    )
    on = analysis.analyse(
        outcomes.evaluate(with_proxies, cfg, seed=3),
        n_boot=200,
        seed=1,
        placeholder_u={k: float(v) for k, v in cfg.uncertainty.items()},
    )
    h2 = on["tests"]["H2"]
    assert 0.80 <= h2["estimate"]["pooled_coverage"] <= 0.95
    assert h2["verdict"] == "not supported"


def test_h3_needs_the_within_profile_correlation_as_well():
    data = study()
    est = analysis.analyse(data, n_boot=200, seed=1)["tests"]["H3"]["estimate"]
    assert "spearman_rho_within_random_mix" in est and "spearman_rho_pooled" in est
    assert est["spearman_rho_pooled"] < 0 and est["spearman_rho_within_random_mix"] < 0


def test_h5_is_not_supported_if_upgrading_the_largest_hotspot_is_no_better():
    data = study()
    data.h5["r_largest"] = data.h5["r_random"] - 0.01  # force largest-first to lose
    h5 = analysis.analyse(data, n_boot=200, seed=1)["tests"]["H5"]
    assert h5["estimate"]["margin_over_best_alternative"] < 0
    assert h5["verdict"] == "not supported"


def test_too_few_clusters_gives_insufficient_data_not_a_verdict():
    frame = validate(synthetic.generate(400, 3)).cases
    keep = frame["cluster"].isin(sorted(frame["cluster"].unique())[:3])
    data = outcomes.evaluate(proxies.add_proxies(frame[keep]), seed=1)
    out = analysis.analyse(data, n_boot=100, seed=1)
    assert all(t["verdict"] == "insufficient data" for t in out["tests"].values())
    assert all(t["adjusted_p"] is None for t in out["tests"].values())


def test_analysis_is_deterministic_for_a_seed():
    data = study(n=300)
    a = analysis.analyse(data, n_boot=100, seed=5)
    b = analysis.analyse(data, n_boot=100, seed=5)
    assert json.dumps(a["tests"], default=str) == json.dumps(b["tests"], default=str)


def test_run_study_marks_synthetic_results_and_writes_valid_json(tmp_path):
    result = run_study(synthetic.generate(300, 2), "synthetic", "invented", seed=2, n_boot=100)
    assert result["provenance"]["synthetic"] is True
    assert result["provenance"]["banner"] == SYNTHETIC_BANNER
    path = write(result, tmp_path / "out" / "study.json")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert set(loaded["tests"]) == {"H1", "H2", "H3", "H4", "H5"}
    assert loaded["provenance"]["trust_config"]["status"] == "placeholder"


def test_real_looking_data_is_not_marked_synthetic():
    frame = synthetic.generate(300, 2).assign(synthetic=False)
    result = run_study(frame, "csv", "reported to the government", seed=2, n_boot=100)
    assert result["provenance"]["synthetic"] is False and result["provenance"]["banner"] == ""


def test_descriptives_break_the_proxy_errors_down_by_item():
    data = study(n=400)
    by_item = analysis.descriptives(data)["item_errors_by_item"]
    assert "grid_electricity" in by_item and "coal" in by_item
    for item, cols in by_item.items():
        for col in ("eps_estimated", "eps_default"):
            assert cols[col]["n"] > 0 and 0 <= cols[col]["median_abs"] <= cols[col]["q90_abs"], item
    # the pooled figure sits between the per-item extremes (it is a mix of them)
    pooled = analysis.descriptives(data)["item_errors"]["eps_estimated"]["median_abs"]
    meds = [c["eps_estimated"]["median_abs"] for c in by_item.values()]
    assert min(meds) <= pooled <= max(meds)


def test_only_sector_keeps_that_sectors_units_and_leaves_the_default_run_alone():
    frame = synthetic.generate(400, 5)
    sector = frame["sector"].iloc[0]
    expected = frame.loc[frame["sector"] == sector, "unit_id"].nunique()
    full = run_study(frame, "x", "ref", seed=5, n_boot=20)
    cut = run_study(frame, "x", "ref", seed=5, n_boot=20, only_sector=sector)
    assert cut["provenance"]["only_sector"] == sector
    assert cut["provenance"]["units"] == expected
    assert full["provenance"]["only_sector"] is None
    assert full["provenance"]["units"] == frame["unit_id"].nunique()
