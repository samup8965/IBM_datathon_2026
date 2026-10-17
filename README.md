# IBM_datathon_2026
IBM Venezuela idea

# Venezuela power-outage risk model

For every region, the model estimates **the chance that an outage starts within the next 24 hours**
(configurable) and turns that into a risk level: **Low / Moderate / Severe / Critical**
(or "Outage in progress"). It combines a **PyTorch neural-network ensemble** with a
**gradient-boosting model** and uses all five datasets: outage history, temperature, heat index,
internet connectivity and reservoir height.

## The files

| File | What it is | Do you run it? |
|---|---|---|
| `outage_config.py` | Where your files are and what their columns are called | **Edit it** |
| `train.py` | Teaches the model from your data | Run once (re-run with much more data) |
| `predict.py` | Current risk for every region -> CSV + JSON | Run whenever your data updates |
| `serve.py` | Web service so your app can ask for risk levels | Run to power the app |
| `make_sample_data.py` | Makes FAKE data to test everything works | Run once at the start |
| `outage_core.py` | The shared machinery | Don't edit |
| `requirements.txt` | Python packages needed | `pip install -r requirements.txt` |

## 1. Install (once)

```
pip install -r requirements.txt
```
(`fastapi` and `uvicorn` in that file are only needed for `serve.py`.)

## 2. Check everything works with fake data (5 minutes)

```
python make_sample_data.py --out sample_data
python train.py   --data-dir sample_data --out-dir sample_model
python predict.py --data-dir sample_data --out-dir sample_model
```
If this runs, your installation is fine. The numbers are invented - ignore them.

## 3. Prepare your real data

Put your CSVs in one folder (e.g. `data/`). Each needs a time column; regional files need a region column.

| File | Columns (default names) | Notes |
|---|---|---|
| `history.csv` | `timestamp, region, outage` | one row per region per time step; outage is 0/1; evenly spaced (e.g. hourly) |
| `temperature.csv` | `timestamp, region, temperature` | any frequency |
| `heat_index.csv` | `timestamp, region, heat_index` | any frequency |
| `connectivity.csv` | `timestamp, region, connectivity` | any frequency |
| `reservoir.csv` | `timestamp, height` | country-level: no region column |

- If your column or file names differ, change them in `outage_config.py` (`path`, `time`, `region`, `cols`).
- Region names are matched ignoring capitals and spaces ("Zulia" = " zulia"), but spelling must agree across files.
- If your history is a list of outages with start/end times, use `"format": "events"` (see the comments in the config).
- **`history.csv` defines the rows.** Its last timestamp is treated as "now", so keep it up to date.
- Other files may have different frequencies: each row uses the latest reading at or before its time.

## 4. Train

```
python train.py --data-dir data --out-dir model_out
```
It prints (and saves to `model_out/training_report.txt`) a report. Read it before trusting the model:

1. **"matched %" lines** should be close to 100%. Low = region names or dates don't line up between files.
2. **Model comparison** - the final model should beat "base rate" and "recent outages". If it doesn't, the data has little signal for the chosen horizon.
3. **"Do the risk levels mean something?"** - the actual outage rate must rise from Low to Critical.
4. **Per region** - regions with very few outages (`+=` small) are unreliable.
5. **What drives the predictions** - the top features (also in `feature_importance.csv`); good for your presentation.

Test data is the newest 15% of the timeline and is never used for training or tuning, so those numbers are honest.

## 5. Get current risk levels

```
python predict.py --data-dir data --out-dir model_out
```
Writes `model_out/risk_latest.csv` and `risk_latest.json`. Each region has:

| Field | Meaning |
|---|---|
| `risk_probability` | calibrated chance an outage starts within the horizon (0-1) |
| `risk_level` | Low / Moderate / Severe / Critical, or "Outage in progress" |
| `confidence` | High / Medium / Low, from how many outages that region has in its history |
| `history_events` | number of separate outages seen for that region |
| `top_factors` | the features pushing this region's risk up the most (approximate) |
| `timestamp` | the moment the risk refers to |

Risk levels compare today with history: Critical = riskier than about 90% of past situations,
Severe about 70%, Moderate about 40% (adjust `TIER_SHARES` in the config).

## 6. Connect your app

Option A (simplest): your app reads `risk_latest.json`. Re-run `predict.py` on a schedule (e.g. hourly) after your data updates.

Option B: a web service.
```
OUTAGE_DATA_DIR=data OUTAGE_OUT_DIR=model_out uvicorn serve:app --host 0.0.0.0 --port 8000
```
(Windows PowerShell: `$env:OUTAGE_DATA_DIR="data"; $env:OUTAGE_OUT_DIR="model_out"; uvicorn serve:app --port 8000`)

- `GET /risk` all regions - `GET /risk/zulia` one region - `GET /health` status - `GET /docs` interactive docs

```js
const regions = await (await fetch("http://localhost:8000/risk")).json();
```
```python
import requests
regions = requests.get("http://localhost:8000/risk").json()
```

## Good practice

- Show the **level and the probability together**, and say "chance of an outage starting in the next 24 hours".
- Show or hint at `confidence`: Low-confidence regions have little outage history.
- Show `top_factors` as "why" - but call them contributing factors, not proven causes.
- Re-run `train.py` when you have substantially more data (weeks or months), not for each update.

## Troubleshooting

| Message | Fix |
|---|---|
| `File not found` | wrong `--data-dir`, or `path` in the config |
| `missing column(s)` | the names in the config don't match the CSV headers |
| `matched very few rows` | region spellings or date ranges don't overlap between files |
| `rows are not evenly spaced` | set `"regularize_freq": "h"` in the config |
| `split has no outages` | not enough data/outages: use a longer history or a shorter horizon |
| `No trained model found` | run `train.py` first, and use the same `--out-dir` |
| `PyTorch is required` | `pip install torch` |
