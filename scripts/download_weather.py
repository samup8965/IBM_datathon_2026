"""Download hourly temperature, humidity and heat index for every Venezuelan state.

Source: Open-Meteo historical weather API (free, no key, CC BY 4.0 - credit Open-Meteo).
One point per state = its capital city. State names match the IODA download.

Output: one CSV with a row per (state, hour).
Uses only the Python standard library.

Usage (from the repo root):
    uv run python scripts/download_weather.py                    # Mar 2022 -> today
    uv run python scripts/download_weather.py --start 2025-01-01 --out data/raw/weather_ve_2025.csv
"""

import argparse
import csv
import json
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

API = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES = ["temperature_2m", "relative_humidity_2m", "apparent_temperature"]
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "weather_ve.csv"

# state name (as IODA spells it) -> (capital city, latitude, longitude)
STATES = {
    "Falcón": ("Coro", 11.40, -69.68),
    "Apure": ("San Fernando de Apure", 7.89, -67.47),
    "Barinas": ("Barinas", 8.62, -70.21),
    "Mérida": ("Mérida", 8.59, -71.14),
    "Táchira": ("San Cristóbal", 7.77, -72.22),
    "Trujillo": ("Trujillo", 9.37, -70.43),
    "Zulia": ("Maracaibo", 10.65, -71.64),
    "Cojedes": ("San Carlos", 9.66, -68.58),
    "Carabobo": ("Valencia", 10.16, -68.00),
    "Lara": ("Barquisimeto", 10.07, -69.32),
    "Portuguesa": ("Guanare", 9.04, -69.74),
    "Yaracuy": ("San Felipe", 10.34, -68.74),
    "Amazonas": ("Puerto Ayacucho", 5.66, -67.62),
    "Bolívar": ("Ciudad Bolívar", 8.12, -63.55),
    "Anzoátegui": ("Barcelona", 10.13, -64.69),
    "Aragua": ("Maracay", 10.25, -67.60),
    "Vargas": ("La Guaira", 10.60, -66.93),
    "Distrito Capital": ("Caracas", 10.49, -66.88),
    "Dependencias Federales": ("Gran Roque", 11.95, -66.68),
    "Guárico": ("San Juan de los Morros", 9.91, -67.35),
    "Monagas": ("Maturín", 9.75, -63.18),
    "Miranda": ("Los Teques", 10.34, -67.04),
    "Nueva Esparta": ("La Asunción", 11.03, -63.86),
    "Sucre": ("Cumaná", 10.46, -64.17),
    "Delta Amacuro": ("Tucupita", 9.06, -62.05),
}


def heat_index_c(temp_c, rh):
    """NOAA heat index (Rothfusz regression), input/output in Celsius."""
    if temp_c is None or rh is None:
        return None
    t = temp_c * 9 / 5 + 32
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    if (simple + t) / 2 < 80:  # cool/mild conditions: simple formula is enough
        hi = simple
    else:
        hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh
              - 6.83783e-3 * t * t - 5.481717e-2 * rh * rh + 1.22874e-3 * t * t * rh
              + 8.5282e-4 * t * rh * rh - 1.99e-6 * t * t * rh * rh)
    return round((hi - 32) * 5 / 9, 1)


def get_json(url, retries=3):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                return json.load(resp)
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"  retry after error: {exc}")
            time.sleep(10 * (attempt + 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2022-03-01", help="YYYY-MM-DD")
    parser.add_argument("--end", default=date.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="default: data/raw/weather_ve.csv")
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["state", "city", "timestamp_utc", "timestamp_vet",
                         "temp_c", "humidity_pct", "apparent_temp_c", "heat_index_c"])
        for state, (city, lat, lon) in STATES.items():
            url = (f"{API}?latitude={lat}&longitude={lon}"
                   f"&start_date={args.start}&end_date={args.end}"
                   f"&hourly={','.join(VARIABLES)}&timezone=America%2FCaracas")
            hourly = get_json(url)["hourly"]
            for ts, temp, rh, app in zip(hourly["time"], hourly["temperature_2m"],
                                         hourly["relative_humidity_2m"],
                                         hourly["apparent_temperature"]):
                vet = datetime.fromisoformat(ts)  # already Venezuela time (UTC-4)
                utc = vet + timedelta(hours=4)
                hi = heat_index_c(temp, rh)
                writer.writerow([state, city, utc.strftime("%Y-%m-%d %H:%M"),
                                 vet.strftime("%Y-%m-%d %H:%M"),
                                 "" if temp is None else temp,
                                 "" if rh is None else rh,
                                 "" if app is None else app,
                                 "" if hi is None else hi])
            print(f"  {state:<22} ({city}) {len(hourly['time']):>6} hours")
            time.sleep(1)  # stay well inside the free-tier rate limit

    print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
