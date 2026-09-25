"""Generate sample_data/orders.csv: 500 synthetic orders plus deliberately
injected defects, so the agent's findings can be checked against ground truth.

    python sample_data/make_orders.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).with_name("orders.csv")


def build(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 500
    df = pd.DataFrame({
        "order_id": np.arange(1001, 1001 + n),
        "customer_id": rng.integers(1, 120, n),
        "order_date": pd.to_datetime("2026-01-01") + pd.to_timedelta(rng.integers(0, 240, n), unit="D"),
        "region": rng.choice(["East", "West", "North", "South"], n),
        "amount": np.round(rng.gamma(3, 60, n), 2),
        "status": rng.choice(["shipped", "pending", "cancelled"], n, p=[.7, .2, .1]),
        "email": [f"user{i}@example.com" for i in rng.integers(1, 120, n)],
    })
    # Injected defects (ground truth for the tests)
    df.loc[rng.choice(n, 25, replace=False), "amount"] = np.nan                       # nulls
    df.loc[rng.choice(n, 6, replace=False), "amount"] = -1 * rng.integers(10, 400, 6)  # negatives
    df.loc[rng.choice(n, 4, replace=False), "amount"] = rng.integers(20000, 90000, 4)  # outliers
    df.loc[rng.choice(n, 12, replace=False), "region"] = rng.choice(["east ", " West", "NORTH", "n/a"], 12)
    df.loc[rng.choice(n, 8, replace=False), "email"] = rng.choice(["bad.email", "", "noatsign.com"], 8)
    df.loc[rng.choice(n, 5, replace=False), "order_date"] = pd.Timestamp("2031-02-15")  # future
    dup = df.sample(7, random_state=1)                                                # duplicate keys
    return pd.concat([df, dup], ignore_index=True)


if __name__ == "__main__":
    build().to_csv(OUT, index=False)
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")
