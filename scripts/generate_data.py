"""Generate synthetic grid, rationing and household data calibrated to real patterns.

Reads data/calibration.json (from scripts/calibrate.py). Measured numbers set each
state's outage rate, outage length, connectivity drop, time-of-day profile, heat
effect and climate. Everything marked ASSUMPTION is a modelling choice, not data.

Cause and effect built in:
    low Guri reservoir or thermal plant failures -> less supply
    heat -> more demand, and more failures on hot days (measured per state)
    supply short of demand -> rotating rationing blocks, west first, Caracas last
    rationing + failures -> outages -> connectivity drops (measured depth per state)

Usage (from the repo root):
    uv run python scripts/generate_data.py
    uv run python scripts/generate_data.py --start 2022-01-01 --years 3 --households 5000 --seed 42

Outputs: data/synthetic/grid_hourly.csv.gz and data/synthetic/households.csv
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_PATH = ROOT / "data" / "calibration.json"
OUT_DIR = ROOT / "data" / "synthetic"

REGIONS = {
    "west": ["Zulia", "Táchira", "Mérida", "Trujillo", "Falcón", "Lara", "Barinas",
             "Portuguesa", "Apure"],
    "central": ["Carabobo", "Aragua", "Yaracuy", "Cojedes", "Guárico", "Miranda", "Vargas",
                "Distrito Capital"],
    "east": ["Anzoátegui", "Monagas", "Sucre", "Nueva Esparta", "Delta Amacuro", "Bolívar",
             "Amazonas", "Dependencias Federales"],
}
PROTECTED = {"Distrito Capital"}  # ASSUMPTION: Caracas is rationed only at the worst level

# ASSUMPTION: Guri reservoir level in metres above sea level. Fullest around mid-October
# after the rainy season, lowest around April; some years are droughts.
GURI_MIN_M, GURI_MAX_M = 240.0, 271.0
GURI_MEAN_M, GURI_SEASONAL_M, GURI_PEAK_DOY = 259.0, 7.0, 290
DROUGHT_PROB, DROUGHT_DROP_M = 0.3, 8.0

# ASSUMPTION: about 65% of supply is hydro (mostly Guri), the rest thermal plants
# that sometimes fail for a few days.
HYDRO_SHARE = 0.65
SUPPLY_CAPACITY = 1.50  # tuned so rationing runs on ~35% of days, mostly Mar-May
THERMAL_FAILURE_PER_DAY, THERMAL_FAILURE_DAYS, THERMAL_FAILURE_LOSS = 0.04, (1, 6), 0.4

# ASSUMPTION: national demand by hour of day (Venezuela time), 1 = average.
# Air conditioning peaks in the afternoon, lighting in the evening.
DEMAND_BY_HOUR = [0.82, 0.78, 0.76, 0.75, 0.76, 0.80, 0.88, 0.95, 1.00, 1.04, 1.08, 1.12,
                  1.15, 1.17, 1.17, 1.15, 1.12, 1.10, 1.14, 1.18, 1.16, 1.08, 0.97, 0.88]
DEMAND_HEAT_PER_C = 0.03  # +3% demand per °C the country is hotter than normal

# Shortfall (demand - supply) that switches on each rationing level, and who it covers.
RATIONING_LEVELS = [(0.00, {"west"}), (0.12, {"west", "central"}),
                    (0.24, {"west", "central", "east"})]
RATIONING_BLOCK_HOURS = 4    # each state is cut for 4 hours, then the next block rotates in
RATIONING_SHARE_CAP = 0.6    # rationing explains at most 60% of a state's outage hours
GAP_FAILURE_COEF = 3.0       # unplanned failures grow by exp(3 x shortfall)
HEAT_SHOCK_NATIONAL = 0.7    # how much of each day's heat anomaly is shared nationwide

# ASSUMPTION: household shares. Not measured; no public data exists.
MEDICAL_DEVICES = {"none": 0.93, "refrigerated_medicine": 0.03, "oxygen_concentrator": 0.025,
                   "powered_wheelchair_or_bed": 0.01, "home_dialysis": 0.005}
DEVICE_WEIGHT = {"none": 0, "refrigerated_medicine": 1, "powered_wheelchair_or_bed": 2,
                 "oxygen_concentrator": 3, "home_dialysis": 3}
ELDERLY_SHARE, BACKUP_POWER_SHARE = 0.25, 0.12


def region_of(state):
    return next(r for r, states in REGIONS.items() if state in states)


def simulate_heat(cal, days, rng):
    """Daily heat-index anomaly per state: AR(1) with a shared national component."""
    states = list(cal["states"])
    national = rng.standard_normal(len(days))
    anomalies = {}
    for state in states:
        clim = cal["heat_climatology"][state]
        phi = clim["daily_anomaly_ar1"]
        std = np.array(clim["daily_anomaly_std_by_month"], dtype=float)
        std = np.where(np.isnan(std), np.nanmean(std), std)[days.month - 1]
        shock = (HEAT_SHOCK_NATIONAL * national
                 + np.sqrt(1 - HEAT_SHOCK_NATIONAL ** 2) * rng.standard_normal(len(days)))
        a = np.zeros(len(days))
        for d in range(1, len(days)):
            a[d] = phi * a[d - 1] + np.sqrt(1 - phi ** 2) * shock[d]
        anomalies[state] = a * std
    return pd.DataFrame(anomalies, index=days)


def simulate_supply(days, rng):
    """Daily Guri level (m) and thermal plant availability (0-1)."""
    years = days.year.unique()
    drought = dict(zip(years, rng.random(len(years)) < DROUGHT_PROB))
    seasonal = GURI_SEASONAL_M * np.cos(2 * np.pi * (days.dayofyear - GURI_PEAK_DOY) / 365.25)
    # Droughts build up through the dry season, so the drop peaks around April-May.
    drought_drop = np.array([DROUGHT_DROP_M if drought[y] else 0.0 for y in days.year])
    drought_drop *= np.clip(np.sin(np.pi * (days.dayofyear.to_numpy() - 30) / 240), 0, 1)
    noise = np.cumsum(rng.normal(0, 0.15, len(days)))
    noise -= np.linspace(noise[0], noise[-1], len(days))  # random wander that ends where it started
    guri = np.clip(GURI_MEAN_M + seasonal - drought_drop + noise, GURI_MIN_M, GURI_MAX_M)

    thermal = np.ones(len(days))
    d = 0
    while d < len(days):
        if rng.random() < THERMAL_FAILURE_PER_DAY:
            length = rng.integers(*THERMAL_FAILURE_DAYS, endpoint=True)
            thermal[d:d + length] -= THERMAL_FAILURE_LOSS
            d += length
        else:
            d += 1
    return pd.DataFrame({"guri_level_m": guri.round(2), "thermal_avail": thermal}, index=days), drought


def simulate_outages(p_start, mean_duration, rng):
    """Outage flags from hourly start probabilities and geometric outage lengths."""
    out = np.zeros(len(p_start), dtype=bool)
    starts = rng.random(len(p_start)) < p_start
    lengths = rng.geometric(1 / max(mean_duration, 1.0), len(p_start))
    t = 0
    while t < len(p_start):
        if starts[t]:
            out[t:t + lengths[t]] = True
            t += lengths[t]
        else:
            t += 1
    return out


def generate_grid(cal, start, years, rng):
    hours = pd.date_range(start, pd.Timestamp(start) + pd.DateOffset(years=years),
                          freq="h", inclusive="left")
    days = hours.normalize().unique()
    day_idx = (hours.normalize() - days[0]).days.to_numpy()
    hour = hours.hour.to_numpy()

    heat_anom = simulate_heat(cal, days, rng)
    supply_daily, drought = simulate_supply(days, rng)

    # National supply and demand
    hydro_frac = ((supply_daily.guri_level_m - GURI_MIN_M) / (GURI_MAX_M - GURI_MIN_M)).to_numpy()
    supply = SUPPLY_CAPACITY * (HYDRO_SHARE * (0.4 + 0.6 * hydro_frac)
                                + (1 - HYDRO_SHARE) * supply_daily.thermal_avail.to_numpy())
    supply = supply[day_idx]
    national_heat = heat_anom.mean(axis=1).to_numpy()[day_idx]
    demand = np.array(DEMAND_BY_HOUR)[hour] * (1 + DEMAND_HEAT_PER_C * national_heat)
    shortfall = demand - supply
    # Rationing is planned per day from that day's worst shortfall, and its blocks then
    # rotate around the clock (real outages are spread fairly evenly over the day).
    daily_peak = pd.Series(shortfall).groupby(day_idx).transform("max").to_numpy()
    level = sum((daily_peak > threshold).astype(int) for threshold, _ in RATIONING_LEVELS)

    hour_profile = np.array(cal["hour_profile_vet"])[hour]
    block_slot = (hour // RATIONING_BLOCK_HOURS + day_idx) % 3
    # States with too few address blocks have noisy measurements; use their region's
    # median from reliable states instead.
    measured = ["outage_hour_share", "mean_duration_h", "mean_drop_when_out"]
    reliable = pd.DataFrame({s: v for s, v in cal["states"].items() if not v["low_signal"]}).T
    region_median = reliable.groupby(reliable.index.map(region_of))[measured].median()
    frames = []
    for state, s in cal["states"].items():
        region = region_of(state)
        position = REGIONS[region].index(state)
        if s["low_signal"]:
            s = {**s, **region_median.loc[region].astype(float).to_dict()}

        # Heat index: real climatology for the month and hour + simulated daily anomaly
        clim = np.array(cal["heat_climatology"][state]["mean_by_month_hour"], dtype=float)
        clim = np.where(np.isnan(clim), np.nanmean(clim), clim)
        heat = clim[hours.month - 1, hour] + heat_anom[state].to_numpy()[day_idx]
        daily_max = pd.Series(heat).groupby(day_idx).transform("max").to_numpy()
        hot_day = daily_max >= (s["hot_day_threshold_c"] or np.inf)
        heat_mult = np.where(hot_day, np.clip(s["heat_rr"] or 1.0, 0.5, 3.0), 1.0)

        # Rationing: covered when the current level includes this state's region,
        # then cut only during its rotating block
        top = len(RATIONING_LEVELS)
        covered_at_level = np.array([False] + [
            region in regions and (state not in PROTECTED or lvl == top)
            for lvl, (_, regions) in enumerate(RATIONING_LEVELS, start=1)])
        scheduled = covered_at_level[level] & (block_slot == position % 3)

        # Scale rationing and failures so the total outage share matches the real one
        target = s["outage_hour_share"]
        scheduled_share = scheduled.mean()
        compliance = min(1.0, RATIONING_SHARE_CAP * target / scheduled_share) if scheduled_share else 0
        block_id = day_idx * 24 // RATIONING_BLOCK_HOURS + hour // RATIONING_BLOCK_HOURS
        executed_blocks = rng.random(block_id.max() + 1) < compliance
        rationed = scheduled & executed_blocks[block_id]

        raw = hour_profile * heat_mult * np.exp(GAP_FAILURE_COEF * np.clip(daily_peak, 0, None))
        remaining = max(target - rationed.mean(), 0.0)
        p_start = np.clip(remaining / (raw.mean() * max(s["mean_duration_h"], 1.0)) * raw, 0, 0.9)
        failure = simulate_outages(p_start, s["mean_duration_h"], rng)

        outage = rationed | failure
        drop = outage * s["mean_drop_when_out"] * rng.uniform(0.7, 1.3, len(hours))
        connectivity = np.clip(100 * (1 - drop) + rng.normal(0, 2, len(hours)), 0, 110)

        frames.append(pd.DataFrame({
            "timestamp_vet": hours,
            "state": state,
            "region": region,
            "hour": hour,
            "weekday": hours.weekday,
            "month": hours.month,
            "heat_index_c": heat.round(1),
            "hot_day": hot_day,
            "guri_level_m": supply_daily.guri_level_m.to_numpy()[day_idx],
            "drought_year": [drought[y] for y in hours.year],
            "demand_idx": demand.round(3),
            "supply_idx": supply.round(3),
            "shortfall": shortfall.round(3),
            "rationing_level": level,
            "rationing_scheduled": scheduled,
            "outage": outage,
            "outage_cause": np.select([rationed, failure], ["rationing", "failure"], "none"),
            "connectivity_pct": connectivity.round(1),
        }))
    return pd.concat(frames, ignore_index=True)


def generate_households(cal, n, rng):
    states = list(cal["states"])
    weights = np.array([cal["states"][s]["connected_blocks"] for s in states])
    state = rng.choice(states, n, p=weights / weights.sum())
    lat = np.array([cal["states"][s]["lat"] for s in state]) + rng.normal(0, 0.12, n)
    lon = np.array([cal["states"][s]["lon"] for s in state]) + rng.normal(0, 0.12, n)
    device = rng.choice(list(MEDICAL_DEVICES), n, p=list(MEDICAL_DEVICES.values()))
    elderly = rng.random(n) < ELDERLY_SHARE
    backup = rng.random(n) < BACKUP_POWER_SHARE
    vulnerability = np.array([DEVICE_WEIGHT[d] for d in device]) + elderly
    vulnerability = np.where(backup, vulnerability / 2, vulnerability)
    return pd.DataFrame({
        "household_id": [f"H{i:06d}" for i in range(n)],
        "state": state,
        "region": [region_of(s) for s in state],
        "lat": lat.round(4),
        "lon": lon.round(4),
        "household_size": rng.choice([1, 2, 3, 4, 5, 6, 7], n,
                                     p=[0.10, 0.18, 0.22, 0.22, 0.14, 0.08, 0.06]),
        "has_elderly": elderly,
        "medical_device": device,
        "backup_power": backup,
        "vulnerability": vulnerability,
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2022-01-01", help="first day (Venezuela time)")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--households", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    cal = json.loads(CALIBRATION_PATH.read_text())
    rng = np.random.default_rng(args.seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    grid = generate_grid(cal, args.start, args.years, rng)
    grid.to_csv(OUT_DIR / "grid_hourly.csv.gz", index=False)
    households = generate_households(cal, args.households, rng)
    households.to_csv(OUT_DIR / "households.csv", index=False)

    # Check the synthetic outage shares against the real ones
    check = grid.groupby("state").agg(synthetic=("outage", "mean"),
                                      rationing=("outage_cause", lambda c: (c == "rationing").mean()))
    check["real"] = pd.Series({s: v["outage_hour_share"] for s, v in cal["states"].items()})
    print(check.round(4).sort_values("real", ascending=False).to_string())
    print(f"\nrationing active {np.mean(grid.rationing_level.to_numpy() > 0):.1%} of hours")
    print(f"Saved {len(grid):,} grid rows and {len(households):,} households to "
          f"{OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
