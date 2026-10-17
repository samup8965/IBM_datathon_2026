"""Write the model's input CSVs (the format src/features.py reads, see src/config.py).

  data/model_input/synthetic/  training data, from data/synthetic/grid_hourly.csv.gz
  data/model_input/real/       real test data from IODA + weather, from --real-from on
                               (default 2025-01-01: months the calibration never saw)
  data/model_input/real_train/ real data from before --real-from, to train a real-only
                               model as a reference

Both folders hold the same files with the same meaning:
  history.csv       timestamp, region, outage        (1 = connectivity below 90% of its
                                                      best level over the past 2 weeks)
  connectivity.csv  timestamp, region, connectivity  (% of that best level)
  heat_index.csv    timestamp, region, heat_index    (degrees C)

Times are Venezuela time. States flagged low_signal in data/calibration.json are left
out, because their real outage labels are mostly measurement noise.

Usage (from the repo root):
    uv run python scripts/export_model_input.py
    uv run python scripts/export_model_input.py --real-from 2025-01-01
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from calibrate import DROP_THRESHOLD, WEATHER_PATH, load_connectivity_ratio

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_PATH = ROOT / "data" / "synthetic" / "grid_hourly.csv.gz"
CALIBRATION_PATH = ROOT / "data" / "calibration.json"
OUT_DIR = ROOT / "data" / "model_input"


def write(frames, folder):
    folder.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        df.to_csv(folder / f"{name}.csv", index=False)
    history = frames["history"]
    print(f"  {folder.relative_to(ROOT)}: {len(history):,} rows, "
          f"{history.region.nunique()} states, {history.timestamp.min()} -> "
          f"{history.timestamp.max()}, outage share {history.outage.mean():.2%}")


def export_synthetic(skip):
    g = pd.read_csv(SYNTHETIC_PATH, usecols=["timestamp_vet", "state", "outage",
                                             "connectivity_pct", "heat_index_c"])
    g = g[~g.state.isin(skip)].rename(columns={"timestamp_vet": "timestamp", "state": "region"})
    keys = g[["timestamp", "region"]]
    return {
        "history": keys.assign(outage=g.outage.astype(int)),
        "connectivity": keys.assign(connectivity=g.connectivity_pct),
        "heat_index": keys.assign(heat_index=g.heat_index_c),
    }


def export_real(skip, start, end=pd.Timestamp.max):
    # Same outage definition as calibration (see scripts/calibrate.py)
    ratio, _ = load_connectivity_ratio(pd.Timestamp.max)
    ratio = ratio[(ratio.index >= start) & (ratio.index < end)].drop(columns=list(skip),
                                                                      errors="ignore")
    long = (ratio.rename_axis("timestamp").reset_index()
            .melt(id_vars="timestamp", var_name="region", value_name="ratio"))
    missing = long.ratio.isna().mean()
    print(f"  real connectivity missing for {missing:.1%} of state-hours "
          "(counted as no outage, connectivity left blank)")

    weather = pd.read_csv(WEATHER_PATH, usecols=["state", "timestamp_vet", "heat_index_c"],
                          parse_dates=["timestamp_vet"])
    weather = weather[(weather.timestamp_vet >= start) & (weather.timestamp_vet < end)
                      & ~weather.state.isin(skip)].dropna()
    return {
        "history": long[["timestamp", "region"]].assign(
            outage=(long.ratio < DROP_THRESHOLD).astype(int)),
        "connectivity": long.dropna(subset=["ratio"])[["timestamp", "region"]].assign(
            connectivity=(long.ratio.dropna() * 100).clip(upper=200).round(1)),
        "heat_index": weather.rename(columns={"timestamp_vet": "timestamp", "state": "region",
                                              "heat_index_c": "heat_index"}),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-from", default="2025-01-01",
                        help="first day (Venezuela time) of the real test data")
    args = parser.parse_args()

    states = json.loads(CALIBRATION_PATH.read_text())["states"]
    skip = {s for s, v in states.items() if v["low_signal"]}
    print(f"Leaving out low-signal states: {sorted(skip)}")

    real_from = pd.Timestamp(args.real_from)
    write(export_synthetic(skip), OUT_DIR / "synthetic")
    write(export_real(skip, real_from), OUT_DIR / "real")
    # Real data from before --real-from: for a real-only model to compare against
    write(export_real(skip, pd.Timestamp.min, end=real_from), OUT_DIR / "real_train")


if __name__ == "__main__":
    main()
