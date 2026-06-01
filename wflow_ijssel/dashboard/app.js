"use strict";

const { ColumnLayer, ScatterplotLayer } = deck;

const API = "";
const DISCHARGE_THRESHOLD = 1500;

// ── jaar-configuratie ─────────────────────────────────────────────────────────

const YEAR_CONFIG = {
  "1995": {
    days: buildDays("1995-01-01", "1995-01-31"),
    accentColor:  [244, 67, 54],
    sliderColor:  "#f44336",
    themeClass:   "",
    eventLabel:   "Rijn-Hoogwater januari 1995 — piek Lobith ~12 600 m³/s op 31 jan",
    precipLabel:  "+182% (KNMI, jan 1995)",
    alertText:    "⚠ EXTREEM HOOGWATER",
    alertBg:      "#c62828",
  },
  "2021": {
    days: buildDays("2021-07-01", "2021-08-31"),
    accentColor:  [206, 147, 216],
    sliderColor:  "#ce93d8",
    themeClass:   "year-2021",
    eventLabel:   "Rijn-Hoogwater juli 2021 — piek Lobith ~8 900 m³/s op 15 jul · IJssel-aandeel ≈25%",
    precipLabel:  "+120% (ERA5, jul 2021)",
    alertText:    "⚠ ERNSTIG HOOGWATER",
    alertBg:      "#6a1b9a",
  },
};

function buildDays(start, end) {
  const days = [];
  let d = new Date(start + "T12:00:00Z");
  const e = new Date(end   + "T12:00:00Z");
  while (d <= e) {
    days.push(d.toISOString().slice(0, 10));
    d = new Date(d.getTime() + 86400000);
  }
  return days;
}

// ── state ─────────────────────────────────────────────────────────────────────

let currentYear = "1995";
let dayIdx      = 0;
let playing     = false;
let playTimer   = null;
let riverData   = [];
let overlay     = null;
let loadAbortController = null;

// ── kaart ─────────────────────────────────────────────────────────────────────

const map = new maplibregl.Map({
  container: "map",
  style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  center: [6.1, 52.2],
  zoom: 8,
  pitch: 45,
  bearing: 0,
});

map.on("load", () => {
  overlay = new deck.MapboxOverlay({ layers: [] });
  map.addControl(overlay);
  loadYear("1995");
});

// ── jaar wisselen ─────────────────────────────────────────────────────────────

document.querySelectorAll(".year-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    const y = btn.dataset.year;
    if (y === currentYear) return;
    switchYear(y);
  });
});

function switchYear(year) {
  if (playing) stopPlay();
  currentYear = year;
  dayIdx = 0;

  // tab styling
  document.querySelectorAll(".year-tab").forEach(b => {
    b.className = "year-tab";
    if (b.dataset.year === year) b.classList.add(`active-${year}`);
  });

  // body theme
  const cfg = YEAR_CONFIG[year];
  document.body.className = cfg.themeClass;

  // slider accent kleur (via inline style)
  document.getElementById("day-slider").style.accentColor = cfg.sliderColor;

  loadYear(year);
}

async function loadYear(year) {
  const cfg  = YEAR_CONFIG[year];
  const days = cfg.days;

  document.getElementById("event-banner").textContent =
    `Wflow SBM simulatie  ·  ${cfg.eventLabel}`;

  const slider = document.getElementById("day-slider");
  slider.max   = days.length - 1;
  slider.value = 0;

  const badge = document.getElementById("alert-badge");
  badge.textContent = "⏳ Laden...";
  badge.style.background = "#555";

  try {
    const [kpis, tsK, tsW] = await Promise.all([
      fetch(`${API}/api/${year}/kpis`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }),
      fetch(`${API}/api/${year}/timeseries/kampen`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }),
      fetch(`${API}/api/${year}/timeseries/westervoort`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }),
    ]);

    renderKpis(kpis, tsW, cfg);
    renderChart(tsK, tsW, days, cfg);
    await loadDay(0);

    badge.textContent = cfg.alertText;
    badge.style.background = cfg.alertBg;
  } catch (err) {
    badge.textContent = year === "2021"
      ? "Simulatie 2021 nog niet klaar"
      : "Fout bij laden — voer export_output.py uit";
    badge.style.background = "#555";
    console.warn(`Jaar ${year} niet beschikbaar:`, err);
  }
}

// ── KPI's ─────────────────────────────────────────────────────────────────────

function renderKpis(kpis, tsW, cfg) {
  document.getElementById("val-peak").textContent =
    kpis.peak_q.toLocaleString("nl-NL") + " m³/s";
  document.getElementById("sub-peak").textContent =
    `piek op ${kpis.peak_date}`;
  document.getElementById("val-inflow").textContent =
    Math.round(Math.max(...tsW.q)).toLocaleString("nl-NL");
  document.getElementById("val-precip").textContent = cfg.precipLabel.split(" ")[0];
  document.getElementById("sub-precip").textContent = cfg.precipLabel.split(" ").slice(1).join(" ");
  document.getElementById("val-days").textContent =
    kpis.days_above_threshold + " dagen";
}

// ── grafiek ───────────────────────────────────────────────────────────────────

function renderChart(tsK, tsW, days, cfg) {
  const [r, g, b] = cfg.accentColor;
  Plotly.react("chart", [
    {
      x: tsK.dates, y: tsK.q,
      type: "scatter", mode: "lines",
      name: "Debiet Kampen (m³/s)",
      line: { color: `rgb(${r},${g},${b})`, width: 2 },
      yaxis: "y",
      fill: "tozeroy",
      fillcolor: `rgba(${r},${g},${b},0.1)`,
    },
    {
      x: tsK.dates, y: tsK.h_nap,
      type: "scatter", mode: "lines",
      name: "Waterpeil Kampen (m+NAP)",
      line: { color: "#4caf50", width: 2, dash: "dot" },
      yaxis: "y2",
    },
    {
      x: tsK.dates,
      y: Array(tsK.dates.length).fill(DISCHARGE_THRESHOLD),
      type: "scatter", mode: "lines",
      name: "Drempel 1500 m³/s",
      line: { color: "#ff9800", width: 1, dash: "dash" },
      yaxis: "y",
    },
  ], {
    paper_bgcolor: "#080c14",
    plot_bgcolor:  "#0d1b2a",
    font:   { color: "#e0e0e0", size: 11 },
    margin: { t: 10, b: 40, l: 60, r: 60 },
    legend: { orientation: "h", y: -0.25 },
    xaxis: { gridcolor: "#1a3a5c", tickformat: "%d %b" },
    yaxis: {
      title: "Debiet (m³/s)", gridcolor: "#1a3a5c",
      titlefont: { color: `rgb(${r},${g},${b})` },
      tickfont:  { color: `rgb(${r},${g},${b})` },
    },
    yaxis2: {
      title: "Waterpeil (m+NAP)", overlaying: "y", side: "right",
      titlefont: { color: "#4caf50" }, tickfont: { color: "#4caf50" },
      gridcolor: "rgba(0,0,0,0)",
    },
    shapes: [{
      type: "line",
      x0: days[0], x1: days[0],
      yref: "paper", y0: 0, y1: 1,
      line: { color: "#4fc3f7", width: 1, dash: "dot" },
    }],
  }, { responsive: true, displayModeBar: false });
}

function updateChartCursor(dayIso) {
  Plotly.relayout("chart", { "shapes[0].x0": dayIso, "shapes[0].x1": dayIso });
}

// ── dag laden ─────────────────────────────────────────────────────────────────

async function loadDay(idx) {
  if (loadAbortController) loadAbortController.abort();
  loadAbortController = new AbortController();
  const signal = loadAbortController.signal;

  const day  = YEAR_CONFIG[currentYear].days[idx];
  const year = currentYear;

  try {
    const gj = await fetch(`${API}/api/${year}/river/${day}`, { signal }).then(r => r.json());
    riverData = gj.features.map(f => ({
      coordinates: f.geometry.coordinates,
      q: f.properties.q,
      h: f.properties.h,
    }));

    document.getElementById("day-label").textContent =
      new Date(day + "T12:00:00Z").toLocaleDateString("nl-NL",
        { day: "numeric", month: "long", year: "numeric" });

    updateChartCursor(day);
    renderDeckLayers();
  } catch (err) {
    if (err.name !== "AbortError") console.warn("loadDay mislukt:", err);
  }
}

// ── deck.gl ───────────────────────────────────────────────────────────────────

function dischargeColor(q) {
  const [r, g, b] = YEAR_CONFIG[currentYear].accentColor;
  const t = Math.min(q / 3500, 1);
  if (t < 0.4) return [21, 101, 192, 220];
  if (t < 0.7) return [255, 152, 0, 220];
  return [r, g, b, 220];
}

function renderDeckLayers() {
  if (!overlay) return;
  overlay.setProps({
    layers: [
      new ColumnLayer({
        id:           "river-q",
        data:         riverData,
        getPosition:  d => d.coordinates,
        getElevation: d => Math.max(d.q / 8, 10),
        getColor:     d => dischargeColor(d.q),
        radius:       400,
        extruded:     true,
        pickable:     true,
        autoHighlight: true,
      }),
      new ScatterplotLayer({
        id:   "stations",
        data: [
          { name: "Kampen",      coords: [5.496, 53.221], color: [244, 67, 54] },
          { name: "Westervoort", coords: [6.154, 51.987], color: [255, 152, 0] },
        ],
        getPosition:  d => d.coords,
        getFillColor: d => d.color,
        getRadius:    800,
        pickable:     true,
      }),
    ],
  });
}

// ── slider & play ─────────────────────────────────────────────────────────────

const slider  = document.getElementById("day-slider");
const playBtn = document.getElementById("play-btn");

slider.addEventListener("input", () => {
  dayIdx = parseInt(slider.value, 10);
  loadDay(dayIdx);
});

playBtn.addEventListener("click", () => {
  playing ? stopPlay() : startPlay();
});

function startPlay() {
  playing = true;
  playBtn.textContent = "⏸";
  const days = YEAR_CONFIG[currentYear].days;
  playTimer = setInterval(() => {
    dayIdx = (dayIdx + 1) % days.length;
    slider.value = dayIdx;
    loadDay(dayIdx);
    if (dayIdx === days.length - 1) stopPlay();
  }, 600);
}

function stopPlay() {
  playing = false;
  playBtn.textContent = "▶";
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
}
