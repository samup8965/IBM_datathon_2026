"""households.py - who to check on first: households ranked by outage risk x vulnerability.

    priority = the state's outage risk (from the model; 1.0 while an outage is under way)
               x the household's vulnerability (scripts/generate_data.py: medical device
                 1 to 3, +1 for an elderly member, halved when there is backup power)

The households are SYNTHETIC (data/synthetic/households.csv): no public registry of
medically dependent households exists, and a real one would be private, opt-in data. They
show how a clinic or civil-protection group would use the ranking with its own list.
"""
import json
from pathlib import Path

import pandas as pd

from src.regions import REGIONS

ROOT = Path(__file__).resolve().parents[1]
HOUSEHOLDS_PATH = ROOT / "data" / "synthetic" / "households.csv"

# A tier starts at this priority. Oxygen (3) with no backup at a Critical-level risk of
# 0.76 scores 2.3 = urgent; oxygen with backup power during an outage (risk 1.0) scores
# 1.5 = high; an elderly member alone during an outage scores 1.0 = watch.
TIERS = [(2.0, "urgent"), (1.5, "high"), (0.5, "watch"), (0.0, "low")]
DEVICE_TEXT = {
    "home_dialysis": "home dialysis",
    "oxygen_concentrator": "oxygen concentrator",
    "powered_wheelchair_or_bed": "powered wheelchair or bed",
    "refrigerated_medicine": "refrigerated medicine",
}
FIELDS = ["household_id", "region_id", "lat", "lon", "household_size", "has_elderly",
          "medical_device", "backup_power", "vulnerability", "priority", "tier", "reasons"]


def load_households(path=HOUSEHOLDS_PATH):
    households = pd.read_csv(path)
    households["region_id"] = households.state.str.strip().str.lower().map(lambda k: REGIONS[k][0])
    return households


def _tier(priority):
    if pd.isna(priority):
        return "unknown"  # the state has no forecast
    return next(name for floor, name in TIERS if priority >= floor)


def _reasons(row):
    reasons = []
    if row.medical_device in DEVICE_TEXT:
        reasons.append(DEVICE_TEXT[row.medical_device])
    if row.has_elderly:
        reasons.append("elderly member")
    if row.vulnerability > 0:
        reasons.append("has backup power" if row.backup_power else "no backup power")
    if row.outage_in_progress is True:
        reasons.append("outage in progress")
    elif isinstance(row.risk_level, str):
        reasons.append(f"{row.risk_level} outage risk")
    return reasons


def rank(households, snapshot):
    """Each household with its state's current risk, priority, tier and reasons; highest first."""
    risk = pd.DataFrame([{
        "region_id": s["region_id"],
        "risk": 1.0 if s.get("outage_in_progress") else s.get("risk_probability"),
        "risk_level": s.get("risk_level"),
        "outage_in_progress": s.get("outage_in_progress"),
    } for s in snapshot])
    ranked = households.merge(risk, on="region_id", how="left")
    ranked["priority"] = (pd.to_numeric(ranked.risk) * ranked.vulnerability).round(3)
    ranked["tier"] = ranked.priority.map(_tier)
    ranked["reasons"] = ranked.apply(_reasons, axis=1)
    return ranked.sort_values(["priority", "vulnerability"], ascending=False, na_position="last")


def records(ranked):
    """JSON-ready dicts (plain Python types)."""
    return json.loads(ranked[FIELDS].to_json(orient="records"))


def summary(ranked, snapshot):
    """Per state: how many households, how many depend on powered medical care, and how
    many fall in each priority tier right now."""
    rows = []
    for s in snapshot:
        h = ranked[ranked.region_id == s["region_id"]]
        tiers = h.tier.value_counts()
        rows.append({
            "region_id": s["region_id"],
            "name": s["name"],
            "risk_level": s.get("risk_level"),
            "outage_in_progress": s.get("outage_in_progress"),
            "households": int(len(h)),
            "medical_dependent": int((h.medical_device != "none").sum()),
            **{tier: int(tiers.get(tier, 0)) for _, tier in TIERS},
        })
    return sorted(rows, key=lambda r: (r["urgent"], r["high"]), reverse=True)
