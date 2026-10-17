"""Measure real outage patterns from the IODA and weather downloads.

The numbers are written to data/calibration.json, which scripts/generate_data.py
reads so the synthetic data follows real Venezuelan patterns. Only data up to
--until is used, so the months after it stay unseen for validating the model.

An "outage hour" is an hour where a state's ping-slash24 connectivity is below
DROP_THRESHOLD of its best level over the previous BASELINE_DAYS days (a high
percentile, so one odd spike does not set the bar). Comparing with the best level,
not the usual level, keeps chronic daily cuts visible: if a state loses power every
night, "usual" would absorb those cuts and hide them. Only past data sets the bar,
so the same definition works for live data. Blank IODA values are missing data,
not outages.

Usage (from the repo root):
    uv run python scripts/calibrate.py
    uv run python scripts/calibrate.py --until 2024-12-31
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from download_weather import STATES as CAPITALS

ROOT = Path(__file__).resolve().parents[1]
IODA_PATH = ROOT / "data" / "raw" / "ioda_ve.csv.gz"
WEATHER_PATH = ROOT / "data" / "raw" / "weather_ve.csv"
OUT_PATH = ROOT / "data" / "calibration.json"

DROP_THRESHOLD = 0.9      # outage hour = connectivity below 90% of its best recent level
BASELINE_DAYS = 14        # best level = BASELINE_QUANTILE of the previous 14 days
BASELINE_QUANTILE = 0.95  # (at 95% even stable Caracas is "out" ~17% of hours: too noisy;
                          #  at 90% Caracas sits at ~5% while Táchira/Barinas reach ~30%)
HOT_QUANTILE = 0.75   # hot day = daily max heat index in the state's top 25%
MIN_BLOCKS = 50       # below this many address blocks a few blocks going quiet looks like
                      # an outage (at 27 blocks, 3 quiet ones cross the 90% line), so the
                      # state is flagged low_signal and left out of averages and the model
HEAT_PRIOR_DAYS = 50  # a state's own heat effect counts fully only with many outage days;
                      # with fewer it is pulled toward the national value


def load_connectivity_ratio(until, path=IODA_PATH):
    """Hourly connectivity / best recent level, as an (hour x state) table in Venezuela time."""
    df = pd.read_csv(path, usecols=["state", "datasource", "timestamp_vet", "value"],
                     parse_dates=["timestamp_vet"])
    df = df[(df.datasource == "ping-slash24") & (df.timestamp_vet < until)]
    df["hour"] = df.timestamp_vet.dt.floor("h")
    # The newest hour is often still filling up when the data is downloaded; with fewer
    # readings than usual it would look like a drop everywhere, so leave it out.
    readings = df.groupby("hour").value.count()
    if len(readings) > 24 and readings.iloc[-1] < readings.iloc[-25:-1].median():
        df = df[df.hour < readings.index[-1]]
    hourly = df.groupby(["hour", "state"]).value.mean().unstack("state")
    hourly = hourly.reindex(pd.date_range(hourly.index.min(), hourly.index.max(), freq="h"))

    hours = 24 * BASELINE_DAYS
    baseline = (hourly.rolling(hours, min_periods=hours // 2)
                .quantile(BASELINE_QUANTILE).shift(1))
    return hourly / baseline, hourly


def run_lengths(flags):
    """Lengths of consecutive True runs in a boolean Series."""
    lengths = flags.groupby((~flags).cumsum()).sum()
    return lengths[lengths > 0]


def state_stats(ratio):
    stats = {}
    for state in ratio.columns:
        r = ratio[state].dropna()
        out = r < DROP_THRESHOLD
        daily = out.groupby(r.index.date).mean()
        stats[state] = {
            "outage_hour_share": round(out.mean(), 4),
            "days_with_outage_share": round((daily > 0).mean(), 4),
            "mean_drop_when_out": round((1 - r[out]).clip(0, 1).mean(), 4) if out.any() else 0.0,
            "mean_duration_h": round(run_lengths(out).mean(), 2) if out.any() else 1.0,
            "valid_hours": int(len(r)),
        }
    return stats


def relative_profile(ratio, key):
    """Outage rate by hour/month relative to each state's own rate, averaged over states."""
    out = (ratio < DROP_THRESHOLD).where(ratio.notna()).astype(float)
    rates = out.groupby(key).mean()
    rel = rates / out.mean()
    profile = rel.replace([np.inf, -np.inf], np.nan).mean(axis=1)
    return (profile / profile.mean()).round(3).tolist()


def heat_stats(ratio, until, reliable):
    weather = pd.read_csv(WEATHER_PATH, usecols=["state", "timestamp_vet", "heat_index_c"],
                          parse_dates=["timestamp_vet"])
    weather = weather[weather.timestamp_vet < until].dropna()
    weather["date"] = weather.timestamp_vet.dt.date
    weather["month"] = weather.timestamp_vet.dt.month
    weather["hour"] = weather.timestamp_vet.dt.hour

    out = (ratio < DROP_THRESHOLD).where(ratio.notna())
    daily_out = out.groupby(out.index.date).mean()

    stats, climatology = {}, {}
    for state, w in weather.groupby("state"):
        daily_max = w.groupby("date").heat_index_c.max()
        hot_threshold = daily_max.quantile(HOT_QUANTILE)
        if state in daily_out:
            joined = pd.DataFrame({"hot": daily_max >= hot_threshold,
                                   "out": daily_out[state]}).dropna()
            joined["hot"] = joined.hot.astype(bool)  # NaNs from the join made it object dtype
            hot_rate = joined.loc[joined.hot, "out"].mean()
            other_rate = joined.loc[~joined.hot, "out"].mean()
            heat_rr = hot_rate / other_rate if other_rate > 0 and hot_rate > 0 else np.nan
            outage_days = int((joined.out > 0).sum())
        else:
            heat_rr, outage_days = np.nan, 0

        # Climatology for the generator: mean heat index by month and hour, plus how
        # much each day's mean wanders from normal and how long hot spells last.
        mean_mh = w.groupby(["month", "hour"]).heat_index_c.mean().unstack("hour")
        daily_mean = w.groupby("date").heat_index_c.mean()
        month_of_day = pd.to_datetime(daily_mean.index).month
        normal = w.groupby("month").heat_index_c.mean().reindex(month_of_day).to_numpy()
        anomaly = daily_mean.to_numpy() - normal
        anomaly_std = pd.Series(anomaly).groupby(month_of_day).std()

        stats[state] = {"hot_day_threshold_c": round(hot_threshold, 1),
                        "heat_rr_raw": heat_rr, "outage_days": outage_days}
        climatology[state] = {
            "mean_by_month_hour": mean_mh.round(1).to_numpy().tolist(),  # 12 x 24
            "daily_anomaly_std_by_month": anomaly_std.reindex(range(1, 13)).round(2).tolist(),
            "daily_anomaly_ar1": round(pd.Series(anomaly).autocorr(), 3),
        }

    # National heat effect: reliable states' effects weighted by their outage days.
    # Each state's own value is then pulled toward it when it has few outage days.
    usable = {s: v for s, v in stats.items()
              if s in reliable and not np.isnan(v["heat_rr_raw"]) and v["outage_days"]}
    weights = np.array([v["outage_days"] for v in usable.values()])
    logs = np.log([v["heat_rr_raw"] for v in usable.values()])
    national_log = float(np.sum(weights * logs) / weights.sum())
    for v in stats.values():
        w = v["outage_days"] / (v["outage_days"] + HEAT_PRIOR_DAYS)
        own = np.log(v["heat_rr_raw"]) if not np.isnan(v["heat_rr_raw"]) else national_log
        v["heat_rr"] = round(float(np.exp(w * own + (1 - w) * national_log)), 3)
        v["heat_rr_raw"] = None if np.isnan(v["heat_rr_raw"]) else round(v["heat_rr_raw"], 3)
    return stats, climatology, round(float(np.exp(national_log)), 3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--until", default="2024-12-31",
                        help="last date (Venezuela time) used for calibration")
    args = parser.parse_args()
    until = pd.Timestamp(args.until) + pd.Timedelta(days=1)

    ratio, hourly = load_connectivity_ratio(until)
    blocks = hourly.mean()
    reliable = [s for s in ratio.columns if blocks[s] >= MIN_BLOCKS]
    states = state_stats(ratio)
    heat, climatology, national_heat_rr = heat_stats(ratio, until, reliable)

    for name in states:
        states[name].update(heat[name])
        states[name]["connected_blocks"] = round(float(blocks[name]), 1)
        states[name]["low_signal"] = name not in reliable
        city, lat, lon = CAPITALS[name]
        states[name].update({"capital": city, "lat": lat, "lon": lon})

    calibration = {
        "meta": {
            "created": datetime.now().isoformat(timespec="seconds"),
            "calibration_from": str(ratio.index.min().date()),
            "calibration_until": args.until,
            "drop_threshold": DROP_THRESHOLD,
            "baseline_days": BASELINE_DAYS,
            "baseline_quantile": BASELINE_QUANTILE,
            "hot_quantile": HOT_QUANTILE,
            "min_blocks": MIN_BLOCKS,
            "heat_prior_days": HEAT_PRIOR_DAYS,
            "sources": ["IODA ping-slash24 (Georgia Tech)", "Open-Meteo historical weather"],
        },
        "national_heat_rr": national_heat_rr,
        "hour_profile_vet": relative_profile(ratio[reliable], ratio.index.hour),
        "month_profile": relative_profile(ratio[reliable], ratio.index.month),
        "states": states,
        "heat_climatology": climatology,
    }
    OUT_PATH.write_text(json.dumps(calibration, indent=1, ensure_ascii=False))

    table = pd.DataFrame(states).T[["connected_blocks", "outage_hour_share",
                                    "days_with_outage_share", "mean_duration_h",
                                    "outage_days", "heat_rr_raw", "heat_rr", "low_signal"]]
    print(table.sort_values("outage_hour_share", ascending=False).to_string())
    print(f"\nnational heat effect: {national_heat_rr}x outage rate on hot days")
    print(f"\nSaved {OUT_PATH.relative_to(ROOT)} ({ratio.index.min():%Y-%m-%d} -> {args.until})")


if __name__ == "__main__":
    main()
