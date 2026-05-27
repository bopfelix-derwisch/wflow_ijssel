"use strict";

const { ColumnLayer, ScatterplotLayer } = deck;

const API = "";
const JAN_DAYS = Array.from({ length: 31 }, (_, i) => {
  const d = new Date(1995, 0, i + 1);
  return d.toISOString().slice(0, 10);
});
const DISCHARGE_THRESHOLD = 1500;

function dischargeColor(q) {
  const t = Math.min(q / 3500, 1);
  if (t < 0.4)  return [21,  101, 192, 220];
  if (t < 0.7)  return [255, 152,   0, 220];
  return              [244,  67,  54, 220];
}

let dayIdx    = 0;
let playing   = false;
let playTimer = null;
let riverData = [];
let overlay   = null;

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
  init();
});

async function init() {
  const [kpis, tsKampen, tsWestervoort] = await Promise.all([
    fetch(`${API}/api/kpis`).then(r => r.json()),
    fetch(`${API}/api/timeseries/kampen`).then(r => r.json()),
    fetch(`${API}/api/timeseries/westervoort`).then(r => r.json()),
  ]);

  renderKpis(kpis, tsWestervoort);
  renderChart(tsKampen, tsWestervoort);
  await loadDay(0);
}

function renderKpis(kpis, tsW) {
  document.getElementById("val-peak").textContent =
    kpis.peak_q.toLocaleString("nl-NL") + " m³/s";
  document.getElementById("sub-peak").textContent =
    `m³/s · piek op ${kpis.peak_date}`;
  document.getElementById("val-inflow").textContent =
    Math.max(...tsW.q).toLocaleString("nl-NL");
  document.getElementById("val-precip").textContent = "+182%";
  document.getElementById("val-days").textContent =
    kpis.days_above_threshold + " dagen";
  document.getElementById("alert-badge").textContent = "⚠ EXTREEM HOOGWATER";
}

function renderChart(tsK, tsW) {
  Plotly.newPlot("chart", [
    {
      x: tsK.dates, y: tsK.q,
      type: "scatter", mode: "lines",
      name: "Debiet Kampen (m³/s)",
      line: { color: "#f44336", width: 2 },
      yaxis: "y",
      fill: "tozeroy",
      fillcolor: "rgba(244,67,54,0.1)",
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
      titlefont: { color: "#f44336" }, tickfont: { color: "#f44336" },
    },
    yaxis2: {
      title: "Waterpeil (m+NAP)", overlaying: "y", side: "right",
      titlefont: { color: "#4caf50" }, tickfont: { color: "#4caf50" },
      gridcolor: "rgba(0,0,0,0)",
    },
    shapes: [{
      type: "line", x0: JAN_DAYS[0], x1: JAN_DAYS[0],
      yref: "paper", y0: 0, y1: 1,
      line: { color: "#4fc3f7", width: 1, dash: "dot" },
    }],
  }, { responsive: true, displayModeBar: false });
}

function updateChartCursor(dayIso) {
  Plotly.relayout("chart", { "shapes[0].x0": dayIso, "shapes[0].x1": dayIso });
}

async function loadDay(idx) {
  const day = JAN_DAYS[idx];
  const gj  = await fetch(`${API}/api/river/${day}`).then(r => r.json());
  riverData  = gj.features.map(f => ({
    coordinates: f.geometry.coordinates,
    q: f.properties.q,
    h: f.properties.h,
  }));

  document.getElementById("day-label").textContent =
    new Date(day + "T12:00:00").toLocaleDateString("nl-NL", { day: "numeric", month: "long", year: "numeric" });

  updateChartCursor(day);
  renderDeckLayers();
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
          { name: "Kampen",      coords: [5.92, 52.55], color: [244, 67, 54] },
          { name: "Westervoort", coords: [6.17, 51.97], color: [255, 152, 0] },
        ],
        getPosition:  d => d.coords,
        getFillColor: d => d.color,
        getRadius:    800,
        pickable:     true,
      }),
    ],
  });
}

const slider  = document.getElementById("day-slider");
const playBtn = document.getElementById("play-btn");

slider.max = JAN_DAYS.length - 1;
slider.addEventListener("input", () => {
  dayIdx = parseInt(slider.value, 10);
  loadDay(dayIdx);
});

playBtn.addEventListener("click", () => {
  playing = !playing;
  playBtn.textContent = playing ? "⏸" : "▶";
  if (playing) {
    playTimer = setInterval(() => {
      dayIdx = (dayIdx + 1) % JAN_DAYS.length;
      slider.value = dayIdx;
      loadDay(dayIdx);
      if (dayIdx === JAN_DAYS.length - 1) {
        clearInterval(playTimer);
        playing = false;
        playBtn.textContent = "▶";
      }
    }, 600);
  } else {
    clearInterval(playTimer);
  }
});
