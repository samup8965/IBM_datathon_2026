#!/usr/bin/env bash
# Start the live backend on LinuxONE, inside the Jupyter container:
#
#   cd ~/shared/IBM_datathon_2026
#   bash scripts/serve_on_linuxone.sh
#
# 1. fetches the latest IODA + weather data and rebuilds the live inputs (about a minute)
# 2. keeps refreshing them every hour in the background (logs/refresh.log)
# 3. serves the API and the website on port 8000 (Ctrl+C stops both)
#
# Needs a trained model in models/ (scripts/run_on_linuxone.sh) and fastapi + uvicorn.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"   # lets the scripts import src/ without installing the repo
mkdir -p logs

python scripts/refresh.py 2>&1 | tee -a logs/refresh.log
python scripts/refresh.py --every 60 --wait >> logs/refresh.log 2>&1 &
refresher=$!
trap 'kill $refresher 2>/dev/null' EXIT
echo "hourly refresh running in the background (pid $refresher, log: logs/refresh.log)"

export OUTAGE_DATA_DIR=data/model_input/live
uvicorn app.api:app --host 0.0.0.0 --port 8000 2>&1 | tee -a logs/api.log
