"""benchmark.py - evidence that our networks run on the Telum AI accelerator (NNPA).

Run it ON THE LINUXONE SERVER, from the repo root:

    python -m src.benchmark
    python -m src.benchmark --out models/benchmark.json

For PyTorch (torch_nnpa) and TensorFlow (ibm-zdnn-plugin) it runs the same two small
networks on the CPU and on the NNPA:
  - mlp : a plain network like the one in src/model.py
  - lstm: an LSTM reading 48-hour windows, as planned for the forecaster

and reports the time per batch and how far the NNPA answers are from the CPU answers.

How to read it: the NNPA computes in a 16-bit number format, so its answers differ from
the CPU's by a tiny amount. A small non-zero difference means the NNPA did the work.
Exactly zero difference means the work quietly fell back to the CPU. On a laptop it
simply reports that no NNPA was found.
"""
import argparse
import copy
import json
import platform
import time
from pathlib import Path

import numpy as np

BATCH = 4096       # rows scored at once
TAB_FEATURES = 30  # inputs per row for the plain network
SEQ_LEN, SEQ_FEATURES = 48, 6  # 48 hours x 6 readings for the LSTM
REPEATS = 20


def machine_info():
    info = {"python": platform.python_version(), "arch": platform.machine()}
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            # On IBM Z this line names the machine type, e.g. which z generation it is
            if line.startswith("processor 0:") or line.startswith("machine"):
                info["cpu"] = line.strip()
                break
    return info


def timed(fn):
    """Milliseconds per call (after one warm-up call) and the last output."""
    fn()
    start = time.perf_counter()
    for _ in range(REPEATS):
        out = fn()
    return (time.perf_counter() - start) / REPEATS * 1000, out


def compare(results, name):
    """Add the CPU vs NNPA difference and speed-up for one network."""
    cpu, nnpa = results.get(f"{name}_cpu", {}), results.get(f"{name}_nnpa", {})
    if "out" not in cpu or "out" not in nnpa:
        return
    diff = float(np.max(np.abs(cpu["out"] - nnpa["out"])))
    results[f"{name}_check"] = {
        "max_abs_difference": diff,
        "nnpa_did_the_work": diff > 0,
        "speedup_vs_cpu": round(cpu["ms_per_batch"] / nnpa["ms_per_batch"], 2),
    }


def bench_torch(x_tab, x_seq):
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        return {"error": "torch not installed"}
    results = {"version": torch.__version__}
    try:
        import torch_nnpa  # registers the NNPA device with PyTorch
        results["torch_nnpa"] = getattr(torch_nnpa, "__version__", "installed")
    except ImportError:
        torch_nnpa = None
        results["torch_nnpa"] = None

    # The device name torch_nnpa registers; check the lab docs if neither works
    nnpa_device = None
    for candidate in ["nnpa", "privateuseone"]:
        try:
            torch.empty(1, device=candidate)
            nnpa_device = candidate
            break
        except Exception:
            continue
    results["nnpa_device"] = nnpa_device
    if torch_nnpa is not None and nnpa_device is None:
        results["hint"] = ("torch_nnpa imported but no device found; its attributes are: "
                           + ", ".join(a for a in dir(torch_nnpa) if not a.startswith("_")))

    class LSTMNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(SEQ_FEATURES, 64, batch_first=True)
            self.head = nn.Linear(64, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1])

    torch.manual_seed(0)
    networks = {
        "mlp": (nn.Sequential(nn.Linear(TAB_FEATURES, 64), nn.ReLU(), nn.Linear(64, 32),
                              nn.ReLU(), nn.Linear(32, 1)), x_tab),
        "lstm": (LSTMNet(), x_seq),
    }
    devices = [("cpu", "cpu")] + ([("nnpa", nnpa_device)] if nnpa_device else [])
    for name, (net, x) in networks.items():
        for label, device in devices:
            try:
                model = copy.deepcopy(net).eval().to(device)
                xd = torch.from_numpy(x).to(device)
                with torch.no_grad():
                    ms, out = timed(lambda: model(xd).to("cpu"))
                results[f"{name}_{label}"] = {"ms_per_batch": round(ms, 2),
                                              "out": out.numpy().ravel()}
            except Exception as e:
                results[f"{name}_{label}"] = {"error": f"{type(e).__name__}: {e}"[:300]}
        compare(results, name)
    return results


def bench_tensorflow(x_tab, x_seq):
    try:
        import tensorflow as tf  # the ibm-zdnn-plugin registers the NNPA when this loads
    except ImportError:
        return {"error": "tensorflow not installed"}
    results = {"version": tf.__version__}
    physical = tf.config.list_physical_devices()
    results["devices"] = [d.device_type for d in physical]
    nnpa = next((d for d in physical if "NNPA" in d.device_type.upper()), None)
    results["nnpa_device"] = nnpa.device_type if nnpa else None

    tf.keras.utils.set_random_seed(0)
    keras = tf.keras
    networks = {
        "mlp": (keras.Sequential([keras.Input((TAB_FEATURES,)), keras.layers.Dense(64, "relu"),
                                  keras.layers.Dense(32, "relu"), keras.layers.Dense(1)]), x_tab),
        "lstm": (keras.Sequential([keras.Input((SEQ_LEN, SEQ_FEATURES)),
                                   keras.layers.LSTM(64), keras.layers.Dense(1)]), x_seq),
    }
    devices = [("cpu", "/CPU:0")] + ([("nnpa", f"/device:{nnpa.device_type}:0")] if nnpa else [])
    for name, (model, x) in networks.items():
        for label, device in devices:
            try:
                with tf.device(device):
                    xd = tf.constant(x)
                    ms, out = timed(lambda: model(xd, training=False).numpy())
                results[f"{name}_{label}"] = {"ms_per_batch": round(ms, 2), "out": out.ravel()}
            except Exception as e:
                results[f"{name}_{label}"] = {"error": f"{type(e).__name__}: {e}"[:300]}
        compare(results, name)
    return results


def report(all_results):
    for framework, res in all_results.items():
        if framework == "machine":
            continue
        print(f"\n== {framework} {res.get('version', '')} | NNPA device: {res.get('nnpa_device')}")
        for key in ("error", "hint", "torch_nnpa", "devices"):
            if key in res:
                print(f"   {key}: {res[key]}")
        for name in ("mlp", "lstm"):
            for label in ("cpu", "nnpa"):
                r = res.get(f"{name}_{label}")
                if r:
                    print(f"   {name:<4} on {label:<4}: "
                          + (f"{r['ms_per_batch']:8.2f} ms per batch of {BATCH}"
                             if "ms_per_batch" in r else r["error"]))
            check = res.get(f"{name}_check")
            if check:
                verdict = ("YES - answers differ slightly, as expected from NNPA's 16-bit math"
                           if check["nnpa_did_the_work"] else
                           "NO - identical answers, the work fell back to the CPU")
                print(f"   {name:<4} NNPA used? {verdict} (max diff "
                      f"{check['max_abs_difference']:.2e}, {check['speedup_vs_cpu']}x vs CPU)")


def main():
    parser = argparse.ArgumentParser(description="CPU vs Telum NNPA benchmark")
    parser.add_argument("--out", type=Path, default=None, help="also save results as JSON")
    args = parser.parse_args()

    rng = np.random.default_rng(0)
    x_tab = rng.standard_normal((BATCH, TAB_FEATURES)).astype("float32")
    x_seq = rng.standard_normal((BATCH, SEQ_LEN, SEQ_FEATURES)).astype("float32")

    results = {"machine": machine_info(),
               "pytorch": bench_torch(x_tab, x_seq),
               "tensorflow": bench_tensorflow(x_tab, x_seq)}
    print("Machine:", results["machine"])
    report(results)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        clean = {fw: {k: ({kk: vv for kk, vv in v.items() if kk != "out"} if isinstance(v, dict) else v)
                      for k, v in res.items()}
                 for fw, res in results.items()}
        args.out.write_text(json.dumps(clean, indent=2, default=str))
        print(f"\nSaved {args.out}")


if __name__ == "__main__":
    main()
