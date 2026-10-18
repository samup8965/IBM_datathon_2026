# Outage Alert: 

**A real-time early-warning system for power cuts in Venezuela, running on IBM LinuxONE.**
For every state, Outage Alert forecasts the chance that a power cut starts in the next 24 hours, explains why, and ranks the households that should be checked on first: people on oxygen, dialysis, nebulisers or insulin.

Built from scratch during the **IBM Z Datathon 2026** · Theme 1: **Real-Time AI for Critical Decisions**

| | |
|---|---|
| Architecture and solution flow | [docs/architecture-and-solution-flow.pdf](docs/architecture-and-solution-flow.pdf) |
| Evidence from our LinuxONE run | [evidence/2026-10-17_2110/SUMMARY.md](evidence/2026-10-17_2110/SUMMARY.md) |

---

## Why we built it

In March 2019, during Venezuela's nationwide blackout, Vasco Villalobos died when the power cut stopped his oxygen concentrator. He was one of many. Venezuelans still lose power for hours with no warning, because the state utility publishes no outage schedules or outage data. People on medical devices only find out when it is already too late to prepare.

It was inspired from one of our team members being from that country and whose family endure these outages weekly if not daily.

## What it does

| | |
|---|---|
| **Detect** | Spots outages as they happen from abnormal drops in each state's internet connectivity |
| **Forecast** | Gives every state the chance an outage starts in the next 24 hours, rescored every 10 minutes |
| **Explain** | Shows the top factors behind each score, such as recent cuts or a dip in connectivity |
| **Prioritise** | Ranks households by outage risk × medical vulnerability |

### Theme alignment: Real-Time AI for Critical Decisions
- **Challenge 5, System Anomaly Detection:** we detect abnormal connectivity drops across 25 states every 10 minutes and forecast the next disruption 24 hours ahead.
- **Challenge 2, Healthcare Prioritisation:** we rank households so people who depend on medical power are reached first.

## How it works

```
IODA connectivity (25 states, every 10 min) ─┐
Open-Meteo weather (hourly)                  ├─► features ─► PyTorch ensemble + gradient boosting ─► blend ─► calibrated risk
                                             │      (21)          (scored on the Telum II NNPA)             + top factors
Synthetic households (calibrated) ───────────┴──────────────────────────────────────────────────────────► household priority
                                                                                                                  │
                                         FastAPI on IBM LinuxONE (port 8000) ◄──────── in-memory results, rescored every 10 min
                                                    │
                                     website + iPhone app (same API)
```

1. **Data.** IODA active-probing connectivity for all 25 states every 10 minutes (March 2022 onwards) and Open-Meteo hourly temperature, humidity and heat index.
2. **Labels we created.** No official outage data exists, so an outage is defined as connectivity **below 90% of the state's best level over the past 2 weeks** (a past-only window, so no future data leaks in). Our first definition, "below 80% of the usual level for that hour", hid chronic daily cuts and was replaced. States with fewer than 50 address blocks are flagged as low-signal, leaving **21 states**.
3. **Features (21 per state-hour).** Recent outages (1, 6 and 24 hours ago; counts over 24 hours and 7 days; hours since the last cut), connectivity (now, 24-hour low, ratio to 7-day median), heat index (now, 24-hour max, 72-hour mean, 24-hour change), hour and month (sine/cosine), weekend, and a learned embedding for each state.
4. **Hybrid model.** An ensemble of 5 PyTorch neural networks (state embeddings, class weighting, early stopping) blended with scikit-learn gradient boosting. The blend share is chosen on validation data, then calibrated into risk levels: Low, Moderate, Severe, Critical.
5. **Predicts onsets only.** The model learns from moments when the power is on, so it cannot score well by predicting that an outage simply continues.
6. **Serving.** An hourly job re-downloads the last 30 days, and FastAPI rescores every 10 minutes and serves cached results, so requests never wait on the model.

## Results on real data the model never saw

Trained on 2022–24, tested on **272,495 state-hours from 2025–26**.

| Approach | PR-AUC | ROC-AUC |
|---|---|---|
| Guessing (base rate) | 0.326 | 0.50 |
| Regional average | 0.407 | 0.60 |
| Same as yesterday | 0.561 | 0.76 |
| Recent outages (best simple rule) | 0.665 | 0.78 |
| **Outage Alert (blend)** | **0.765** | **0.858** |

| Risk level | Actual outage rate in the next 24 h |
|---|---|
| Low | 5.8% |
| Moderate | 12.9% |
| Severe | 33.0% |
| Critical | 75.9% |

Alerting at Severe or above catches **87%** of outages (precision 0.55).

**How we got here:** a forecaster trained only on our simulated grid lost to the simple rules (PR-AUC 0.089 vs 0.114), because simulated outages had no warning signs. Training on real data beat them (0.140 vs 0.114 on our first label), and the new label plus the hybrid blend gives the final 0.765 vs 0.665.

## Built on IBM LinuxONE

| Capability | How we used it |
|---|---|
| **IBM z17** | LinuxONE Community Cloud instance, machine type 9175, z/VM, Ubuntu on s390x |
| **Telum II AI accelerator** | The forecaster's neural networks score on the NNPA (`/health` reports `scoring_device: nnpa`) |
| **Containers** | The pipeline runs in IBM's AI/ML Docker image (Python 3.12, PyTorch 2.11 with NNPA support, scikit-learn 1.9) |
| **Compute** | Data refresh, training and scoring all run on the z17 |
| **Security** | SSH keys, a custom Jupyter token, ports 38888 (Jupyter) and 8000 (API) opened in the firewall, no external AI services, aggregated state-level data only |
| **Open source** | PyTorch, scikit-learn, pandas, NumPy, FastAPI, uvicorn |

**Telum II benchmarks on our z17** (from `evidence/.../SUMMARY.md`):

| Workload | CPU | NNPA | Speed-up |
|---|---|---|---|
| Our forecaster, 50,000 state-hours | 102.4 ms | 78.6 ms | **1.3×** |
| Test network (MLP), batch of 4,096 | 1.49 ms | 0.14 ms | **10.6×** |
| LSTM, batch of 4,096 | 739 ms | 768 ms | 0.96× |

The LSTM got no speed-up, so we kept the feed-forward ensemble. TensorFlow's zDNN plugin was not active in our container, so we used PyTorch, which reached the NNPA directly. NNPA results differ from the CPU's by at most 0.0013, as expected from the accelerator's 16-bit arithmetic, which shows the NNPA did the work.

## What is real and what is simulated

| | Data | Status |
|---|---|---|
| **Forecaster** | Real IODA connectivity and Open-Meteo weather | Live |
| **Household priority** | 5,000 **synthetic** households (real medical data is private), multiplied by the real forecaster risk | Live |
| **Simulated grid** (reservoir, plant failures, rationing) | Synthetic, calibrated on real 2022–24 patterns | Built and tested; not used for forecasts. Next: what-if planning |

## Run it

**On LinuxONE** (inside IBM's AI/ML container):
```bash
bash scripts/run_on_linuxone.sh       # generate → export → train → predict, about 6 minutes
bash scripts/serve_on_linuxone.sh     # hourly data refresh + website and API on port 8000
bash scripts/collect_evidence.sh      # writes evidence/<date>/SUMMARY.md
```

**On a laptop:**
```bash
uv sync                               # package versions pinned to match the server
uv run python scripts/download_ioda.py
uv run python scripts/download_weather.py
```
Then follow the same steps as `scripts/run_on_linuxone.sh`.

### API

| Endpoint | Returns |
|---|---|
| `GET /` | The Outage Alert website |
| `GET /health` | Model status, scoring device (`nnpa` = Telum), data freshness |
| `GET /v1/regions` | Every state for the map (ISO codes, e.g. `VE-S` = Táchira) |
| `GET /v1/prediction?region=VE-A` | One state, in the app's format |
| `GET /v1/households?region=VE-S` | Households to check on first |
| `GET /v1/households/summary` | Medical-dependent households and priority tiers per state |
| `GET /docs` | Interactive API documentation |

## Repository

| Path | What it is |
|---|---|
| `scripts/` | Data download, calibration, simulation, export, training, prediction, LinuxONE run, serve and evidence scripts |
| `src/` | Features, model, households, regions, serving, Telum benchmark |
| `app/api.py` | FastAPI service: website + `/v1` API |
| `Outage-Alert-Website/` | Website (built into `dist/`) |
| `OutageAlert/` | iPhone app (SwiftUI) |
| `notebooks/` | Exploration, training and LinuxONE demo notebooks |
| `docs/` | Architecture and solution flow |
| `evidence/` | Output from our runs on the z17 |

## Responsible AI and limits
- Every score shows its top factors; risk levels are calibrated on held-out data.
- No personal data is used: households are synthetic and all signals are state-level.
- Internet drops are a proxy for power cuts; forecasts are per state, not per street, and less accurate where outages are rare.
- The system advises people to prepare. It never switches anything off.

## What comes next
- IBM Granite on LinuxONE for plain-language Spanish advice (generative + predictive AI)
- SMS and WhatsApp alerts for people without the app
- Real reservoir and rainfall data, and what-if planning for clinics and NGOs
- Cross-checking outages against NASA night-lights imagery

## Data sources and credits
- **IODA**, Internet Outage Detection and Analysis, Georgia Tech: connectivity signals (Copyright Georgia Tech Research Corporation; raw data is not redistributed in this repo)
- **Open-Meteo**: weather data (CC BY 4.0)
- **geoBoundaries**: Venezuela state boundaries (CC BY 3.0 IGO)
- News reports cited in our deck: El Cooperante, Reuters, Euronews, AFP, Global Galicia, El Siglo
