"""
serve.py - lets your app ask the model for risk levels over HTTP.

    pip install fastapi uvicorn
    OUTAGE_DATA_DIR=data OUTAGE_OUT_DIR=model_out uvicorn serve:app --host 0.0.0.0 --port 8000

(On Windows PowerShell:  $env:OUTAGE_DATA_DIR="data"; $env:OUTAGE_OUT_DIR="model_out"; uvicorn serve:app --port 8000)

Endpoints
  GET /risk            risk for every region (JSON list)
  GET /risk/{region}   one region, e.g. /risk/zulia
  GET /health          is the model loaded, how fresh is the data
  GET /docs            interactive documentation (open in a browser)

Results are recomputed from your CSV files at most every OUTAGE_REFRESH_SECONDS (default 600).
"""
import os
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from outage_core import OutageModel, build_dataset

DATA_DIR = os.path.expanduser(os.environ.get("OUTAGE_DATA_DIR", "data"))
OUT_DIR = os.path.expanduser(os.environ.get("OUTAGE_OUT_DIR", "model_out"))
REFRESH_SECONDS = int(os.environ.get("OUTAGE_REFRESH_SECONDS", "600"))

MODEL = OutageModel.load(OUT_DIR)            # loaded once, when the server starts
app = FastAPI(title="Venezuela power-outage risk")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

_cache = {"time": 0.0, "rows": [], "data_through": None}
_lock = threading.Lock()


def _refresh():
    df, _, _ = build_dataset(DATA_DIR, region_map=MODEL.region_map)
    out = MODEL.score_latest(df)
    through = out["timestamp"].max()
    out["timestamp"] = out["timestamp"].astype(str)
    _cache.update(rows=out.to_dict("records"), time=time.time(), data_through=str(through))


def _rows():
    with _lock:
        if not _cache["rows"] or time.time() - _cache["time"] > REFRESH_SECONDS:
            _refresh()
        return _cache["rows"]


@app.get("/risk")
def all_regions():
    return _rows()


@app.get("/risk/{region}")
def one_region(region: str):
    for row in _rows():
        if row["region"] == region.strip().lower():
            return row
    raise HTTPException(status_code=404, detail=f"unknown region '{region}'")


@app.get("/health")
def health():
    _rows()
    return {"status": "ok", "regions": len(_cache["rows"]), "data_through": _cache["data_through"],
            "horizon_rows": MODEL.horizon}
