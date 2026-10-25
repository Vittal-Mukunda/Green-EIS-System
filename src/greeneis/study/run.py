"""Run the study end to end and write the result to JSON.

    python -m greeneis.study.run --source synthetic --units 600 --seed 7 --out outputs/study_synthetic.json
    python -m greeneis.study.run --source csv --path my_cases.csv --out outputs/study_real.json

The output records where the data came from; results from synthetic data carry a banner everywhere they
are shown. The reference quantity's nature (reported or metered) is a property of the source and is stated
with `--reference`.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ..trust import TrustConfig
from . import analysis, cases, outcomes, proxies, synthetic

SYNTHETIC_BANNER = (
    "SYNTHETIC DATA: generated to exercise the pipeline. The errors below come from the generator's "
    "settings, not from any real unit. These results say nothing about the world."
)


def _json_default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(type(o))


def run_study(
    frame,
    source: str,
    reference: str,
    seed: int = 0,
    n_boot: int = 1000,
    cfg: TrustConfig | None = None,
) -> dict:
    cfg = cfg or TrustConfig()
    valid = cases.validate(frame)
    with_proxies = proxies.add_proxies(valid.cases)
    data = outcomes.evaluate(with_proxies, cfg, seed=seed)
    result = analysis.analyse(data, n_boot=n_boot, seed=seed)
    is_synth = bool(valid.cases["synthetic"].all())
    result["provenance"] = {
        "source": source,
        "synthetic": is_synth,
        "banner": SYNTHETIC_BANNER if is_synth else "",
        "reference_quantity": reference,
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows_dropped": valid.dropped,
        "units": int(valid.cases["unit_id"].nunique()),
        "rows": int(len(valid.cases)),
        "clusters": int(valid.cases["cluster"].nunique()),
        "trust_config": {
            "status": cfg.status,
            "scores": {k: str(v) for k, v in cfg.scores.items()},
            "uncertainty": {k: str(v) for k, v in cfg.uncertainty.items()},
        },
        "profiles": list(outcomes.PROFILES),
    }
    return result


def write(result: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=_json_default), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--source", choices=["synthetic", "csv"], default="synthetic")
    ap.add_argument("--path", help="case-table CSV (with --source csv)")
    ap.add_argument("--units", type=int, default=600)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--reference", default="not stated", help="what the reference quantity is")
    ap.add_argument("--out", default="outputs/study.json")
    args = ap.parse_args(argv)

    if args.source == "synthetic":
        frame = synthetic.generate(args.units, args.seed)
        reference = "invented (synthetic generator)"
    else:
        if not args.path:
            ap.error("--path is required with --source csv")
        import pandas as pd

        frame = pd.read_csv(args.path)
        reference = args.reference
    result = run_study(frame, args.source, reference, args.seed, args.boot)
    out = write(result, args.out)
    print(f"wrote {out}")
    if result["provenance"]["synthetic"]:
        print(SYNTHETIC_BANNER)
    for name, t in result["tests"].items():
        p = t["adjusted_p"]
        print(f"{name}: {t['verdict']}" + (f" (Holm p = {p:.4f})" if p is not None else ""))


if __name__ == "__main__":
    main()
