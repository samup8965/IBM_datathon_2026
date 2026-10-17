"""
predict.py - get the CURRENT risk for every region, using the model trained by scripts/train.py.

    uv run python scripts/predict.py --data-dir data/model_input --out-dir models

Run this whenever your CSV files have been updated. It needs no retraining.
The LAST timestamp in your history file is treated as "now", so keep that file up to date.

Output (in --out-dir): risk_latest.csv and risk_latest.json
"""
import argparse
import os

import pandas as pd

from src.features import build_dataset
from src.model import OutageModel, save_risk


def main(data_dir, out_dir):
    model = OutageModel.load(out_dir)
    df, _, _ = build_dataset(data_dir, region_map=model.region_map)   # same region ids as training
    out = model.score_latest(df)

    newest = out["timestamp"].max()
    age = pd.Timestamp.now("UTC").tz_localize(None) - newest
    print(f"\nData is current up to {newest} ({str(age).split('.')[0]} ago); "
          f"risk = chance of an outage starting in the next {model.horizon} rows.")
    if age > pd.Timedelta("2D"):
        print("WARNING: the history file looks stale - these risk levels describe the past, not now.")
    new_regions = sorted(set(df["region"]) - set(model.region_map))
    if new_regions:
        print(f"NOTE: regions the model never saw in training (low reliability): {new_regions}")
    print()
    save_risk(out, out_dir)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Score every region with the trained model.")
    ap.add_argument("--data-dir", default="data/model_input", help="folder containing your CSV files")
    ap.add_argument("--out-dir", default="models", help="folder holding the trained model")
    args = ap.parse_args()
    main(os.path.expanduser(args.data_dir), os.path.expanduser(args.out_dir))
