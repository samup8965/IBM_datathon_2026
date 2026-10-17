"""
outage_core.py - shared code used by train.py, predict.py and serve.py. You do not need to edit it.

  1. data      load every dataset, align them in time, build features
  2. models    a PyTorch neural network ensemble + gradient boosting, blended together
  3. risk      calibrated probability -> Low / Moderate / Severe / Critical
  4. OutageModel  one object that holds everything needed to score regions (save / load / score)
"""
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import TensorDataset, DataLoader
except ImportError as e:
    raise SystemExit("PyTorch is required. Install it with:  pip install torch") from e

import outage_config as C

device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))


# =====================================================================================
# 1. DATA
# =====================================================================================
def _path(data_dir, p):
    p = os.path.expanduser(p)
    return p if os.path.isabs(p) else os.path.join(data_dir, p)


def _std_time(s):
    """Parse to naive UTC datetime64[ns] so every file uses the same clock."""
    return pd.to_datetime(s, utc=True).dt.tz_localize(None).astype("datetime64[ns]")


def _read(data_dir, path, time, region=None, cols=()):
    full = _path(data_dir, path)
    if not os.path.exists(full):
        raise SystemExit(f"File not found: {full}\n(use --data-dir, or fix 'path' in outage_config.py)")
    d = pd.read_csv(full)
    need = [c for c in [time, region, *cols] if c]
    missing = [c for c in need if c not in d.columns]
    if missing:
        raise SystemExit(f"{path}: missing column(s) {missing}. Columns found: {list(d.columns)}\n"
                         f"(fix the names in outage_config.py)")
    d = d.rename(columns={time: "timestamp"})
    d["timestamp"] = _std_time(d["timestamp"])
    if region:
        d = d.rename(columns={region: "region"})
        d["region"] = d["region"].astype(str).str.strip().str.lower()
    return d


def events_to_grid(data_dir, path, start_col, end_col, region_col, freq="h"):
    """Turn an outage event log (start, end, region) into a (timestamp, region, outage) grid."""
    ev = pd.read_csv(_path(data_dir, path))
    missing = [c for c in (start_col, end_col, region_col) if c not in ev.columns]
    if missing:
        raise SystemExit(f"{path}: missing column(s) {missing}. Columns found: {list(ev.columns)}")
    ev = ev.rename(columns={region_col: "region"})
    ev["region"] = ev["region"].astype(str).str.strip().str.lower()
    ev[start_col], ev[end_col] = _std_time(ev[start_col]), _std_time(ev[end_col])
    ts = pd.date_range(ev[start_col].min().floor(freq), ev[end_col].max().ceil(freq), freq=freq)
    parts = []
    for r, e in ev.groupby("region"):
        arr = np.zeros(len(ts), dtype="int8")
        for s, t in zip(e[start_col], e[end_col]):
            arr[ts.searchsorted(s):ts.searchsorted(t)] = 1
        parts.append(pd.DataFrame({"timestamp": ts, "region": r, "outage": arr}))
    return pd.concat(parts, ignore_index=True)


def _load_history(data_dir, cfg):
    h = cfg["history"]
    if h["format"] == "events":
        grid = events_to_grid(data_dir, h["path"], h["start"], h["end"], h["region"], h.get("freq", "h"))
    else:
        grid = _read(data_dir, h["path"], h["time"], h["region"], cols=[h["target"]])
        grid = grid.rename(columns={h["target"]: "outage"})[["timestamp", "region", "outage"]]
    grid["outage"] = (pd.to_numeric(grid["outage"], errors="coerce").fillna(0) > 0).astype("int8")

    f = cfg.get("regularize_freq")
    if f:                                            # rebuild a complete, evenly spaced time grid
        grid["timestamp"] = grid["timestamp"].dt.floor(f)
        grid = grid.groupby(["region", "timestamp"], as_index=False)["outage"].max()
        parts = []
        for r, d in grid.groupby("region"):
            idx = pd.date_range(d["timestamp"].min(), d["timestamp"].max(), freq=f)
            s = d.set_index("timestamp")["outage"].reindex(idx, fill_value=0)
            parts.append(pd.DataFrame({"timestamp": idx, "region": r, "outage": s.values.astype("int8")}))
        grid = pd.concat(parts, ignore_index=True)
    return grid.groupby(["region", "timestamp"], as_index=False)["outage"].max()


def _describe_grid(df, horizon):
    """Windows and the horizon are counted in ROWS, so rows should be evenly spaced in time."""
    step = df.sort_values(["region", "timestamp"]).groupby("region")["timestamp"].diff().dropna()
    if step.empty:
        raise SystemExit("History has too few rows per region.")
    typical = step.mode().iloc[0]
    irregular = float((step != typical).mean())
    print(f"  [history] time step {typical}; horizon = {horizon} rows = {horizon * typical}; "
          f"{100 * irregular:.1f}% of steps irregular")
    if irregular > 0.02:
        print("  WARNING: rows are not evenly spaced, so 'rows' do not mean equal time. "
              "Set 'regularize_freq' (e.g. 'h') in outage_config.py to fix this.")


def _attach(data_dir, base, src, default_tol):
    """As-of join: each row gets the latest reading at or before its timestamp (no future leakage)."""
    name, regional = src["name"], src["region"] is not None
    s = _read(data_dir, src["path"], src["time"], src["region"], cols=src["cols"])
    keep = ["timestamp"] + (["region"] if regional else []) + src["cols"]
    s = s[keep].dropna(subset=["timestamp"]).sort_values("timestamp")
    s = s.rename(columns={c: f"{name}_{c}" for c in src["cols"]})
    if regional:
        unknown = set(s["region"]) - set(base["region"])
        if unknown:
            print(f"  [{name}] regions not in history (ignored): {sorted(unknown)[:8]}")
    out = pd.merge_asof(
        base.sort_values("timestamp"), s, on="timestamp",
        by="region" if regional else None, direction="backward",
        tolerance=pd.Timedelta(src.get("tolerance", default_tol)),
    )
    first = f"{name}_{src['cols'][0]}"
    out[f"{name}_missing"] = out[first].isna().astype("int8")
    matched = 100 * (1 - out[f"{name}_missing"].mean())
    print(f"  [{name}] matched {matched:.1f}% of rows")
    if matched < 50:
        print(f"  WARNING: [{name}] matched very few rows - check region spellings and time ranges.")
    return out


def _transforms(df, src):
    name = src["name"]
    for col in src["cols"]:
        c = f"{name}_{col}"
        g = df.groupby("region")[c]
        for stat, w in src.get("roll", []):
            df[f"{c}_{stat}{w}"] = g.transform(lambda s: getattr(s.rolling(w, min_periods=1), stat)())
        for k in src.get("diff", []):
            df[f"{c}_d{k}"] = g.diff(k)
        W = src.get("rel_to_median")
        if W:
            med = g.transform(lambda s: s.shift(1).rolling(W, min_periods=max(3, W // 8)).median())
            df[f"{c}_rel{W}"] = (df[c] / med.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    return df


def build_dataset(data_dir, region_map=None, cfg=None):
    """Returns (df, feature_cols, region_map).
    df has one row per (region, timestamp). 'label' = an outage starts within the horizon
    (NaN when the future is not known yet)."""
    cfg = cfg or C.CONFIG
    print("Loading datasets")
    df = _load_history(data_dir, cfg)
    print(f"  [history] {len(df)} rows, {df['region'].nunique()} regions, "
          f"{df['timestamp'].min()} -> {df['timestamp'].max()}")
    _describe_grid(df, cfg["horizon"])
    for src in cfg["sources"]:
        df = _attach(data_dir, df, src, cfg["default_tolerance"])
    df = df.sort_values(["region", "timestamp"]).reset_index(drop=True)
    for src in cfg["sources"]:
        df = _transforms(df, src)

    # calendar (cyclical, so 23:00 sits next to 00:00)
    t = df["timestamp"]
    df["hour_sin"] = np.sin(2 * np.pi * t.dt.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * t.dt.hour / 24)
    df["month_sin"] = np.sin(2 * np.pi * (t.dt.month - 1) / 12)
    df["month_cos"] = np.cos(2 * np.pi * (t.dt.month - 1) / 12)
    df["is_weekend"] = (t.dt.dayofweek >= 5).astype("int8")

    # outage history up to and including time t (nothing from after t)
    g = df.groupby("region")["outage"]
    df["outage_now"] = df["outage"]
    for k in cfg["lags"]:
        df[f"outage_lag{k}"] = g.shift(k).fillna(0)
    for w in cfg["windows"]:
        df[f"outage_roll{w}"] = g.transform(lambda s: s.rolling(w, min_periods=1).sum())

    def since_last(s):
        pos = pd.Series(np.arange(len(s)), index=s.index)
        return pos - pos.where(s == 1).ffill()
    df["rows_since_outage"] = g.transform(since_last).fillna(10_000)

    # label: does an outage occur in rows t+1 ... t+H ?  (NaN for the last H rows: future unknown)
    H = cfg["horizon"]
    df["label"] = g.transform(lambda s: s.iloc[::-1].shift(1).rolling(H, min_periods=H).max().iloc[::-1])

    # region ids (0 is reserved for regions never seen in training)
    if region_map is None:
        region_map = {r: i + 1 for i, r in enumerate(sorted(df["region"].unique()))}
    df["region_id"] = df["region"].map(region_map).fillna(0).astype(int)

    exclude = {"timestamp", "region", "outage", "label", "region_id"}
    feature_cols = [c for c in df.columns if c not in exclude]
    df[feature_cols] = df[feature_cols].replace([np.inf, -np.inf], np.nan)
    return df, feature_cols, region_map


def count_events(df):
    """Number of separate outages (not outage-hours) seen per region."""
    onset = (df["outage"] == 1) & (df.groupby("region")["outage"].shift(1).fillna(0) == 0)
    return df[onset].groupby("region").size().to_dict()


# =====================================================================================
# 2. MODELS - both expose  .predict(X, region_ids) -> probability of an outage
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
    out = []
    for i in range(0, len(X), 8192):                     # chunked so large inputs fit in memory
        xb = torch.tensor(X[i:i + 8192], dtype=torch.float32).to(device)
        rb = torch.tensor(r[i:i + 8192], dtype=torch.long).to(device)
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

    def save(self, out_dir):
        for s, m in zip(self.seeds, self.models):
            torch.save(m.state_dict(), os.path.join(out_dir, f"nn_seed{s}.pt"))

    @staticmethod
    def load(out_dir, seeds, n_numeric, n_regions):
        models = []
        for s in seeds:
            m = OutageNet(n_numeric, n_regions).to(device)
            m.load_state_dict(torch.load(os.path.join(out_dir, f"nn_seed{s}.pt"), map_location=device))
            m.eval()
            models.append(m)
        return NNEnsemble(models, seeds)

    @staticmethod
    def fit(Xtr, rtr, ytr, Xva, rva, yva, n_regions, tmp_dir):
        seeds = list(range(42, 42 + C.N_SEEDS))
        return NNEnsemble([_train_one_net(s, Xtr, rtr, ytr, Xva, rva, yva, n_regions, tmp_dir)
                           for s in seeds], seeds)


# =====================================================================================
# 3. RISK LEVELS
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
# 4. OutageModel - everything needed to score regions, in one object
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
                             "outage_config.py must match what the model was trained with.")
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
            raise SystemExit(f"No trained model found in {out_dir}. Run train.py first.")
        a = joblib.load(p)
        nn_ens = NNEnsemble.load(out_dir, a["seeds"], len(a["feature_cols"]), len(a["region_map"]))
        return OutageModel(nn_ens, GBMModel.load(out_dir), a["w_nn"], a["scaler"], a["medians"],
                           a["calibrator"], a["cutoffs"], a["feature_cols"], a["region_map"],
                           a["region_events"], a["horizon"])


# =====================================================================================
# utilities
# =====================================================================================
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


def save_risk(out, out_dir):
    """Write the app-facing results as CSV and JSON."""
    os.makedirs(out_dir, exist_ok=True)
    out.to_csv(os.path.join(out_dir, "risk_latest.csv"), index=False)
    out.assign(timestamp=out["timestamp"].astype(str)).to_json(
        os.path.join(out_dir, "risk_latest.json"), orient="records", indent=2)
    print(out.drop(columns=["top_factors"]).to_string(index=False))
    print(f"\nSaved risk_latest.csv and risk_latest.json in {out_dir}/")
