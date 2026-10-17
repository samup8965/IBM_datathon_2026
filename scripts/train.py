"""
train.py - teach the model from your data. Run this once (and again when you have much more data).

    uv run python scripts/train.py --data-dir data/model_input --out-dir models

    # train on synthetic data, test on real data the model never saw
    uv run python scripts/train.py --data-dir data/model_input/synthetic \
        --test-dir data/model_input/real --out-dir models

What it does:
  1. loads and combines all your datasets (see src/config.py)
  2. splits the data BY TIME: oldest 70% train, next 15% validation, newest 15% test
  3. trains a PyTorch neural-network ensemble and a gradient-boosting model
  4. blends them (the blend weights are chosen on validation data)
  5. calibrates the blend so its output is a real "% chance", and sets the risk-level cut-offs
  6. reports honest results on the test set (data the model never touched)
  7. saves the model + current risk per region into --out-dir
"""
import argparse
import os
import platform
import sys

import joblib
import numpy as np
import pandas as pd
import sklearn
import torch
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    f1_score, log_loss, brier_score_loss, precision_score, recall_score,
)
from sklearn.preprocessing import StandardScaler

from src import config as C
from src.features import build_dataset, count_events
from src.model import (
    GBMModel, NNEnsemble, OutageModel, risk_cutoffs, risk_tier, safe_auc, safe_ap, save_risk, device,
)


class Tee:
    """Copy everything printed to a text file as well, so the training report is kept."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for x in self.streams:
            x.write(s)

    def flush(self):
        for x in self.streams:
            x.flush()


def report(name, y, p, thr):
    pred = (p >= thr).astype(int)
    print(f"{name:<32} PR-AUC {safe_ap(y, p):.3f} | ROC-AUC {safe_auc(y, p):.3f} | "
          f"prec {precision_score(y, pred, zero_division=0):.3f} | "
          f"rec {recall_score(y, pred, zero_division=0):.3f} | "
          f"F1 {f1_score(y, pred, zero_division=0):.3f}")


def permutation_importance(predict_fn, X, r, y, names, n=5000, repeats=3, seed=0):
    """How much does PR-AUC drop when one feature is scrambled? Bigger drop = more important."""
    rng = np.random.default_rng(seed)
    if len(X) > n:
        idx = rng.choice(len(X), n, replace=False)
        X, r, y = X[idx], r[idx], y[idx]
    base = safe_ap(y, predict_fn(X, r))
    rows = []
    for j, name in enumerate(list(names) + ["region"]):
        drops = []
        for _ in range(repeats):
            Xp, rp = X.copy(), r.copy()
            if name == "region":
                rp = rng.permutation(rp)
            else:
                Xp[:, j] = rng.permutation(Xp[:, j])
            drops.append(base - safe_ap(y, predict_fn(Xp, rp)))
        rows.append((name, float(np.mean(drops))))
    return pd.DataFrame(rows, columns=["feature", "pr_auc_drop"]).sort_values("pr_auc_drop", ascending=False)


def add_yesterday(df, horizon):
    """Baseline input: the label at this hour yesterday, which is already known by now."""
    df["label_yesterday"] = df.groupby("region")["label"].shift(max(24, horizon))
    return df


def usable(df):
    """Rows the model may learn from: the future is known, and (optionally) power is currently on."""
    lab = df[df["label"].notna()]
    if C.CONFIG["exclude_ongoing"]:
        lab = lab[lab["outage_now"] == 0]
    return lab


def main(data_dir, out_dir, test_dir=None):
    print(f"Python {platform.python_version()} | torch {torch.__version__} on {device} | "
          f"scikit-learn {sklearn.__version__}")
    H = C.CONFIG["horizon"]
    df, feature_cols, region_map = build_dataset(data_dir)
    lab = usable(add_yesterday(df, H))

    if test_dir:
        # Train and validate on --data-dir (split by time); test on ALL of --test-dir,
        # e.g. train on synthetic data and test on real data the model never saw
        t1 = lab["timestamp"].quantile(C.TRAIN_FRAC / (C.TRAIN_FRAC + C.VAL_FRAC))
        tr = lab[lab.timestamp <= t1]
        va = lab[lab.timestamp > t1]
        print(f"\nTest data: {test_dir}")
        test_df, _, _ = build_dataset(test_dir, region_map=region_map)
        te = usable(add_yesterday(test_df, H))
    else:
        t1 = lab["timestamp"].quantile(C.TRAIN_FRAC)
        t2 = lab["timestamp"].quantile(C.TRAIN_FRAC + C.VAL_FRAC)
        tr = lab[lab.timestamp <= t1]
        va = lab[(lab.timestamp > t1) & (lab.timestamp <= t2)]
        te = lab[lab.timestamp > t2]
        test_df = df
    print(f"\n{len(tr)} train / {len(va)} validation / {len(te)} test rows | "
          f"{len(region_map)} regions | {len(feature_cols)} features")
    for name, d in [("train", tr), ("validation", va), ("test", te)]:
        npos = int(d["label"].sum()) if len(d) else 0
        rate = d["label"].mean() if len(d) else float("nan")
        print(f"  {name:<10} outage-in-next-{H}-rows rate {rate:.3f} ({npos} positive rows)")
        if npos == 0:
            raise SystemExit(f"The {name} split has no outages. You need more data (or a longer history).")
        if npos < C.MIN_POSITIVES:
            print(f"  WARNING: only {npos} positive rows in {name}; results will be very noisy.")

    # fill gaps and scale using TRAIN statistics only
    med = tr[feature_cols].median().fillna(0)
    scaler = StandardScaler().fit(tr[feature_cols].fillna(med))

    def prep(d):
        return (scaler.transform(d[feature_cols].fillna(med)).astype("float32"),
                d["region_id"].values, d["label"].values.astype("float32"))
    Xtr, rtr, ytr = prep(tr)
    Xva, rva, yva = prep(va)
    Xte, rte, yte = prep(te)

    # ---- fit both model families
    os.makedirs(out_dir, exist_ok=True)
    print("\nTraining gradient boosting")
    gbm = GBMModel.fit(Xtr, rtr, ytr)
    print("\nTraining PyTorch neural-network ensemble")
    nn_ens = NNEnsemble.fit(Xtr, rtr, ytr, Xva, rva, yva, len(region_map), out_dir)

    # ---- choose the blend on validation data
    nn_va, gbm_va = nn_ens.predict(Xva, rva), gbm.predict(Xva, rva)
    scores = {w: safe_ap(yva, w * nn_va + (1 - w) * gbm_va) for w in C.BLEND_WEIGHTS}
    w_nn = max(scores, key=scores.get)
    print("\nBlend (share given to the neural network) -> validation PR-AUC")
    for w, s in scores.items():
        print(f"  {w:.2f} -> {s:.3f}{'   <- chosen' if w == w_nn else ''}")

    events = count_events(df)
    model = OutageModel(nn_ens, gbm, w_nn, scaler, med, None, None, feature_cols, region_map, events, H)

    # ---- calibrate (so the output means "% chance") and derive the risk cut-offs from validation
    model.calibrator = IsotonicRegression(out_of_bounds="clip").fit(model.raw(Xva, rva), yva)
    pv, pt = model.prob(Xva, rva), model.prob(Xte, rte)
    model.cutoffs = risk_cutoffs(pv)
    cuts = model.cutoffs

    # ---- honest evaluation on the untouched test set
    print("\nModel comparison (test set)")
    print(f"{'base rate (the floor)':<32} PR-AUC {yte.mean():.3f}")
    region_rate = tr.groupby("region")["label"].mean()
    baselines = [
        ("recent outages (roll24)", te["outage_roll24"].values),
        ("regional average", te["region"].map(region_rate).fillna(tr["label"].mean()).values),
        ("same as yesterday", te["label_yesterday"].fillna(0).values),
    ]
    for name, p in baselines:
        print(f"{name:<32} PR-AUC {safe_ap(yte, p):.3f} | ROC-AUC {safe_auc(yte, p):.3f}")
    for name, p in [("gradient boosting alone", gbm.predict(Xte, rte)),
                    ("PyTorch ensemble alone", nn_ens.predict(Xte, rte)),
                    (f"blend (NN share {w_nn:.2f}), raw", model.raw(Xte, rte))]:
        print(f"{name:<32} PR-AUC {safe_ap(yte, p):.3f} | ROC-AUC {safe_auc(yte, p):.3f}")

    print(f"\nRisk levels (calibrated probability of an outage within {H} rows): "
          f"Moderate >= {cuts[0]:.3f} | Severe >= {cuts[1]:.3f} | Critical >= {cuts[2]:.3f}")
    print("\nFinal model, calibrated (test set)")
    report("final model (flagging Severe+)", yte, pt, cuts[1])
    print(f"log loss {log_loss(yte, np.clip(pt, 1e-6, 1 - 1e-6)):.4f} | Brier {brier_score_loss(yte, pt):.4f}")

    print("\nDo the risk levels mean something? (test set; the outage rate should rise with the level)")
    tiers = risk_tier(pt, cuts)
    for name in ["Low", "Moderate", "Severe", "Critical"]:
        m = tiers == name
        if m.sum():
            print(f"  {name:<9} rows {m.sum():>7} | actual outage rate {yte[m].mean():.3f} | "
                  f"share of all outages {yte[m].sum() / max(yte.sum(), 1):.2f}")

    print("\nPer region (test set)")
    inv = {v: k for k, v in region_map.items()}
    for rid in sorted(np.unique(rte)):
        m = rte == rid
        report(f"{inv.get(rid, rid)} (n={m.sum()}, +={int(yte[m].sum())})", yte[m], pt[m], cuts[1])

    print("\nWhat drives the predictions? (test set; PR-AUC lost when the feature is scrambled)")
    imp = permutation_importance(model.raw, Xte, rte, yte, feature_cols)
    imp.to_csv(os.path.join(out_dir, "feature_importance.csv"), index=False)
    print(imp.head(10).to_string(index=False))

    # ---- current risk per region, then save everything
    print("\nCurrent risk by region")
    save_risk(model.score_latest(test_df), out_dir)
    model.save(out_dir)
    with open(os.path.join(out_dir, "versions.txt"), "w") as f:
        f.write(f"python {platform.python_version()}\ntorch {torch.__version__}\n"
                f"numpy {np.__version__}\npandas {pd.__version__}\nscikit-learn {sklearn.__version__}\n"
                f"joblib {joblib.__version__}\n")
    print(f"\nModel saved in {out_dir}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Train the outage risk model.")
    ap.add_argument("--data-dir", default="data/model_input", help="folder containing your CSV files")
    ap.add_argument("--out-dir", default="models", help="folder for the trained model and results")
    ap.add_argument("--test-dir", default=None,
                    help="optional: test on this folder instead of the newest part of --data-dir")
    args = ap.parse_args()
    data_dir, out_dir = os.path.expanduser(args.data_dir), os.path.expanduser(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    log = open(os.path.join(out_dir, "training_report.txt"), "w")
    sys.stdout = Tee(sys.__stdout__, log)           # print to the screen AND keep a copy
    try:
        main(data_dir, out_dir, os.path.expanduser(args.test_dir) if args.test_dir else None)
    finally:
        sys.stdout = sys.__stdout__
        log.close()
