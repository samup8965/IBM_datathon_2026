"""
features.py - load every dataset, line them up in time and build the model inputs.

Used by scripts/train.py, scripts/predict.py and app/api.py. Settings live in src/config.py.
"""
import os

import numpy as np
import pandas as pd

from src import config as C


def _path(data_dir, p):
    p = os.path.expanduser(p)
    return p if os.path.isabs(p) else os.path.join(data_dir, p)


def _std_time(s):
    """Parse to naive UTC datetime64[ns] so every file uses the same clock."""
    return pd.to_datetime(s, utc=True).dt.tz_localize(None).astype("datetime64[ns]")


def _read(data_dir, path, time, region=None, cols=()):
    full = _path(data_dir, path)
    if not os.path.exists(full):
        raise SystemExit(f"File not found: {full}\n(use --data-dir, or fix 'path' in src/config.py)")
    d = pd.read_csv(full)
    need = [c for c in [time, region, *cols] if c]
    missing = [c for c in need if c not in d.columns]
    if missing:
        raise SystemExit(f"{path}: missing column(s) {missing}. Columns found: {list(d.columns)}\n"
                         f"(fix the names in src/config.py)")
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
              "Set 'regularize_freq' (e.g. 'h') in src/config.py to fix this.")


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
