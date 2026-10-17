import { levels, percentages, statuses, actions, demoProvider, liveProvider } from "./model.js";

const app = document.querySelector("#app");
const statusPill = document.querySelector("#status");
const modeButton = document.querySelector("#mode");

// One colour per risk level: Low, Moderate, Severe, Critical
const COLORS = ["#0f7a5c", "#a87304", "#c4541f", "#b8283f"]; // text and accents
const FILLS = ["#8cc7ab", "#efd27f", "#eb9a66", "#d05a71"]; // map and bars
const NO_DATA = "#d5dbd8";
const STABILITY = ["Stable", "Fluctuating", "Unstable", "Highly unstable"];
const DEMAND = ["Normal", "Elevated", "High", "Peak load"];

const state = {
  live: false, // true when the forecast comes from the LinuxONE API
  step: 0, // demo simulation step (risk level index)
  profile: "household", // or "medical"
  selected: "VE-A", // Distrito Capital, the demo "current location"
};

let geography;
let zoom = 1;
let pan = { x: 0, y: 0 };

const escape = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

const fmtTime = (d) =>
  new Date(d).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Caracas",
  }) + " VET";

/* ------------------------------------------------------------------ data */

// One shape for every state, from the live forecast or the demo simulation
function region(code) {
  const feature = geography.features.find((f) => f.properties.shapeISO === code);
  const base = { code, name: feature.properties.shapeName };
  if (state.live) {
    const record = liveProvider.record(code);
    const step = liveProvider.regionStep(code);
    if (step === null) return { ...base, step: null };
    return {
      ...base,
      step,
      percent: Math.round(record.risk_probability * 100),
      outageNow: record.outage_in_progress,
      stability: record.grid_stability,
      demand: record.electricity_demand,
      weather: record.weather_risk,
      factors: record.top_factors,
      households: liveProvider.households?.[code] ?? null,
      dataThrough: record.data_through,
    };
  }
  const step = demoProvider.regionStep(code, state.step);
  if (step === null) return { ...base, step: null };
  return {
    ...base,
    step,
    percent: percentages[step],
    outageNow: false,
    stability: STABILITY[step],
    demand: DEMAND[step],
    weather: levels[step],
    factors: [],
    households: null,
  };
}

const allRegions = () => geography.features.map((f) => region(f.properties.shapeISO));
const fillOf = (r) => (r.step === null ? NO_DATA : FILLS[r.step]);
const labelOf = (r) => (r.step === null ? "No data" : r.outageNow ? "Outage now" : levels[r.step]);

/* ------------------------------------------------------------------ header */

function header() {
  statusPill.className = `pill ${state.live ? "live" : "demo"}`;
  statusPill.innerHTML = `<span class="dot"></span>${state.live ? "Live · IBM z17" : "Demo data"}`;
  modeButton.hidden = !state.live && !liveProvider.regions;
  modeButton.textContent = state.live ? "Try the demo simulation" : "Back to live data";
}

function headline() {
  const lede = state.live
    ? "A forecast for every state from internet connectivity and weather, refreshed every hour and scored on IBM LinuxONE. Select a state on the map or in the list."
    : "Demo simulation with fictional values. Step through rising grid stress to see how the guidance changes.";
  return `
    <section class="headline">
      <div>
        <p class="eyebrow">Venezuela · next 24 hours</p>
        <h1>Where the power is likely to go out next</h1>
      </div>
      <p class="lede">${lede}</p>
    </section>`;
}

function kpis(regions) {
  const scored = regions.filter((r) => r.step !== null);
  const critical = scored.filter((r) => r.step === 3).length;
  const outages = scored.filter((r) => r.outageNow).length;
  const urgent =
    state.live && liveProvider.households
      ? Object.values(liveProvider.households).reduce((sum, h) => sum + h.urgent, 0)
      : null;
  const newest = scored.find((r) => r.dataThrough)?.dataThrough;
  const scoredOn = liveProvider.device === "nnpa" ? "scored on Telum, IBM z17" : "IBM LinuxONE";
  const tile = (value, label, color) =>
    `<div class="kpi" style="--k:${color}"><strong>${value}</strong><span>${label}</span></div>`;
  return `
    <section class="kpis">
      ${tile(`${critical}<small>/ ${scored.length}</small>`, "states at critical risk", COLORS[3])}
      ${tile(outages, "outages under way now", outages ? COLORS[3] : "#9aa8a2")}
      ${tile(urgent ?? "—", "medical households to check first", urgent ? COLORS[2] : "#9aa8a2")}
      ${tile(newest ? fmtTime(newest) : "Simulated", state.live ? `latest data · ${scoredOn}` : "demo values", "var(--brand)")}
    </section>`;
}

function demoBar() {
  if (state.live) return "";
  const critical = state.step === 3;
  const steps = levels.map((_, i) => `<i class="${i <= state.step ? "on" : ""}"></i>`).join("");
  return `
    <section class="demo-bar">
      <strong>Demo simulation</strong>
      <button class="primary" id="simulate" ${critical ? "disabled" : ""}>
        ${critical ? "Critical reached" : "Simulate grid deterioration →"}
      </button>
      <button class="link" id="reset">Reset</button>
      <div class="steps" aria-label="Step ${state.step + 1} of 4">${steps}</div>
    </section>`;
}

/* ------------------------------------------------------------------ map */

// Longitude/latitude -> position in the 800 x 710 map drawing
const point = ([x, y]) => [((x + 73.8) / 14.5) * 800, ((13 - y) / 12.8) * 710];

function polygonPath(geometry) {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  const ringPath = (ring) =>
    ring.map((p, i) => `${i ? "L" : "M"}${point(p).map((n) => n.toFixed(2)).join(",")}`).join("") + "Z";
  return polygons.map((polygon) => polygon.map(ringPath).join("")).join("");
}

function mapCard(regions) {
  const paths = geography.features
    .map((f) => {
      const r = regions.find((x) => x.code === f.properties.shapeISO);
      return `
        <path class="region" data-region="${escape(r.code)}" role="button" tabindex="0"
          aria-label="${escape(r.name)}, ${labelOf(r)}" fill="${fillOf(r)}" fill-rule="evenodd"
          d="${polygonPath(f.geometry)}"></path>`;
    })
    .join("");
  const labels = [
    ["ZULIA", -72.1, 10.2],
    ["APURE", -69, 7],
    ["BOLÍVAR", -63.8, 6.1],
    ["AMAZONAS", -66, 3.1],
  ]
    .map(([name, x, y]) => {
      const [px, py] = point([x, y]);
      return `<text x="${px}" y="${py}" class="map-label" text-anchor="middle">${name}</text>`;
    })
    .join("");
  const legend = levels
    .map((l, i) => `<span style="--c:${FILLS[i]}">${l}</span>`)
    .concat(`<span style="--c:${NO_DATA}">No data</span>`)
    .join("");
  return `
    <section class="card map-card">
      <div class="card-head">
        <div>
          <h2>Outage risk by state</h2>
          <p class="muted">Chance an outage starts in the next 24 hours</p>
        </div>
        <div class="legend">${legend}</div>
      </div>
      <div class="map-wrap">
        <svg viewBox="0 0 800 710" role="group" aria-label="Map of Venezuela. Select a state, or use the list below.">
          <g id="map-transform">
            ${paths}
            <text x="365" y="45" class="sea" text-anchor="middle">CARIBBEAN SEA</text>
            ${labels}
            <circle cx="380" cy="140" r="5" fill="#123b35" stroke="white" stroke-width="2" pointer-events="none"/>
            <text x="392" y="135" class="map-label">Caracas</text>
          </g>
        </svg>
        <div class="tip" hidden></div>
        <div class="map-controls">
          <button id="zoom-in" aria-label="Zoom in">+</button>
          <button id="zoom-out" aria-label="Zoom out">−</button>
          <button id="fit" aria-label="Fit map">Fit</button>
        </div>
      </div>
    </section>`;
}

function enableMap() {
  const wrap = app.querySelector(".map-wrap");
  const svg = wrap.querySelector("svg");
  const tip = wrap.querySelector(".tip");

  wrap.querySelectorAll("[data-region]").forEach((el) => {
    el.onclick = () => select(el.dataset.region);
    el.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        select(el.dataset.region);
      }
    };
  });

  // Hover tooltip: state name, level and probability
  wrap.addEventListener("pointermove", (e) => {
    const el = e.target.closest?.("[data-region]");
    if (!el || last) return (tip.hidden = true);
    const r = region(el.dataset.region);
    const box = wrap.getBoundingClientRect();
    tip.innerHTML = `<b>${escape(r.name)}</b>${r.step === null ? "No data" : `${labelOf(r)} · ${r.percent}%`}`;
    tip.style.left = `${e.clientX - box.left}px`;
    tip.style.top = `${e.clientY - box.top}px`;
    tip.hidden = false;
  });
  wrap.addEventListener("pointerleave", () => (tip.hidden = true));

  const transform = () => {
    wrap
      .querySelector("#map-transform")
      .setAttribute(
        "transform",
        `translate(${400 * (1 - zoom) + pan.x} ${355 * (1 - zoom) + pan.y}) scale(${zoom})`,
      );
    wrap.querySelector("#zoom-in").disabled = zoom >= 4;
    wrap.querySelector("#zoom-out").disabled = zoom <= 1;
  };
  wrap.querySelector("#zoom-in").onclick = () => {
    zoom = Math.min(4, zoom + 0.5);
    transform();
  };
  wrap.querySelector("#zoom-out").onclick = () => {
    zoom = Math.max(1, zoom - 0.5);
    if (zoom === 1) pan = { x: 0, y: 0 };
    transform();
  };
  wrap.querySelector("#fit").onclick = () => {
    zoom = 1;
    pan = { x: 0, y: 0 };
    transform();
  };

  // Drag to pan while zoomed in; a drag must not also count as a click on a state
  let last = null;
  let moved = false;
  svg.addEventListener("pointerdown", (e) => {
    if (zoom <= 1) return;
    last = { x: e.clientX, y: e.clientY };
    moved = false;
  });
  svg.addEventListener("pointermove", (e) => {
    if (!last) return;
    const ratio = 800 / svg.getBoundingClientRect().width;
    const dx = e.clientX - last.x;
    const dy = e.clientY - last.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
    pan.x = Math.max(-1000, Math.min(1000, pan.x + dx * ratio));
    pan.y = Math.max(-1000, Math.min(1000, pan.y + dy * ratio));
    last = { x: e.clientX, y: e.clientY };
    transform();
  });
  svg.addEventListener(
    "click",
    (e) => {
      if (moved) {
        e.stopPropagation();
        moved = false;
      }
    },
    true,
  );
  window.onpointerup = () => (last = null);
  svg.onpointerleave = () => (last = null);
  svg.onpointercancel = () => (last = null);
  transform();
}

/* ------------------------------------------------------------------ selected state */

function gauge(percent, color) {
  const radius = 52;
  const circle = 2 * Math.PI * radius;
  return `
    <svg class="gauge" viewBox="0 0 128 128" aria-hidden="true">
      <circle class="track" cx="64" cy="64" r="${radius}" fill="none" stroke-width="12"/>
      <circle cx="64" cy="64" r="${radius}" fill="none" stroke="${color}" stroke-width="12"
        stroke-linecap="round" stroke-dasharray="${(percent / 100) * circle} ${circle}"
        transform="rotate(-90 64 64)"/>
      <text x="64" y="68" text-anchor="middle" font-size="28" font-weight="700" fill="#14211d">${percent}%</text>
      <text x="64" y="88" text-anchor="middle" font-size="10.5" fill="#5d6f68">next 24 h</text>
    </svg>`;
}

function detailCard(r) {
  const heading = `
    <p class="eyebrow">${escape(r.code)}${r.code === "VE-A" ? " · your location" : ""}</p>
    <h2 class="region-name">${escape(r.name)}</h2>`;

  if (r.step === null) {
    return `
      <section class="card detail">
        ${heading}
        <p class="empty">Too few networks here to measure reliably, so we show no forecast rather than a guess.</p>
      </section>`;
  }

  const color = COLORS[r.step];
  const medical = state.profile === "medical";
  const status = r.outageNow
    ? "An outage is under way here now. Follow the steps for your profile."
    : statuses[r.step];
  const why = r.factors.length
    ? `<div class="chips">${r.factors.map((f) => `<span>${escape(f)}</span>`).join("")}</div>`
    : "";
  const conditions = [
    ["Grid stability", r.stability],
    ["Electricity demand", r.demand],
    ["Weather risk", r.weather],
  ]
    .map(([name, value]) => `<div class="condition"><span>${name}</span><strong>${value}</strong></div>`)
    .join("");
  const steps = actions[state.profile][r.step].map((a) => `<li>${a}</li>`).join("");
  const care = r.households?.medical_dependent
    ? `<p class="note">${r.households.medical_dependent} example households here rely on powered medical care; ${r.households.urgent} are urgent to check right now.</p>`
    : "";
  const device = medical
    ? `
      <div class="device">
        <span>Example device · Oxygen concentrator<br><small>Backup battery, demo estimate</small></span>
        <strong>42 <small>min</small></strong>
      </div>
      ${care}`
    : "";
  const disclaimer = !state.live
    ? "Demo values, not current electricity conditions."
    : medical
      ? "Preparedness guidance only, not medical advice. Follow your equipment instructions and care plan. Households are synthetic examples."
      : "Forecast from internet connectivity and weather data, scored on IBM LinuxONE.";

  return `
    <section class="card detail" style="--accent:${color}">
      ${heading}
      <div class="gauge-row">
        ${gauge(r.percent, color)}
        <div>
          <span class="badge ${r.outageNow ? "now" : ""}" style="--c:${color}">${labelOf(r)}</span>
          <p class="status">${status}</p>
        </div>
      </div>
      ${why}
      <div class="conditions">${conditions}</div>
      <div class="tabs" role="group" aria-label="Preparedness profile">
        <button data-profile="household" aria-pressed="${!medical}">Household</button>
        <button data-profile="medical" aria-pressed="${medical}">Medical needs</button>
      </div>
      <ul class="actions">${steps}</ul>
      ${device}
      <p class="disclaimer">${disclaimer}</p>
    </section>`;
}

/* ------------------------------------------------------------------ ranking */

function rankingCard(regions) {
  const sorted = [...regions].sort(
    (a, b) => (b.step === null ? -1 : b.percent) - (a.step === null ? -1 : a.percent),
  );
  const rows = sorted
    .map((r) => {
      const known = r.step !== null;
      return `
        <button class="rank-row ${r.code === state.selected ? "selected" : ""}" data-pick="${escape(r.code)}">
          <span class="rank-name">${escape(r.name)}</span>
          <span class="bar"><i style="width:${known ? r.percent : 0}%;background:${fillOf(r)}"></i></span>
          <span class="rank-pct">${known ? `${r.percent}%` : "—"}</span>
          <span class="chip" style="--c:${known ? COLORS[r.step] : "#8a9a94"}">${labelOf(r)}</span>
        </button>`;
    })
    .join("");
  return `
    <section class="card ranking">
      <div class="card-head">
        <div>
          <h2>All states, highest risk first</h2>
          <p class="muted">Select a state to see its forecast and what to do</p>
        </div>
      </div>
      <div class="rank-list" style="--rows:${Math.ceil(sorted.length / 2)}">${rows}</div>
    </section>`;
}

/* ------------------------------------------------------------------ page */

function select(code) {
  state.selected = code;
  const r = region(code);
  app.querySelectorAll("[data-region]").forEach((el) => {
    const on = el.dataset.region === code;
    el.classList.toggle("selected", on);
    el.setAttribute("aria-pressed", String(on));
    if (on) el.parentNode.appendChild(el); // draw the selected outline on top
  });
  app.querySelectorAll("[data-pick]").forEach((el) => {
    el.classList.toggle("selected", el.dataset.pick === code);
  });
  app.querySelector(".detail").outerHTML = detailCard(r);
  app.querySelectorAll("[data-profile]").forEach((button) => {
    button.onclick = () => {
      state.profile = button.dataset.profile;
      select(state.selected);
      app.querySelector(`[data-profile="${state.profile}"]`).focus();
    };
  });
}

function render() {
  header();
  const regions = allRegions();
  app.innerHTML = `
    ${headline()}
    ${kpis(regions)}
    ${demoBar()}
    <div class="main-grid">
      ${mapCard(regions)}
      <section class="card detail"></section>
    </div>
    ${rankingCard(regions)}`;

  enableMap();
  app.querySelectorAll("[data-pick]").forEach((el) => {
    el.onclick = () => select(el.dataset.pick);
  });
  app.querySelector("#simulate")?.addEventListener("click", () => {
    state.step = Math.min(3, state.step + 1);
    render();
  });
  app.querySelector("#reset")?.addEventListener("click", () => {
    state.step = 0;
    render();
  });
  select(state.selected);
}

modeButton.onclick = () => {
  state.live = !state.live;
  state.step = 0;
  render();
};

/* ------------------------------------------------------------------ start */

try {
  await liveProvider.load();
  state.live = true;
} catch (e) {
  console.info("Live data unavailable, showing demo data.", e);
}

try {
  const response = await fetch("assets/venezuela-adm1.geojson");
  if (!response.ok) throw Error("Boundary file unavailable");
  geography = await response.json();
  render();
} catch (e) {
  app.innerHTML = '<p class="muted loading">The map could not load. Please refresh the page.</p>';
}

// Pick up the API's hourly data refresh
setInterval(async () => {
  if (!state.live) return;
  try {
    await liveProvider.load();
    render();
  } catch (e) {}
}, 600000);
