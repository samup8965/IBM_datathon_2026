#!/usr/bin/env bash
# Collect evidence that the pipeline ran on LinuxONE (IBM z17, Telum NNPA).
# Run inside the Jupyter container after scripts/run_on_linuxone.sh:
#
#   cd ~/shared/IBM_datathon_2026
#   bash scripts/collect_evidence.sh
#
# Writes evidence/<UTC date>/ with machine details, package versions, the run logs,
# results, a timing of the real forecaster on the NNPA vs the CPU, and SUMMARY.md
# (the one page to screenshot). The folder is small text, so it can be committed.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
out="evidence/$(date -u +%Y-%m-%d_%H%M)"
mkdir -p "$out"
echo "Collecting evidence in $out ..."

# --- machine: which computer this ran on
{
    echo "date (UTC): $(date -u)"
    uname -a
    grep -m1 'machine' /proc/cpuinfo || true
    # On IBM Z, /proc/sysinfo names the machine type (9175 = z17) and the partition
    if [ -r /proc/sysinfo ]; then
        grep -E '^(Manufacturer|Type|Model|LPAR Name|LPAR CPUs Total|VM00 Name|VM00 Control Program):' \
            /proc/sysinfo || true
    fi
} > "$out/machine.txt"
lscpu > "$out/lscpu.txt" 2>/dev/null || true

# --- software: Python and the packages that matter, incl. the Telum (NNPA) plugin
{
    python --version
    pip list 2>/dev/null | grep -iE 'torch|nnpa|zdnn|tensorflow|scikit-learn|xgboost|pandas|numpy' || true
} > "$out/packages.txt"
git log -1 --format='commit %H%nauthor %an, %ad%n%s' > "$out/git_commit.txt" 2>/dev/null || true

# --- the run itself: logs and results from scripts/run_on_linuxone.sh
cp logs/*.log "$out/" 2>/dev/null || true
for f in training_report.txt risk_latest.json feature_importance.csv versions.txt; do
    cp "models/$f" "$out/" 2>/dev/null || true
done
sha256sum models/*.pt models/*.joblib > "$out/model_files.sha256" 2>/dev/null || true

# --- the real forecaster scored on the NNPA and on the CPU
echo "Timing the trained forecaster on the NNPA vs the CPU ..."
python - > "$out/telum_forecaster.txt" 2>&1 <<'EOF'
import time

import numpy as np

from src.features import build_dataset
from src.model import OutageModel

model = OutageModel.load("models")
df, _, _ = build_dataset("data/model_input/real", region_map=model.region_map)
rows = df[df["label"].notna()].tail(50_000)
X, r = model.prepare(rows)
dev = next(model.nn.models[0].parameters()).device


def timed(fn, repeats=7):
    """Fastest of several calls, in ms, so warm-up effects don't favour either device."""
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - start)
    return min(times) * 1000, out


ms_dev, p_dev = timed(lambda: model.nn.predict(X, r))
for net in model.nn.models:
    net.to("cpu")
ms_cpu, p_cpu = timed(lambda: model.nn.predict(X, r))
diff = float(np.max(np.abs(p_dev - p_cpu)))
print(f"\nTrained forecaster: {len(model.nn.models)} neural networks scoring {len(X):,} state-hours")
print(f"  on {dev}: {ms_dev:8.1f} ms")
print(f"  on cpu : {ms_cpu:8.1f} ms   ({ms_cpu / ms_dev:.1f}x)")
print(f"  largest difference between the two: {diff:.2e} "
      f"({'non-zero: the NNPA did the work' if diff > 0 else 'identical: no NNPA used'})")
EOF

# --- the small CPU-vs-NNPA benchmark
echo "Running the CPU vs NNPA benchmark ..."
python -m src.benchmark --out "$out/benchmark.json" > "$out/benchmark.txt" 2>&1 || true

# --- one page to screenshot
{
    echo "# Evidence: Venezuela outage forecaster on IBM LinuxONE"
    echo
    echo "Collected $(date -u '+%Y-%m-%d %H:%M UTC') from \`$out\`"
    echo
    echo "## Machine"
    echo '```'; cat "$out/machine.txt"; echo '```'
    echo
    echo "## Code version"
    echo '```'; cat "$out/git_commit.txt" 2>/dev/null; echo '```'
    echo
    echo "## Telum NNPA: the trained forecaster"
    echo '```'; grep -A4 '^Trained forecaster' "$out/telum_forecaster.txt" || tail -5 "$out/telum_forecaster.txt"; echo '```'
    echo
    echo "## Telum NNPA: benchmark"
    echo '```'; grep -E 'Machine|==|NNPA used|on (cpu|nnpa)' "$out/benchmark.txt" || true; echo '```'
    echo
    echo "## Results on real 2025-26 outages (trained on real 2022-24, on this machine)"
    echo '```'
    sed -n '/^Model comparison/,/^Per region/p' "$out/training_report.txt" | grep -v '^Per region'
    echo '```'
    echo
    echo "## Prediction run"
    echo '```'; grep -E 'score on|Data is current' "$out/predict.log" || true; echo '```'
} > "$out/SUMMARY.md"

echo
cat "$out/SUMMARY.md"
echo
echo "Saved $out/  (screenshot SUMMARY.md above; copy the folder to your laptop to commit it)"
