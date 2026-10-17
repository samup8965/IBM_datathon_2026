"""Fetch the latest data and rebuild the model's live inputs in data/model_input/live/.

The API (app/api.py) re-reads that folder every few minutes, so running this keeps the
forecast about today. One cycle takes a minute or two:
  1. IODA connectivity for every state over the last --days days (the model needs about
     3 weeks: a 2-week baseline for the outage definition plus a week of history)
  2. weather for the same days from Open-Meteo's forecast service (its archive, used for
     training, lags about 5 days)
  3. the model's input CSVs, with the same outage definition as training

The new files replace the old ones only once a cycle has succeeded; a failed cycle
leaves the previous data in place.

Usage (from the repo root):
    python scripts/refresh.py                       # once
    python scripts/refresh.py --every 60            # now, then every 60 minutes
    python scripts/refresh.py --every 60 --wait     # first cycle after 60 minutes
"""

import argparse
import csv
import gzip
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import download_ioda as ioda
import download_weather as weather
from export_model_input import CALIBRATION_PATH, OUT_DIR, export_real, write

ROOT = Path(__file__).resolve().parents[1]
IODA_RECENT = ROOT / "data" / "raw" / "ioda_recent.csv.gz"
WEATHER_RECENT = ROOT / "data" / "raw" / "weather_recent.csv"
LIVE_DIR = OUT_DIR / "live"
FORECAST_API = "https://api.open-meteo.com/v1/forecast"


def fetch_ioda(days, path):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["state_code", "state", "datasource", "timestamp_utc", "timestamp_vet", "value"])
        for code, name in ioda.venezuelan_states():
            for ts, value in ioda.fetch_series(code, "ping-slash24", start, end):
                utc = datetime.fromtimestamp(ts, timezone.utc)
                writer.writerow([code, name, "ping-slash24", utc.strftime("%Y-%m-%d %H:%M"),
                                 utc.astimezone(ioda.VET).strftime("%Y-%m-%d %H:%M"),
                                 "" if value is None else value])
    tmp.replace(path)


def fetch_weather(days, path):
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["state", "city", "timestamp_utc", "timestamp_vet",
                         "temp_c", "humidity_pct", "apparent_temp_c", "heat_index_c"])
        for state, (city, lat, lon) in weather.STATES.items():
            url = (f"{FORECAST_API}?latitude={lat}&longitude={lon}&past_days={days}"
                   f"&forecast_days=1&hourly={','.join(weather.VARIABLES)}&timezone=America%2FCaracas")
            hourly = weather.get_json(url)["hourly"]
            for ts, temp, rh, app in zip(hourly["time"], hourly["temperature_2m"],
                                         hourly["relative_humidity_2m"], hourly["apparent_temperature"]):
                vet = datetime.fromisoformat(ts)  # already Venezuela time (UTC-4)
                hi = weather.heat_index_c(temp, rh)
                writer.writerow([state, city, (vet + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M"),
                                 vet.strftime("%Y-%m-%d %H:%M"),
                                 "" if temp is None else temp, "" if rh is None else rh,
                                 "" if app is None else app, "" if hi is None else hi])
            time.sleep(0.2)
    tmp.replace(path)


def rebuild_live_inputs():
    states = json.loads(CALIBRATION_PATH.read_text())["states"]
    skip = {s for s, v in states.items() if v["low_signal"]}
    frames = export_real(skip, pd.Timestamp.min, ioda_path=IODA_RECENT, weather_path=WEATHER_RECENT)
    staging = OUT_DIR / "live.tmp"
    write(frames, staging)
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    for f in staging.iterdir():
        f.replace(LIVE_DIR / f.name)  # one file at a time, each replaced in a single step
    staging.rmdir()


def cycle(days):
    started = time.time()
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] refreshing the last {days} days")
    fetch_ioda(days, IODA_RECENT)
    print("  IODA connectivity downloaded")
    fetch_weather(days, WEATHER_RECENT)
    print("  weather downloaded")
    rebuild_live_inputs()
    print(f"  live inputs updated in {LIVE_DIR.relative_to(ROOT)} ({time.time() - started:.0f}s)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30, help="days of history to fetch (max 92)")
    parser.add_argument("--every", type=int, default=0, help="repeat every N minutes (0 = once)")
    parser.add_argument("--wait", action="store_true", help="wait one interval before the first cycle")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # show progress in logs as it happens

    if args.wait and args.every:
        time.sleep(args.every * 60)
    while True:
        try:
            cycle(args.days)
        except Exception as e:  # network hiccups: keep the previous data and try next time
            print(f"  refresh failed, previous data kept: {type(e).__name__}: {e}")
            if not args.every:
                sys.exit(1)
        if not args.every:
            break
        time.sleep(args.every * 60)


if __name__ == "__main__":
    main()
