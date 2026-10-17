"""serving.py - turn the model's latest scores into what the apps show (used by app/api.py).

One record per Venezuelan state, keyed by ISO code. The fields the apps already decode
(see OutageAlert/OutageAlert/Models/Prediction.swift):
    location, risk_probability, risk_level (low/moderate/severe/critical), updated_at,
    grid_stability, electricity_demand, weather_risk
plus extras the apps may ignore: region_id, name, status, outage_in_progress,
confidence, top_factors, connectivity_pct, heat_index_c, data_through.
"""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src import config as C
from src.features import build_dataset
from src.regions import REGIONS

# Model inputs in words people understand, for the "why" shown in the apps
FACTOR_TEXT = {
    "outage_now": "an outage right now",
    "outage_lag1": "an outage an hour ago",
    "outage_lag6": "an outage 6 hours ago",
    "outage_lag24": "an outage this time yesterday",
    "outage_roll24": "outages in the past 24 hours",
    "outage_roll168": "outages in the past week",
    "rows_since_outage": "time since the last outage",
    "net_connectivity": "current connectivity",
    "net_connectivity_min24": "connectivity dips in the past 24 hours",
    "net_connectivity_rel168": "connectivity below its weekly norm",
    "net_missing": "missing connectivity data",
    "heat_heat_index": "current heat",
    "heat_heat_index_max24": "peak heat in the past 24 hours",
    "heat_heat_index_mean72": "heat over the past 3 days",
    "heat_heat_index_d24": "heat rising since yesterday",
    "heat_missing": "missing weather data",
    "hour_sin": "time of day",
    "hour_cos": "time of day",
    "month_sin": "season",
    "month_cos": "season",
    "is_weekend": "day of the week",
}


def grid_stability(connectivity_pct):
    """Connectivity as % of the state's best level over the past 2 weeks; below 90 is an outage."""
    if connectivity_pct is None or np.isnan(connectivity_pct):
        return "Unknown"
    if connectivity_pct >= 97:
        return "Stable"
    if connectivity_pct >= 93:
        return "Fluctuating"
    if connectivity_pct >= 90:
        return "Unstable"
    return "Highly unstable"


def weather_risk(heat_index_c):
    """NOAA heat-index bands (°C): caution 27, extreme caution 32, danger 41."""
    if heat_index_c is None or np.isnan(heat_index_c):
        return "Unknown"
    return ("Low" if heat_index_c < 27 else "Moderate" if heat_index_c < 32
            else "Severe" if heat_index_c < 41 else "Critical")


def electricity_demand(heat_index_c, hour):
    """An estimate, not a measurement: air conditioning load grows with heat, and the
    evening (18:00-22:00) adds lighting and cooking."""
    if heat_index_c is None or np.isnan(heat_index_c):
        return "Unknown"
    level = 0 if heat_index_c < 27 else 1 if heat_index_c < 32 else 2 if heat_index_c < 41 else 3
    level = min(3, level + (18 <= hour < 22))
    return ["Normal", "Elevated", "High", "Peak load"][level]


def readable_factors(top_factors):
    """'outage_roll24; net_connectivity_min24' -> ['outages in the past 24 hours', ...]"""
    words = [FACTOR_TEXT.get(f.strip(), f.strip()) for f in str(top_factors or "").split(";") if f.strip()]
    return list(dict.fromkeys(words))  # drop repeats (hour_sin/hour_cos), keep order


def _number(value, digits=1):
    return None if value is None or pd.isna(value) else round(float(value), digits)


def build_snapshot(model, data_dir):
    """Score every state on the newest data in data_dir. Returns one dict per state, all
    25 of them: states the model does not cover come back with status 'insufficient_data'."""
    df, _, _ = build_dataset(data_dir, region_map=model.region_map)
    scores = model.score_latest(df).set_index("region")
    latest = df.sort_values("timestamp").groupby("region").tail(1).set_index("region")
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tz = C.CONFIG.get("timezone", "UTC")

    snapshot = []
    for key, (iso, name) in REGIONS.items():
        record = {"region_id": iso, "name": name, "location": f"{name}, Venezuela",
                  "updated_at": updated_at}
        if key not in scores.index:
            snapshot.append({**record, "status": "insufficient_data"})
            continue
        score, row = scores.loc[key], latest.loc[key]
        in_progress = score["risk_level"] == "Outage in progress"
        connectivity = _number(row.get("net_connectivity"))
        heat = _number(row.get("heat_heat_index_max24"))
        snapshot.append({
            **record,
            "status": "ok",
            "risk_probability": round(float(score["risk_probability"]), 4),
            # the apps know four levels; an outage under way shows as critical + the flag
            "risk_level": "critical" if in_progress else str(score["risk_level"]).lower(),
            "outage_in_progress": bool(in_progress),
            "confidence": str(score["confidence"]).lower(),
            "top_factors": readable_factors(score["top_factors"]),
            "grid_stability": grid_stability(connectivity),
            "electricity_demand": electricity_demand(heat, pd.Timestamp(score["timestamp"]).hour),
            "weather_risk": weather_risk(heat),
            "connectivity_pct": connectivity,
            "heat_index_c": heat,
            "data_through": pd.Timestamp(score["timestamp"]).tz_localize(tz).isoformat(),
        })
    return snapshot
