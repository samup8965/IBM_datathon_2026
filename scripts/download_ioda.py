"""Download IODA internet connectivity signals for every Venezuelan state.

Output: one long-format CSV with a row per (state, datasource, timestamp).
Uses only the Python standard library.

Usage (from the repo root):
    uv run python scripts/download_ioda.py                       # all states, Mar 2022 -> now
    uv run python scripts/download_ioda.py --start 2025-01-01    # custom start date
    uv run python scripts/download_ioda.py --out data/raw/ioda_ve_2025.csv.gz
    uv run python scripts/download_ioda.py --datasources ping-slash24 bgp merit-nt

Regional data starts around March 2022. ping-slash24 alone since then is roughly
6M rows (~300 MB as plain CSV); all three datasources is ~5x that. The default
output is gzipped (about 10x smaller); pandas reads it with pd.read_csv as is.
"""

import argparse
import csv
import gzip
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.ioda.inetintel.cc.gatech.edu/v2"
VET = timezone(timedelta(hours=-4))  # Venezuela time, no daylight saving
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "ioda_ve.csv.gz"

# ping-slash24 = how many address blocks answer pings -> best proxy for power cuts
# bgp          = routes announced (barely moves when power goes, kept for comparison)
# merit-nt     = background traffic seen by a network telescope
DEFAULT_DATASOURCES = ["ping-slash24"]  # add bgp/merit-nt with --datasources if needed

CHUNK_DAYS = 30  # one request per state/datasource per 30 days


def get_json(url, retries=3):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return json.load(resp)
        except Exception as exc:  # network hiccups: wait and retry
            if attempt == retries - 1:
                raise
            print(f"  retry after error: {exc}")
            time.sleep(5 * (attempt + 1))


def venezuelan_states():
    data = get_json(f"{API}/entities/query?entityType=region&relatedTo=country/VE")["data"]
    # drop placeholder entries such as "[Invalid Region (4481)]" and "Unknown Region"
    return [(e["code"], e["name"]) for e in data
            if not e["name"].startswith("[") and not e["name"].startswith("Unknown")]


def fetch_series(state_code, datasource, start, end):
    """Yield (unix_ts, value) for one state and datasource between start and end."""
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), end)
        url = (f"{API}/signals/raw/region/{state_code}"
               f"?from={int(chunk_start.timestamp())}&until={int(chunk_end.timestamp())}"
               f"&datasource={datasource}")
        for group in get_json(url)["data"]:
            for series in group:
                for i, value in enumerate(series["values"]):
                    yield series["from"] + i * series["step"], value
        chunk_start = chunk_end
        time.sleep(0.5)  # be polite to the API


def open_output(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        return gzip.open(path, "wt", newline="", encoding="utf-8")
    return open(path, "w", newline="", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2022-03-01", help="UTC date, YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="UTC date, YYYY-MM-DD (default: now)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="end in .gz to compress (default: data/raw/ioda_ve.csv.gz)")
    parser.add_argument("--datasources", nargs="+", default=DEFAULT_DATASOURCES,
                        help="e.g. --datasources ping-slash24 bgp merit-nt")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = (datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
           if args.end else datetime.now(timezone.utc))

    states = venezuelan_states()
    print(f"{len(states)} states, {start:%Y-%m-%d} -> {end:%Y-%m-%d}")

    with open_output(args.out) as f:
        writer = csv.writer(f)
        writer.writerow(["state_code", "state", "datasource",
                         "timestamp_utc", "timestamp_vet", "value"])
        for code, name in states:
            for ds in args.datasources:
                rows = 0
                for ts, value in fetch_series(code, ds, start, end):
                    utc = datetime.fromtimestamp(ts, timezone.utc)
                    writer.writerow([code, name, ds,
                                     utc.strftime("%Y-%m-%d %H:%M"),
                                     utc.astimezone(VET).strftime("%Y-%m-%d %H:%M"),
                                     "" if value is None else value])  # blank = missing, NOT an outage
                    rows += 1
                print(f"  {name:<22} {ds:<13} {rows:>7} rows")

    print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
