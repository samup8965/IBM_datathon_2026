#!/usr/bin/env bash
# Run the forecaster pipeline on the LinuxONE server, inside the Jupyter container.
#
#   cd ~/shared/IBM_datathon_2026
#   bash scripts/run_on_linuxone.sh
#
# Needs data/raw/ (copied from a laptop with scp, or re-downloaded with
# scripts/download_ioda.py and scripts/download_weather.py).
# Each step's output is saved in logs/ for screenshots; the model and
# risk_latest.json end up in models/.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"   # lets the scripts import src/ without installing the repo
mkdir -p logs

stamp() { date '+%Y-%m-%d %H:%M:%S'; }
run() {
    local name=$1; shift
    echo "[$(stamp)] $name ..."
    "$@" 2>&1 | tee "logs/$name.log"
}

{
    echo "[$(stamp)] machine: $(uname -m) | $(grep -m1 'machine' /proc/cpuinfo || echo 'unknown cpu')"
    python --version
} | tee logs/machine.log

run generate python scripts/generate_data.py
run export   python scripts/export_model_input.py
run train    python scripts/train.py --data-dir data/model_input/real_train \
                 --test-dir data/model_input/real --out-dir models
run predict  python scripts/predict.py --data-dir data/model_input/real --out-dir models
echo "[$(stamp)] done. Logs in logs/, model and risk_latest.json in models/"
