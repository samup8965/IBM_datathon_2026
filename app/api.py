"""
api.py - the backend for Outage Alert. Run from the repo root:

    uv run uvicorn app.api:app --host 0.0.0.0 --port 8000
    (on the LinuxONE container:  PYTHONPATH=$PWD uvicorn app.api:app --host 0.0.0.0 --port 8000)

It scores every state with the trained model and keeps the results in memory; requests are
answered from there, so they never wait for the model. Scores are recomputed in the
background every OUTAGE_REFRESH_SECONDS (default 600) from the CSVs in OUTAGE_DATA_DIR
(default: data/model_input/live, kept fresh by scripts/refresh.py; else data/model_input/real),
so fresh data is picked up without a restart.

Endpoints
  GET /                              the Outage Alert website (Outage-Alert-Website/dist)
  GET /health                        model loaded?, scoring device (nnpa = Telum), data freshness
  GET /v1/regions                    every state, for the map (ISO codes, e.g. VE-S = Táchira)
  GET /v1/prediction?region=VE-A     one state, in the apps' Prediction format
  GET /v1/households?region=VE-S     who to check on first: households by risk x vulnerability
  GET /v1/households/summary         per state: medical-dependent households and priority tiers
  GET /docs                          interactive documentation

The households are synthetic (see src/households.py).
"""
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src import households as hh
from src.model import OutageModel
from src.regions import BY_ISO
from src.serving import build_snapshot

ROOT = Path(__file__).resolve().parents[1]
# Live data from scripts/refresh.py when it exists, else the real test period
DEFAULT_DATA_DIR = "data/model_input/live" if (ROOT / "data/model_input/live").is_dir() else "data/model_input/real"
DATA_DIR = os.path.expanduser(os.environ.get("OUTAGE_DATA_DIR", DEFAULT_DATA_DIR))
OUT_DIR = os.path.expanduser(os.environ.get("OUTAGE_OUT_DIR", "models"))
REFRESH_SECONDS = int(os.environ.get("OUTAGE_REFRESH_SECONDS", "600"))
WEBSITE_DIR = ROOT / "Outage-Alert-Website" / "dist"

MODEL = OutageModel.load(OUT_DIR)            # loaded once, when the server starts
HOUSEHOLDS = hh.load_households() if hh.HOUSEHOLDS_PATH.exists() else None
app = FastAPI(title="Outage Alert: Venezuela power-outage risk", version="1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

_state = {"regions": [], "by_id": {}, "ranked": None, "household_summary": [],
          "computed_at": None, "last_error": None}
_lock = threading.Lock()


def _refresh():
    """Score every state and re-rank households; on failure keep the last good results."""
    try:
        regions = build_snapshot(MODEL, DATA_DIR)
        ranked = hh.rank(HOUSEHOLDS, regions) if HOUSEHOLDS is not None else None
    except Exception as e:
        _state["last_error"] = f"{type(e).__name__}: {e}"
        print(f"refresh failed, keeping previous results: {_state['last_error']}")
        return
    with _lock:
        _state.update(regions=regions, by_id={r["region_id"]: r for r in regions}, ranked=ranked,
                      household_summary=hh.summary(ranked, regions) if ranked is not None else [],
                      computed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      last_error=None)


def _refresh_forever():
    while True:
        time.sleep(REFRESH_SECONDS)
        _refresh()


_refresh()                                   # first results before serving any request
threading.Thread(target=_refresh_forever, daemon=True).start()


@app.get("/health")
def health():
    regions = _state["regions"]
    scored = [r for r in regions if r.get("status") == "ok"]
    return {
        "status": "ok" if scored else "no_data",
        "scoring_device": MODEL.nn.device,   # "nnpa" = Telum AI accelerator
        "regions_scored": len(scored),
        "regions_total": len(regions),
        "computed_at": _state["computed_at"],
        "data_through": max((r["data_through"] for r in scored), default=None),
        "data_dir": DATA_DIR,
        "horizon_hours": MODEL.horizon,
        "refresh_seconds": REFRESH_SECONDS,
        "last_error": _state["last_error"],
    }


@app.get("/v1/regions")
def regions():
    """Every state, including those without enough data (status 'insufficient_data')."""
    return _state["regions"]


@app.get("/v1/prediction")
def prediction(region: str = Query(..., description="ISO code, e.g. VE-A for Distrito Capital")):
    code = region.strip().upper()
    if code not in BY_ISO:
        raise HTTPException(status_code=404, detail=f"unknown region '{region}' (use an ISO code like VE-A)")
    record = _state["by_id"].get(code)
    if record is None or record.get("status") != "ok":
        raise HTTPException(status_code=404, detail=f"not enough data to forecast {BY_ISO[code][1]}")
    return record


def _ranked():
    if _state["ranked"] is None:
        raise HTTPException(status_code=503, detail="no household data (run scripts/generate_data.py)")
    return _state["ranked"]


@app.get("/v1/households/summary")
def household_summary():
    """Per state, most urgent first: households, medical-dependent households, and how many
    fall in each priority tier (urgent / high / watch / low) right now. Synthetic households."""
    _ranked()
    return {"synthetic": True, "regions": _state["household_summary"]}


@app.get("/v1/households")
def households(region: str | None = Query(None, description="ISO code, e.g. VE-S; all states if left out"),
               tier: str | None = Query(None, description="only this tier: urgent, high, watch or low"),
               limit: int = Query(50, ge=1, le=500)):
    """Households ranked by priority = state outage risk x vulnerability, highest first,
    each with its reasons. Synthetic households."""
    ranked = _ranked()
    if region:
        code = region.strip().upper()
        if code not in BY_ISO:
            raise HTTPException(status_code=404, detail=f"unknown region '{region}' (use an ISO code like VE-S)")
        ranked = ranked[ranked.region_id == code]
    if tier:
        ranked = ranked[ranked.tier == tier.strip().lower()]
    return {"synthetic": True, "region": region, "tier": tier, "total": int(len(ranked)),
            "households": hh.records(ranked.head(limit))}


# The website last, so the API routes above take precedence over its files
if WEBSITE_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEBSITE_DIR, html=True), name="website")
