import { levels, percentages, demoProvider, liveProvider } from "./model.js";

const app = document.querySelector("#app");
const nav = document.querySelector("#navigation");

// One colour per risk level: Low, Moderate, Severe, Critical
const colors = ["#08735b", "#946407", "#bd4c20", "#b5253c"];
const tints = ["#e7f4ed", "#fff4d9", "#fff0e7", "#fcebef"];
const fills = ["#81bca1", "#ebcd7b", "#e89968", "#cd6477"];

const state = {
  step: 0, // risk level index shown on the dashboard
  profile: "household", // or "medical"
  map: false, // which page is showing
  selected: "VE-A", // region picked on the map (Distrito Capital)
  updated: new Date(), // last demo step
  live: false, // true when the forecast comes from the LinuxONE API
};

let geography;
let zoom = 1;
let pan = { x: 0, y: 0 };

const escape = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

function theme(step) {
  document.documentElement.style.setProperty("--accent", colors[step]);
  document.documentElement.style.setProperty("--tint", tints[step]);
}

const badge = () =>
  state.live
    ? '<span class="demo live">LIVE · IBM z17</span>'
    : '<span class="demo">DEMO DATA</span>';

const fmtTime = (d) =>
  new Date(d).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Caracas",
  }) + " VET";

const intro = (eyebrow, title) => `
  <div class="intro">
    <div><p class="eyebrow">${eyebrow}</p><h1 tabindex="-1">${title}</h1></div>
    ${badge()}
  </div>`;

/* ---------------------------------------------------------------- dashboard */

function riskCard(p) {
  const spectrum = levels
    .map((l, i) => `<span class="${i === state.step ? "active" : ""}">${l}</span>`)
    .join("");
  const why =
    state.live && p.factors?.length
      ? `<p class="muted" style="margin:8px 0 0">Why: ${p.factors.map(escape).join(", ")}</p>`
      : "";
  return `
    <section class="card hero" aria-label="Power outage risk">
      <div class="hero-top">
        <div><h2>Power Outage Risk</h2><p class="muted">Next 24 hours</p></div>
        <span class="risk-badge">${p.level.toUpperCase()}</span>
      </div>
      <div class="probability" aria-label="${p.percentage} percent">${p.percentage}<span>%</span></div>
      <div class="prob-label">
        ${state.live ? "Chance an outage starts in the next 24 hours" : "Predicted probability of an outage · demo"}
      </div>
      <div class="spectrum">${spectrum}</div>
      <p class="status" role="status">${p.status}</p>
      ${why}
      <div class="timestamp">
        <span>Updated ${fmtTime(state.live ? p.updated : state.updated)}</span>
        <span>${state.live ? "Live forecast · data to " + fmtTime(p.dataThrough) : "Simulated prediction"}</span>
      </div>
    </section>`;
}

function gridCard(p) {
  const rows = [
    ["Grid stability", p.stability],
    ["Electricity demand", p.demand],
    ["Weather risk", p.weather || p.level],
  ]
    .map(([name, value]) => `<div class="grid-row"><span>${name}</span><strong>${value}</strong></div>`)
    .join("");
  return `
    <section class="card">
      <h2>Live Grid Conditions</h2>
      <p class="muted" style="margin:6px 0 0">
        ${state.live ? "From internet connectivity and weather data" : "Simulated signals for this demo"}
      </p>
      <div class="grid-rows">${rows}</div>
    </section>`;
}

function preparednessCard(p, medical) {
  const warning =
    state.step >= 2
      ? `
        <div class="warning">
          <strong>${state.step === 3 ? "Prepare backup power immediately" : "Prioritise medical backup power"}</strong>
          <p>Confirm your backup plan and contact your support person if needed.</p>
        </div>`
      : "";
  const readiness = medical
    ? `
      <div class="readiness">
        <p>EXAMPLE DEVICE</p>
        <div class="battery"><span>Oxygen Concentrator</span><strong>42 <small>min</small></strong></div>
        <p>Backup battery · demo estimate · remaining</p>
      </div>
      ${warning}`
    : "";
  const actions = p.actions
    .map((a) => `<li><span class="check" aria-hidden="true">✓</span><span>${a}</span></li>`)
    .join("");
  const disclaimer = medical
    ? `<p class="disclaimer">Preparedness guidance only. Follow your equipment instructions and personal care plan. This is not a medical diagnosis tool.</p>`
    : "";
  return `
    <section class="card">
      <p class="eyebrow">Preparedness for you</p>
      <div class="profile-switch" aria-label="Preparedness profile">
        <button data-profile="household" aria-pressed="${!medical}">Household</button>
        <button data-profile="medical" aria-pressed="${medical}">Medical Power Dependency</button>
      </div>
      <div class="section-rule"></div>
      <h2>${medical ? "Medical Power Readiness" : "Recommended Actions"}</h2>
      <p class="muted" style="margin:8px 0">
        ${medical ? "Keep essential care powered." : "Small steps. Better prepared."}
      </p>
      ${readiness}
      <ul class="actions">${actions}</ul>
      ${disclaimer}
    </section>`;
}

function liveCard() {
  const where =
    liveProvider.device === "nnpa"
      ? "on the Telum AI accelerator of an IBM z17"
      : "on IBM LinuxONE";
  return `
    <section class="simulation">
      <div class="sim-heading">
        <p class="eyebrow">Live from IBM LinuxONE</p>
        <button class="reset" id="to-demo">Demo mode ↺</button>
      </div>
      <p class="muted" style="margin:0">
        Forecast scored ${where}, from internet connectivity and weather data refreshed every hour.
      </p>
    </section>`;
}

function simulationCard() {
  const toLive = liveProvider.regions
    ? '<button class="reset" id="to-live">Live data</button> '
    : "";
  const critical = state.step === 3;
  const steps = levels.map((_, i) => `<i class="${i <= state.step ? "on" : ""}"></i>`).join("");
  return `
    <section class="simulation">
      <div class="sim-heading">
        <p class="eyebrow">Demo simulation</p>
        <span>${toLive}<button class="reset" id="reset">Reset ↺</button></span>
      </div>
      <button class="primary" id="simulate" ${critical ? "disabled" : ""}><span>${critical ? "Critical reached · Reset to replay" : "Simulate Grid Deterioration"}</span><span aria-hidden="true">→</span></button>
      <div class="sim-bottom">
        <span>Explore how guidance changes with risk</span>
        <div class="steps" aria-label="Step ${state.step + 1} of 4">${steps}</div>
      </div>
    </section>`;
}

function dashboard() {
  if (state.live) state.step = liveProvider.regionStep("VE-A") ?? 0;
  theme(state.step);
  const p =
    (state.live && liveProvider.prediction("VE-A", state.profile)) ||
    demoProvider.prediction(state.step, state.profile);
  const medical = state.profile === "medical";

  app.innerHTML = `
    ${intro("Your current location", "Caracas, Venezuela")}
    <div class="layout">
      <div class="column">
        ${riskCard(p)}
        ${gridCard(p)}
      </div>
      <div class="column">
        ${preparednessCard(p, medical)}
        ${state.live ? liveCard() : simulationCard()}
      </div>
    </div>`;

  app.querySelectorAll("[data-profile]").forEach((button) => {
    button.onclick = () => {
      state.profile = button.dataset.profile;
      dashboard();
      app.querySelector(`[data-profile="${state.profile}"]`).focus();
    };
  });

  if (!state.live) {
    app.querySelector("#simulate").onclick = () => {
      state.step = Math.min(3, state.step + 1);
      state.updated = new Date();
      dashboard();
      app.querySelector(state.step === 3 ? "#reset" : "#simulate").focus();
    };
    app.querySelector("#reset").onclick = () => {
      state.step = 0;
      state.updated = new Date();
      dashboard();
      app.querySelector("#reset").focus();
    };
  }

  app.querySelector("#to-demo")?.addEventListener("click", () => {
    state.live = false;
    state.step = 0;
    state.updated = new Date();
    dashboard();
  });
  app.querySelector("#to-live")?.addEventListener("click", () => {
    state.live = true;
    dashboard();
  });
}

/* ---------------------------------------------------------------------- map */

// Longitude/latitude -> position in the 800 x 710 map drawing
const point = ([x, y]) => [((x + 73.8) / 14.5) * 800, ((13 - y) / 12.8) * 710];

function polygonPath(geometry) {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  const ringPath = (ring) =>
    ring.map((p, i) => `${i ? "L" : "M"}${point(p).map((n) => n.toFixed(2)).join(",")}`).join("") + "Z";
  return polygons.map((polygon) => polygon.map(ringPath).join("")).join("");
}

const regionStep = (code) =>
  state.live ? liveProvider.regionStep(code) : demoProvider.regionStep(code, state.step);

function mapShell() {
  const legend = levels.map((l, i) => `<span style="--c:${fills[i]}">${l}</span>`).join("");
  return `
    ${intro("A wider view", "Venezuela")}
    <div class="map-layout">
      <section class="card map-card">
        <div class="map-heading">
          <div>
            <h2>Regional outage risk</h2>
            <p class="muted" style="margin:6px 0">
              ${state.live ? "Next 24 hours · Live forecast" : "Next 24 hours · Demo predictions"}
            </p>
          </div>
          <span class="eyebrow" style="white-space:nowrap;margin-top:5px">25 regions</span>
        </div>
        <div class="legend">${legend}</div>
        <div class="map-wrap" aria-label="Interactive Venezuela administrative regions">
          <div class="muted" style="padding:30px" role="status">Loading regional boundaries…</div>
        </div>
        <p class="source">
          Boundaries: OCHA Venezuela / INE via
          <a href="https://www.geoboundaries.org/api/current/gbOpen/VEN/ADM1/" target="_blank" rel="noopener">geoBoundaries ↗</a>
          · 2020 ·
          <a href="https://creativecommons.org/licenses/by/3.0/igo/" target="_blank" rel="noopener">CC BY 3.0 IGO</a>.
          <a href="assets/BOUNDARY-LICENSE.txt">Attribution</a>
        </p>
      </section>
      <aside class="card region-panel" aria-label="Selected region"></aside>
    </div>`;
}

function mapDrawing() {
  const regions = geography.features
    .map((f) => {
      const s = regionStep(f.properties.shapeISO);
      const name = escape(f.properties.shapeName);
      return `
        <path class="region" data-region="${escape(f.properties.shapeISO)}" role="button" tabindex="0"
          aria-label="${name}, ${s === null ? "no data" : levels[s] + " risk"}"
          fill="${s === null ? "#ccc" : fills[s]}" fill-rule="evenodd"
          d="${polygonPath(f.geometry)}"><title>${name}</title></path>`;
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
  return `
    <svg viewBox="0 0 800 710" role="group" aria-label="Map of Venezuela. Select a region, or use the region list.">
      <g id="map-transform">
        ${regions}
        <text x="365" y="45" class="sea" text-anchor="middle">CARIBBEAN SEA</text>
        ${labels}
        <circle cx="380" cy="140" r="5" fill="#173e35" stroke="white" stroke-width="2" pointer-events="none"/>
        <text x="392" y="135" class="map-label">Caracas</text>
      </g>
    </svg><div class="map-controls">
      <button id="zoom-in" aria-label="Zoom in">+</button>
      <button id="zoom-out" aria-label="Zoom out">−</button>
      <button id="fit" aria-label="Fit map">Fit map</button>
    </div>`;
}

function enableMapControls(wrap) {
  wrap.querySelectorAll("[data-region]").forEach((el) => {
    el.onclick = () => selectRegion(el.dataset.region);
    el.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectRegion(el.dataset.region);
      }
    };
  });

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

  // Drag to pan while zoomed in; a drag must not also count as a click on a region
  const svg = wrap.querySelector("svg");
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

async function mapPage() {
  theme(0);
  app.innerHTML = mapShell();
  try {
    if (!geography) {
      const response = await fetch("assets/venezuela-adm1.geojson");
      if (!response.ok) throw Error("Boundary file unavailable");
      geography = await response.json();
    }
    if (!state.map) return;
    const wrap = app.querySelector(".map-wrap");
    wrap.innerHTML = mapDrawing();
    enableMapControls(wrap);
    selectRegion(state.selected);
  } catch (e) {
    if (state.map)
      app.querySelector(".map-wrap").innerHTML =
        '<div class="error">The map could not load. <button id="retry">Try again</button></div>';
    app.querySelector("#retry")?.addEventListener("click", mapPage);
  }
}

/* ------------------------------------------------------- selected region panel */

function regionPanel(code) {
  const feature = geography.features.find((f) => f.properties.shapeISO === code);
  const step = regionStep(code);
  const record = state.live ? liveProvider.record(code) : null;
  const households = state.live ? liveProvider.households?.[code] : null;

  const options = [...geography.features]
    .sort((a, b) => a.properties.shapeName.localeCompare(b.properties.shapeName))
    .map(
      (f) =>
        `<option value="${escape(f.properties.shapeISO)}" ${f.properties.shapeISO === code ? "selected" : ""}>${escape(f.properties.shapeName)}</option>`,
    )
    .join("");
  const subtitle =
    code === "VE-A"
      ? state.live ? "Caracas · your current location" : "Caracas · current demo location"
      : state.live ? "Live regional forecast" : "Regional demo prediction";
  const percent =
    step === null ? "—" : record ? Math.round(record.risk_probability * 100) : percentages[step];
  const level =
    step === null ? "NO DATA" : record?.outage_in_progress ? "OUTAGE NOW" : levels[step].toUpperCase();
  const why = record?.top_factors?.length
    ? `<p class="map-note">Why: ${record.top_factors.map(escape).join(", ")}</p>`
    : "";
  const care = households?.medical_dependent
    ? `<p class="map-note">${households.medical_dependent} example households here rely on powered medical care; ${households.urgent} are urgent right now.</p>`
    : "";
  const disclaimer = !state.live
    ? "Regional predictions are fictional demo values. They do not represent current electricity conditions."
    : step === null
      ? "Too few networks here to measure reliably, so we show no forecast rather than a guess."
      : "Forecast from internet connectivity and weather data, scored on IBM LinuxONE. Households are synthetic examples.";

  return {
    step,
    html: `
      <div>
        <label class="eyebrow" for="region-select">Explore ADM1 regions</label><select id="region-select">${options}</select>
        <div aria-live="polite">
          <p class="eyebrow">${escape(code)}</p>
          <h2>${escape(feature.properties.shapeName)}</h2>
          <p class="muted">${subtitle}</p>
        </div>
      </div>
      <div>
        <div class="probability">${percent}<span>%</span></div>
        <div class="prob-label">Outage probability · next 24 hours</div>
        <span class="risk-badge">${level}</span>
        ${why}
        ${care}
        <p class="map-note">Select a region on the map or from the list. Use + to zoom, then drag to explore.</p>
        <p class="disclaimer">${disclaimer}</p>
      </div>`,
  };
}

function selectRegion(code) {
  state.selected = code;
  app.querySelectorAll("[data-region]").forEach((el) => {
    el.classList.toggle("selected", el.dataset.region === code);
    el.setAttribute("aria-pressed", String(el.dataset.region === code));
  });
  const panel = app.querySelector(".region-panel");
  const { step, html } = regionPanel(code);
  panel.style.setProperty("--accent", colors[step] || "#65776c");
  panel.style.setProperty("--tint", tints[step] || "#eee");
  panel.innerHTML = html;
  panel.querySelector("select").onchange = (e) => {
    selectRegion(e.target.value);
    panel.querySelector("select").focus();
  };
}

/* --------------------------------------------------------------- navigation */

function navigate(map) {
  state.map = map;
  nav.innerHTML = map
    ? 'Current location <span aria-hidden="true">↙</span>'
    : 'Map <span aria-hidden="true">↗</span>';
  if (map) mapPage();
  else dashboard();
  app.querySelector("h1")?.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

nav.onclick = () => navigate(!state.map);
document.querySelector(".brand").onclick = (e) => {
  e.preventDefault();
  navigate(false);
};

// Start on live data from the LinuxONE API when it answers, otherwise the demo
try {
  await liveProvider.load();
  state.live = true;
} catch (e) {
  console.info("Live data unavailable, showing demo data.", e);
}
dashboard();

// Pick up the API's hourly data refresh
setInterval(async () => {
  if (!state.live) return;
  try {
    await liveProvider.load();
    state.map ? mapPage() : dashboard();
  } catch (e) {}
}, 600000);
