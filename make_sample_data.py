"""
make_sample_data.py - creates FAKE data in the same format as your real files, so you can
check that the whole pipeline works before using real data.

    python make_sample_data.py --out sample_data
    python train.py --data-dir sample_data --out-dir sample_model
    python predict.py --data-dir sample_data --out-dir sample_model

(The numbers are invented: outages are made more likely by heat, a low reservoir and
dips in internet connectivity just beforehand. Do not read anything real into the results.)
"""
import argparse
import os

import numpy as np
import pandas as pd


def main(out, days=180, seed=1):
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2025-01-01", periods=24 * days, freq="h")
    base = {"Zulia": 0.0060, "Caracas": 0.0020, "Bolivar": 0.0040, "Lara": 0.0030, "Merida": 0.0025}

    day = pd.date_range(ts[0], periods=days + 10, freq="D")
    res = 240 - 0.04 * np.arange(len(day)) + rng.normal(0, 0.3, len(day)).cumsum() * 0.1
    pd.DataFrame({"timestamp": day, "height": res}).to_csv(os.path.join(out, "reservoir.csv"), index=False)
    res_h = pd.Series(res, index=day).reindex(ts, method="ffill").values

    hist, temp, heat, net = [], [], [], []
    for region, b in base.items():
        t = 28 + 6 * np.sin(2 * np.pi * (ts.hour - 8) / 24) + rng.normal(0, 1, len(ts))
        h = t + 3 + rng.normal(0, 1, len(ts))
        conn = 95.0 + rng.normal(0, 2, len(ts))
        p = b * (1 + 3 * (h > 35.5)) * (1 + 2 * (res_h < 238))
        start = rng.random(len(ts)) < p
        out_flag = start.astype(int)
        for i in np.where(start)[0]:
            out_flag[i:i + 3] = 1                      # an outage lasts about 3 hours
            conn[max(0, i - 4):i + 3] -= 40            # connectivity dips just before and during
        hist.append(pd.DataFrame({"timestamp": ts, "region": region, "outage": out_flag}))
        temp.append(pd.DataFrame({"timestamp": ts, "region": region.upper(), "temperature": t}))
        heat.append(pd.DataFrame({"timestamp": ts, "region": region, "heat_index": h}))
        s = ts[::3]                                    # connectivity is measured every 3 hours
        net.append(pd.DataFrame({"timestamp": s, "region": " " + region, "connectivity": conn[::3]}))

    pd.concat(hist).to_csv(os.path.join(out, "history.csv"), index=False)
    pd.concat(temp).to_csv(os.path.join(out, "temperature.csv"), index=False)
    pd.concat(heat).to_csv(os.path.join(out, "heat_index.csv"), index=False)
    pd.concat(net).to_csv(os.path.join(out, "connectivity.csv"), index=False)
    print(f"Wrote fake data for {len(base)} regions to {out}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="sample_data")
    ap.add_argument("--days", type=int, default=180)
    a = ap.parse_args()
    main(a.out, a.days)
