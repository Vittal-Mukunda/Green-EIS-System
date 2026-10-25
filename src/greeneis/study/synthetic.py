"""Generated test data, so the pipeline can be exercised before real data exist.

**Everything here is invented.** Intensities, prices and noise levels are arbitrary and chosen only to
give the code realistic-looking variety. Because the generator decides how large the proxy errors are,
H1-H3 run on this data would just recover the generator's settings. Results from it prove nothing about
the world; every output built from it is marked synthetic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# arbitrary: sector -> {item: (kg or kWh per unit of scale, probability a unit uses it)}
SECTORS = {
    "textiles": {
        "coal": (900.0, 0.7),
        "diesel": (60.0, 0.6),
        "lpg": (25.0, 0.3),
        "grid_electricity": (4000.0, 1.0),
    },
    "minerals": {
        "coal": (2500.0, 0.8),
        "furnace_oil": (150.0, 0.3),
        "diesel": (80.0, 0.5),
        "grid_electricity": (2500.0, 1.0),
    },
    "metals": {
        "coal": (1200.0, 0.5),
        "furnace_oil": (300.0, 0.5),
        "natural_gas": (80.0, 0.3),
        "grid_electricity": (6000.0, 1.0),
    },
    "food": {
        "coal": (500.0, 0.5),
        "diesel": (70.0, 0.6),
        "lpg": (60.0, 0.5),
        "grid_electricity": (3000.0, 1.0),
    },
}
BASE_PRICE = {  # arbitrary INR per kg (per kWh for electricity)
    "coal": 9.0,
    "lignite": 6.0,
    "diesel": 85.0,
    "furnace_oil": 55.0,
    "lpg": 75.0,
    "natural_gas": 50.0,
    "grid_electricity": 7.5,
}
STATES = ("S1", "S2", "S3", "S4", "S5")
YEARS = ("Y1", "Y2")


def generate(
    n_units: int = 600,
    seed: int = 0,
    sigma_intensity: float = 0.5,  # spread of a unit's intensity around its sector's
    sigma_price: float = 0.25,  # spread of unit prices around the state-year price
    sigma_state: float = 0.15,  # spread of the state-year price around the base price
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    state_price = {
        (st, yr, item): BASE_PRICE[item] * float(np.exp(rng.normal(0, sigma_state)))
        for st in STATES
        for yr in YEARS
        for item in BASE_PRICE
    }
    sectors = list(SECTORS)
    rows = []
    for i in range(n_units):
        sector = sectors[int(rng.integers(len(sectors)))]
        state = STATES[int(rng.integers(len(STATES)))]
        year = YEARS[int(rng.integers(len(YEARS)))]
        scale = float(np.exp(rng.normal(2.0, 0.8)))  # output value, arbitrary units
        used = [
            (item, base) for item, (base, prob) in SECTORS[sector].items() if rng.random() < prob
        ]
        if len(used) < 1:
            continue
        for item, base in used:
            q = base * scale * float(np.exp(rng.normal(0, sigma_intensity)))
            price = state_price[(state, year, item)] * float(np.exp(rng.normal(0, sigma_price)))
            rows.append(
                {
                    "unit_id": f"SYN-{i:05d}",
                    "item_id": item,
                    "quantity": q,
                    "value_inr": q * price,
                    "scale": scale,
                    "sector": sector,
                    "price_group": f"{state}-{year}",
                    "cluster": f"{state}-{year}",
                    "synthetic": True,
                }
            )
    return pd.DataFrame(rows)
