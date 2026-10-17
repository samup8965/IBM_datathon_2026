"""
model.py - the outage risk model. You do not need to edit it.

  1. models    a PyTorch neural network ensemble + gradient boosting, blended together
  2. risk      calibrated probability -> Low / Moderate / Severe / Critical
  3. OutageModel  one object that holds everything needed to score regions (save / load / score)

The data loading and features live in src/features.py.
"""
import os

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import TensorDataset, DataLoader
except ImportError as e:
    raise SystemExit("PyTorch is required. Install it with:  uv sync") from e

from src import config as C

device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))


def _find_nnpa():
    """The Telum AI accelerator (NNPA) through torch_nnpa, if this machine has one."""
    try:
        import torch_nnpa  # noqa: F401  registers the "nnpa" device on LinuxONE
        torch.empty(1, device="nnpa")
        return "nnpa"
    except Exception:
        return None


# Training runs on `device`. Scoring a saved model (predict.py, the API) uses the Telum
# NNPA when available. Set OUTAGE_INFER_DEVICE=cpu to compare against the CPU.
infer_device = os.environ.get("OUTAGE_INFER_DEVICE") or _find_nnpa() or device


# =====================================================================================
# 1. MODELS - both expose  .predict(X, region_ids) -> probability of an outage
# =====================================================================================
def safe_ap(y, p):
    return float(average_precision_score(y, p)) if y.sum() > 0 else float("nan")


def safe_auc(y, p):
    return float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan")


class GBMModel:
    """Gradient boosting (scikit-learn): fast and strong on tables."""

    def __init__(self, hgb):
        self.hgb = hgb

    def predict(self, X, r):
        return self.hgb.predict_proba(np.column_stack([X, r]))[:, 1]

    def save(self, out_dir):
        joblib.dump(self.hgb, os.path.join(out_dir, "gbm_model.joblib"))

    @staticmethod
    def load(out_dir):
        return GBMModel(joblib.load(os.path.join(out_dir, "gbm_model.joblib")))

    @staticmethod
    def fit(Xtr, rtr, ytr):
        hgb = HistGradientBoostingClassifier(
            max_iter=250, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=50,
            l2_regularization=1.0, class_weight="balanced", early_stopping=False, random_state=42,
            categorical_features=[Xtr.shape[1]],          # the last column is the region id
        )
        return GBMModel(hgb.fit(np.column_stack([Xtr, rtr]), ytr))


class OutageNet(nn.Module):
    """Small neural network: numeric features + a learned vector for each region."""

    def __init__(self, n_numeric, n_regions):
        super().__init__()
        # padding_idx=0 keeps the "region never seen" vector at zero instead of random noise
        self.emb = nn.Embedding(n_regions + 1, C.EMB_DIM, padding_idx=0)
        self.mlp = nn.Sequential(
            nn.Linear(n_numeric + C.EMB_DIM, 64), nn.BatchNorm1d(64), nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(64, 32), nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, x, region):
        return self.mlp(torch.cat([x, self.emb(region)], dim=1))


@torch.no_grad()
def _nn_predict(model, X, r):
    model.eval()
    dev = next(model.parameters()).device                # wherever the model lives (cpu / nnpa)
    out = []
    for i in range(0, len(X), 8192):                     # chunked so large inputs fit in memory
        xb = torch.tensor(X[i:i + 8192], dtype=torch.float32).to(dev)
        rb = torch.tensor(r[i:i + 8192], dtype=torch.long).to(dev)
        out.append(torch.sigmoid(model(xb, rb)).cpu().numpy().ravel())
    return np.concatenate(out)


def _train_one_net(seed, Xtr, rtr, ytr, Xva, rva, yva, n_regions, tmp_dir):
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = OutageNet(Xtr.shape[1], n_regions).to(device)
    if C.USE_POS_WEIGHT:
        pw = min(float((ytr == 0).sum() / max((ytr == 1).sum(), 1)), C.POS_WEIGHT_CAP)
        loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pw], dtype=torch.float32).to(device))
    else:
        loss_fn = nn.BCEWithLogitsLoss()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, mode="max", factor=0.5, patience=3)
    ds = TensorDataset(torch.tensor(Xtr, dtype=torch.float32), torch.tensor(rtr, dtype=torch.long),
                       torch.tensor(ytr, dtype=torch.float32).unsqueeze(1))
    # drop_last avoids a final batch of one row, which BatchNorm cannot handle
    loader = DataLoader(ds, batch_size=C.BATCH, shuffle=True, drop_last=len(ds) > C.BATCH)

    best, bad, epoch = -1.0, 0, 0
    path = os.path.join(tmp_dir, f"tmp_best_seed{seed}.pt")
    for epoch in range(C.MAX_EPOCHS):
        model.train()
        for xb, rb, yb in loader:
            xb, rb, yb = xb.to(device), rb.to(device), yb.to(device)
            opt.zero_grad()
            loss_fn(model(xb, rb), yb).backward()
            opt.step()
        score = safe_ap(yva, _nn_predict(model, Xva, rva))          # PR-AUC suits rare events
        score = -1.0 if np.isnan(score) else score
        sched.step(score)
        if score > best:
            best, bad = score, 0
            torch.save(model.state_dict(), path)
        else:
            bad += 1
            if bad >= C.PATIENCE:
                break
    model.load_state_dict(torch.load(path, map_location=device))
    os.remove(path)
    print(f"  network {seed}: best validation PR-AUC {best:.3f} ({epoch + 1} epochs)")
    return model


class NNEnsemble:
    """Average of several small neural networks trained from different random starts."""

    def __init__(self, models, seeds):
        self.models, self.seeds = models, seeds

    def predict(self, X, r):
        return np.mean([_nn_predict(m, X, r) for m in self.models], axis=0)

    @property
    def device(self):
        """Where the networks run: 'nnpa' = the Telum AI accelerator."""
        return next(self.models[0].parameters()).device.type

    def save(self, out_dir):
        for s, m in zip(self.seeds, self.models):
            torch.save(m.state_dict(), os.path.join(out_dir, f"nn_seed{s}.pt"))

    @staticmethod
    def load(out_dir, seeds, n_numeric, n_regions):
        models, dev = [], infer_device
        for s in seeds:
            m = OutageNet(n_numeric, n_regions)
            m.load_state_dict(torch.load(os.path.join(out_dir, f"nn_seed{s}.pt"), map_location="cpu"))
            m.eval()
            try:                                         # check the device really runs the network
                m = m.to(dev)
                _nn_predict(m, np.zeros((2, n_numeric), dtype="float32"), np.ones(2, dtype=int))
            except Exception as e:
                print(f"  could not score on {dev} ({type(e).__name__}); using cpu")
                dev, m = "cpu", m.to("cpu")
            models.append(m)
        print(f"  neural networks score on: {dev}")
        return NNEnsemble(models, seeds)

    @staticmethod
    def fit(Xtr, rtr, ytr, Xva, rva, yva, n_regions, tmp_dir):
        seeds = list(range(42, 42 + C.N_SEEDS))
        return NNEnsemble([_train_one_net(s, Xtr, rtr, ytr, Xva, rva, yva, n_regions, tmp_dir)
                           for s in seeds], seeds)


# =====================================================================================
# 2. RISK LEVELS
# =====================================================================================
def risk_cutoffs(pv):
    """Cut-offs on the calibrated probability, from the validation period (see TIER_SHARES)."""
    sh = C.TIER_SHARES
    cuts = [float(np.quantile(pv, 1 - sh[k])) for k in ("Moderate", "Severe", "Critical")]
    return tuple(np.maximum.accumulate(cuts))           # keep them in increasing order


def risk_tier(p, cuts):
    return np.select([p >= cuts[2], p >= cuts[1], p >= cuts[0]],
                     ["Critical", "Severe", "Moderate"], default="Low")


# =====================================================================================
# 3. OutageModel - everything needed to score regions, in one object
# =====================================================================================
class OutageModel:
    def __init__(self, nn_ens, gbm, w_nn, scaler, medians, calibrator, cutoffs,
                 feature_cols, region_map, region_events, horizon):
        self.nn, self.gbm, self.w_nn = nn_ens, gbm, w_nn
        self.scaler, self.medians, self.calibrator, self.cutoffs = scaler, medians, calibrator, cutoffs
        self.feature_cols, self.region_map = feature_cols, region_map
        self.region_events, self.horizon = region_events, horizon

    # --- predictions
    def raw(self, X, r):
        """Blend of the neural network and gradient boosting (before calibration)."""
        return self.w_nn * self.nn.predict(X, r) + (1 - self.w_nn) * self.gbm.predict(X, r)

    def prob(self, X, r):
        """Calibrated probability that an outage starts within the horizon."""
        return self.calibrator.predict(self.raw(X, r))

    def prepare(self, d):
        missing = [c for c in self.feature_cols if c not in d.columns]
        if missing:
            raise SystemExit(f"Features missing from the data: {missing[:6]}...\n"
                             "src/config.py must match what the model was trained with.")
        X = self.scaler.transform(d[self.feature_cols].fillna(self.medians)).astype("float32")
        return X, d["region_id"].values

    def top_factors(self, X, r, k=3, min_effect=0.01):
        """For each row: the features pushing its risk UP the most (approximate).
        Each feature is set to its typical (average) value, and we see how much the risk falls."""
        n, m = X.shape
        base = self.raw(X, r)
        Xp = np.repeat(X, m, axis=0)
        Xp[np.arange(n * m), np.tile(np.arange(m), n)] = 0.0      # scaled 0 = the training average
        effect = base[:, None] - self.raw(Xp, np.repeat(r, m)).reshape(n, m)
        out = []
        for i in range(n):
            order = np.argsort(-effect[i])[:k]
            out.append("; ".join(self.feature_cols[j] for j in order if effect[i, j] > min_effect))
        return out

    def score_latest(self, df):
        """Current risk for each region (its most recent row)."""
        latest = df.sort_values("timestamp").groupby("region").tail(1).copy()
        X, r = self.prepare(latest)
        p = self.prob(X, r)
        latest["risk_probability"] = np.round(p, 4)
        latest["risk_level"] = risk_tier(p, self.cutoffs)
        latest.loc[latest["outage_now"] == 1, "risk_level"] = "Outage in progress"
        ev = latest["region"].map(self.region_events).fillna(0).astype(int)
        latest["history_events"] = ev
        latest["confidence"] = np.select([ev >= C.CONF_HIGH, ev >= C.CONF_MED], ["High", "Medium"], "Low")
        latest["top_factors"] = self.top_factors(X, r)
        cols = ["region", "timestamp", "risk_probability", "risk_level",
                "confidence", "history_events", "top_factors"]
        return latest[cols].sort_values("risk_probability", ascending=False).reset_index(drop=True)

    # --- saving / loading
    def save(self, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        self.nn.save(out_dir)
        self.gbm.save(out_dir)
        joblib.dump({
            "seeds": self.nn.seeds, "w_nn": self.w_nn, "scaler": self.scaler, "medians": self.medians,
            "calibrator": self.calibrator, "cutoffs": self.cutoffs, "feature_cols": self.feature_cols,
            "region_map": self.region_map, "region_events": self.region_events, "horizon": self.horizon,
        }, os.path.join(out_dir, "meta.joblib"))

    @staticmethod
    def load(out_dir):
        p = os.path.join(out_dir, "meta.joblib")
        if not os.path.exists(p):
            raise SystemExit(f"No trained model found in {out_dir}. Run scripts/train.py first.")
        a = joblib.load(p)
        nn_ens = NNEnsemble.load(out_dir, a["seeds"], len(a["feature_cols"]), len(a["region_map"]))
        return OutageModel(nn_ens, GBMModel.load(out_dir), a["w_nn"], a["scaler"], a["medians"],
                           a["calibrator"], a["cutoffs"], a["feature_cols"], a["region_map"],
                           a["region_events"], a["horizon"])


def save_risk(out, out_dir):
    """Write the app-facing results as CSV and JSON."""
    os.makedirs(out_dir, exist_ok=True)
    out.to_csv(os.path.join(out_dir, "risk_latest.csv"), index=False)
    out.assign(timestamp=out["timestamp"].astype(str)).to_json(
        os.path.join(out_dir, "risk_latest.json"), orient="records", indent=2)
    print(out.drop(columns=["top_factors"]).to_string(index=False))
    print(f"\nSaved risk_latest.csv and risk_latest.json in {out_dir}/")
