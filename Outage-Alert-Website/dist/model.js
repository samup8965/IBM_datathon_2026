export const levels = ["Low", "Moderate", "Severe", "Critical"];
export const percentages = [12, 34, 68, 89];
export const statuses = [
  "Grid conditions currently appear stable.",
  "Grid pressure is rising. A little preparation now can help.",
  "Grid conditions are deteriorating. Prepare essential backup power.",
  "Outage risk is critical. Prepare for possible imminent power loss.",
];
const actions = {
  household: [
    ["No urgent action needed", "Keep devices normally charged"],
    ["Consider charging phone and laptop", "Charge power bank", "Save important work"],
    [
      "Charge essential devices now",
      "Prepare backup lighting",
      "Save computer work",
      "Minimise opening refrigerator/freezer",
    ],
    [
      "Prepare for imminent outage",
      "Fully charge essential devices",
      "Ensure power banks are ready",
      "Prepare backup lighting",
      "Protect refrigerated essentials",
      "Save all important work immediately",
    ],
  ],
  medical: [
    ["Ensure backup battery is available"],
    ["Begin charging backup battery", "Check backup power source"],
    [
      "Fully charge medical equipment backup",
      "Confirm alternative power source",
      "Notify caregiver/support person if needed",
    ],
    [
      "Prepare for possible imminent power loss",
      "Switch or prepare backup power immediately",
      "Confirm remaining battery duration",
      "Contact caregiver/support if backup time may be insufficient",
    ],
  ],
};
const offsets = {
  A: 0,
  B: 1,
  C: 0,
  D: 1,
  E: 0,
  F: 1,
  G: 2,
  H: 0,
  I: 1,
  J: 0,
  K: 1,
  L: 0,
  M: 1,
  N: 0,
  O: 0,
  P: 1,
  R: 1,
  S: 0,
  T: 0,
  U: 1,
  V: 2,
  W: 0,
  X: 0,
  Y: 0,
  Z: 0,
};
// Demo provider: fixed, fictional values for the simulation.
export const demoProvider = {
  prediction(step, profile) {
    return {
      level: levels[step],
      percentage: percentages[step],
      status: statuses[step],
      actions: actions[profile][step],
      stability: ["Stable", "Fluctuating", "Unstable", "Highly unstable"][step],
      demand: ["Normal", "Elevated", "High", "Peak load"][step],
    };
  },
  regionStep(code, step) {
    const offset = offsets[code?.replace("VE-", "")];
    return offset === undefined ? null : Math.min(3, step + offset);
  },
};

// Live provider: the forecasting API on IBM LinuxONE (app/api.py). Same origin by default;
// ?api=http://host:8000 points the page at another server.
const API = (new URLSearchParams(location.search).get("api") || "").replace(/\/$/, "");
const getJSON = async (path) => {
  const r = await fetch(API + path, { signal: AbortSignal.timeout(8000) });
  if (!r.ok) throw Error(`${path}: ${r.status}`);
  return r.json();
};
const levelIndex = (l) => levels.findIndex((x) => x.toLowerCase() === l);
export const liveProvider = {
  regions: null,
  households: null,
  device: null,
  async load() {
    const regions = await getJSON("/v1/regions");
    if (!regions.some((r) => r.status === "ok")) throw Error("no live forecasts");
    this.regions = Object.fromEntries(regions.map((r) => [r.region_id, r]));
    try {
      this.households = Object.fromEntries(
        (await getJSON("/v1/households/summary")).regions.map((r) => [r.region_id, r]),
      );
    } catch {
      this.households = null;
    }
    try {
      this.device = (await getJSON("/health")).scoring_device;
    } catch {
      this.device = null;
    }
  },
  record(code) {
    return this.regions?.[code] ?? null;
  },
  regionStep(code) {
    const r = this.record(code);
    return r?.status === "ok" ? levelIndex(r.risk_level) : null;
  },
  prediction(code, profile) {
    const r = this.record(code),
      step = this.regionStep(code);
    if (step === null) return null;
    return {
      level: levels[step],
      percentage: Math.round(r.risk_probability * 100),
      status: r.outage_in_progress
        ? "An outage is under way here now. Follow the steps for your profile."
        : statuses[step],
      actions: actions[profile][step],
      stability: r.grid_stability,
      demand: r.electricity_demand,
      weather: r.weather_risk,
      factors: r.top_factors,
      updated: r.updated_at,
      dataThrough: r.data_through,
    };
  },
};
