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
    threshold:    1500,
    thresholdLabel: "Drempel 1500 m³/s",
  },
  "2018": {
    days: buildDays("2018-06-01", "2018-08-31"),
    accentColor:  [255, 193, 7],
    sliderColor:  "#ffc107",
    themeClass:   "year-2018",
    eventLabel:   "Droogte zomer 2018 — Lobith ~600 m³/s (normaal ~2 000 m³/s) · IJssel laag peil",
    precipLabel:  "−40% (ERA5, zomer 2018)",
    alertText:    "⚠ ERNSTIGE DROOGTE",
    alertBg:      "#e65100",
    threshold:    200,
    thresholdLabel: "Laagwater 200 m³/s",
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
    threshold:    1500,
    thresholdLabel: "Drempel 1500 m³/s",
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

let currentYear = "intro";
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
  center: [6.1, 52.4],
  zoom: 9.5,
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

  const simView     = document.getElementById("sim-view");
  const infoPnl     = document.getElementById("info-panel");
  const uitlegPnl   = document.getElementById("uitleg-panel");
  const forecastPnl = document.getElementById("forecast-panel");
  const ensemblePnl = document.getElementById("ensemble-panel");
  const introPnl    = document.getElementById("intro-panel");
  const banner      = document.getElementById("event-banner");

  function hideAll() {
    simView.style.display = "none";
    [infoPnl, uitlegPnl, forecastPnl, ensemblePnl, introPnl].forEach(p => {
      if (p) p.classList.remove("visible");
    });
    ["multimodel-panel","roadmap-panel","arch-panel","fews-panel","pocs-panel","grondwater-panel","handleiding-panel"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.remove("visible");
    });
  }

  if (year === "intro") {
    hideAll();
    introPnl.classList.add("visible");
    banner.textContent = "Waterlab · micro-innovatielab · hydrologische modellering + AI · NVIDIA Jetson AGX Orin";
    document.getElementById("alert-badge").textContent = "⚗ Waterlab";
    document.getElementById("alert-badge").style.background = "#37474f";
    document.body.className = "";
    return;
  }

  if (year === "handleiding") {
    hideAll();
    document.getElementById("handleiding-panel").classList.add("visible");
    banner.textContent = "Handleiding · navigatie, API's (PI REST · GraphQL) en databronnen";
    document.getElementById("alert-badge").textContent = "📖 Handleiding";
    document.getElementById("alert-badge").style.background = "#455a64";
    document.body.className = "";
    return;
  }

  if (year === "forecast") {
    hideAll();
    forecastPnl.classList.add("visible");
    banner.textContent = "Live verwachting IJssel · RWS Waterinfo + Open-Meteo · indicatief 14 dagen";
    document.getElementById("alert-badge").textContent = "📡 Verwachting";
    document.getElementById("alert-badge").style.background = "#00695c";
    document.body.className = "";
    loadForecast();
    return;
  }

  if (year === "info") {
    hideAll();
    infoPnl.classList.add("visible");
    banner.textContent = "Uitleg proef · Lessons learned · Analyse resultaten 2021";
    document.getElementById("alert-badge").textContent = "ℹ Info";
    document.getElementById("alert-badge").style.background = "#00695c";
    document.body.className = "";
    loadInfoKpis();
    return;
  }

  if (year === "ensemble") {
    hideAll();
    ensemblePnl.classList.add("visible");
    banner.textContent = "Ensemble AI · 5 neerslag-scenario's (×0.70–×1.30) · Qwen2.5-32B interpretatie";
    document.getElementById("alert-badge").textContent = "🎲 Ensemble";
    document.getElementById("alert-badge").style.background = "#e65100";
    document.body.className = "";
    loadEnsemble();
    return;
  }

  if (year === "multimodel") {
    hideAll();
    document.getElementById("multimodel-panel").classList.add("visible");
    banner.textContent = "Multimodel · Rijn/IJssel netwerk → AI → wflow droogte-ensemble";
    document.getElementById("alert-badge").textContent = "🌐 Multimodel";
    document.getElementById("alert-badge").style.background = "#1565c0";
    document.body.className = "";
    loadMultimodel();
    return;
  }

  if (year === "fews") {
    hideAll();
    document.getElementById("fews-panel").classList.add("visible");
    banner.textContent = "FEWS PI REST · Waterlab als FEWS-service · fewspiservice/v1 · vier endpoints · PI JSON";
    document.getElementById("alert-badge").textContent = "🔌 FEWS";
    document.getElementById("alert-badge").style.background = "#004d40";
    document.body.className = "";
    loadFewsChart();
    return;
  }

  if (year === "grondwater") {
    hideAll();
    document.getElementById("grondwater-panel").classList.add("visible");
    banner.textContent = "Grondwater ↔ IJssel · BRO GLD-putten Veluwe-oostflank · lag-correlatie · Qwen2.5-32B";
    document.getElementById("alert-badge").textContent = "💧 Grondwater";
    document.getElementById("alert-badge").style.background = "#00838f";
    document.body.className = "";
    loadGrondwater();
    return;
  }

  if (year === "arch") {
    hideAll();
    document.getElementById("arch-panel").classList.add("visible");
    banner.textContent = "Platform Visie  ·  API-first · AI-orchestrated · Domain-agnostic  ·  van Waterlab naar platform";
    document.getElementById("alert-badge").textContent = "🏗 Platform";
    document.getElementById("alert-badge").style.background = "#004d40";
    document.body.className = "";
    return;
  }

  if (year === "roadmap") {
    hideAll();
    document.getElementById("roadmap-panel").classList.add("visible");
    banner.textContent = "Backlog & POC's  ·  FEWS · SOBEK · D-FLOW FM · EnKF · KNMI'23  ·  Deltares ecosysteem";
    document.getElementById("alert-badge").textContent = "🔬 Roadmap";
    document.getElementById("alert-badge").style.background = "#4a148c";
    document.body.className = "";
    return;
  }

  if (year === "pocs") {
    hideAll();
    document.getElementById("pocs-panel").classList.add("visible");
    banner.textContent = "Waterlab · negen proeven · POC's · hydrologische modellering + AI";
    document.getElementById("alert-badge").textContent = "🧪 POC's";
    document.getElementById("alert-badge").style.background = "#004d40";
    document.body.className = "";
    return;
  }

  if (year === "uitleg") {
    hideAll();
    uitlegPnl.classList.add("visible");
    banner.textContent = "Uitleg & Achtergrond  ·  IJssel-systeem  ·  Wflow SBM  ·  ERA5";
    document.getElementById("alert-badge").textContent = "📖 Uitleg";
    document.getElementById("alert-badge").style.background = "#01579b";
    document.body.className = "";
    return;
  }

  // simulatie-view
  simView.style.display = "";
  infoPnl.classList.remove("visible");
  uitlegPnl.classList.remove("visible");
  forecastPnl.classList.remove("visible");
  ensemblePnl.classList.remove("visible");
  const mmPnlSim = document.getElementById("multimodel-panel");
  if (mmPnlSim) mmPnlSim.classList.remove("visible");
  const fewsPnlSim = document.getElementById("fews-panel");
  if (fewsPnlSim) fewsPnlSim.classList.remove("visible");

  const cfg = YEAR_CONFIG[year];
  document.body.className = cfg.themeClass;
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

    // Gemeten data optioneel (alleen 2021)
    let measured = null;
    if (year === "2021") {
      try {
        measured = await fetch(`${API}/api/${year}/measured`).then(r => r.ok ? r.json() : null);
      } catch (_) {}
    }

    renderKpis(kpis, tsW, cfg);
    renderChart(tsK, tsW, days, cfg, measured);
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

function renderChart(tsK, tsW, days, cfg, measured) {
  const [r, g, b] = cfg.accentColor;

  const traces = [
    {
      x: tsK.dates, y: tsK.q,
      type: "scatter", mode: "lines",
      name: "Gesimuleerd Kampen (m³/s)",
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
      y: Array(tsK.dates.length).fill(cfg.threshold ?? DISCHARGE_THRESHOLD),
      type: "scatter", mode: "lines",
      name: cfg.thresholdLabel ?? "Drempel 1500 m³/s",
      line: { color: "#ff9800", width: 1, dash: "dash" },
      yaxis: "y",
    },
  ];

  // Gemeten data voor 2021: Westervoort (IJssel) en Lobith (Rijn)
  if (measured) {
    if (measured.westervoort) {
      traces.push({
        x: measured.westervoort.dates, y: measured.westervoort.q,
        type: "scatter", mode: "lines",
        name: "Gemeten Westervoort m³/s (RWS)",
        line: { color: "#80cbc4", width: 2, dash: "dashdot" },
        yaxis: "y",
      });
    }
    if (measured.lobith) {
      traces.push({
        x: measured.lobith.dates, y: measured.lobith.q,
        type: "scatter", mode: "lines",
        name: "Gemeten Lobith m³/s (Rijn totaal)",
        line: { color: "#90caf9", width: 1.5, dash: "dot" },
        yaxis: "y3",
      });
    }
  }

  const hasLobith = measured && measured.lobith;

  Plotly.react("chart", traces, {
    paper_bgcolor: "#080c14",
    plot_bgcolor:  "#0d1b2a",
    font:   { color: "#e0e0e0", size: 11 },
    margin: { t: 10, b: 40, l: 60, r: hasLobith ? 80 : 60 },
    legend: { orientation: "h", y: -0.3 },
    xaxis: { gridcolor: "#1a3a5c", tickformat: "%d %b" },
    yaxis: {
      title: "Debiet IJssel (m³/s)", gridcolor: "#1a3a5c",
      titlefont: { color: `rgb(${r},${g},${b})` },
      tickfont:  { color: `rgb(${r},${g},${b})` },
    },
    yaxis2: {
      title: "Waterpeil (m+NAP)", overlaying: "y", side: "right",
      titlefont: { color: "#4caf50" }, tickfont: { color: "#4caf50" },
      gridcolor: "rgba(0,0,0,0)",
      position: hasLobith ? 0.85 : 1.0,
    },
    ...(hasLobith ? {
      yaxis3: {
        title: "Rijn Lobith (m³/s)", overlaying: "y", side: "right",
        titlefont: { color: "#90caf9" }, tickfont: { color: "#90caf9" },
        gridcolor: "rgba(0,0,0,0)",
      },
    } : {}),
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
          { name: "Kampen",      coords: [5.921, 52.555], color: [244, 67, 54] },
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

// ── forecast tab ─────────────────────────────────────────────────────────────

const ALERT_LABELS = {
  normaal:   { text: "Normaal",   color: "#4caf50" },
  waakzaam:  { text: "Waakzaam",  color: "#ff9800" },
  verhoogd:  { text: "Verhoogd",  color: "#f44336" },
  hoog:      { text: "HOOG",      color: "#b71c1c" },
};

async function loadForecast() {
  const badge = document.getElementById("alert-badge");
  badge.textContent = "⏳ Ophalen...";
  badge.style.background = "#555";

  try {
    const data = await fetch(`${API}/api/forecast`).then(r => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
    renderForecastKpis(data);
    renderForecastChart(data);
    renderForecastPrecip(data);

    const al = ALERT_LABELS[data.alert] || ALERT_LABELS.normaal;
    badge.textContent = `🌊 ${al.text}`;
    badge.style.background = al.color;

    loadForecastIntervention();

    const src = document.getElementById("forecast-source");
    const src_str = data.data_available
      ? `RWS Waterinfo · Open-Meteo · gegenereerd ${data.generated_at}`
      : `⚠ RWS niet beschikbaar — model op standaard · Open-Meteo · ${data.generated_at}`;
    if (src) src.textContent = src_str;
  } catch (err) {
    badge.textContent = "Verwachting niet beschikbaar";
    badge.style.background = "#555";
    console.warn("forecast load failed:", err);
  }
}

function renderForecastKpis(d) {
  const k = d.kpis;
  const hStr = k.current_h_kampen_m !== null
    ? ` · ${k.current_h_kampen_m.toLocaleString("nl-NL", {minimumFractionDigits:2})} m+NAP`
    : "";
  document.getElementById("fval-now").textContent    = k.current_q_kampen.toLocaleString("nl-NL") + " m³/s";
  document.getElementById("fkpi-now").querySelector(".sub").textContent = "m³/s routing" + hStr;
  document.getElementById("fval-peak").textContent   = k.peak_forecast_q.toLocaleString("nl-NL") + " m³/s";
  document.getElementById("fsub-peak").textContent   = `piek verwacht ${k.peak_forecast_date}`;
  document.getElementById("fval-precip").textContent = k.total_precip_14d.toLocaleString("nl-NL") + " mm";
  const al = ALERT_LABELS[d.alert] || ALERT_LABELS.normaal;
  const alertEl = document.getElementById("fval-alert");
  alertEl.textContent = al.text;
  alertEl.style.color = al.color;
  document.getElementById("fsub-alert").textContent =
    k.days_above_threshold > 0
      ? `${k.days_above_threshold} dag(en) boven 1500 m³/s`
      : "onder drempel 1500 m³/s";
}

function renderForecastChart(d) {
  const today     = d.generated_at;
  const measDates = d.measured.dates;
  const fDates    = d.forecast.dates;
  const allX0     = measDates[0];
  const allX1     = fDates[fDates.length - 1];

  const hasH = d.measured.h_kampen_m && d.measured.h_kampen_m.some(v => v !== null);
  const hasRwsFcast = d.rws_forecast && d.rws_forecast.dates && d.rws_forecast.dates.length > 0;

  const traces = [
    // Onzekerheidsband debiet (laag → hoog, fill)
    {
      x: fDates, y: d.forecast.q_low,
      type: "scatter", mode: "lines", line: { width: 0 },
      showlegend: false, hoverinfo: "skip", yaxis: "y",
    },
    {
      x: fDates, y: d.forecast.q_high,
      type: "scatter", mode: "lines", line: { width: 0 },
      fill: "tonexty", fillcolor: "rgba(77,182,172,0.15)",
      name: "Onzekerheidsband ±", hoverinfo: "skip", yaxis: "y",
    },
    // Gemeten Westervoort Q
    {
      x: measDates, y: d.measured.q_westervoort,
      type: "scatter", mode: "lines",
      name: "Debiet Westervoort (m³/s)",
      line: { color: "#ff9800", width: 1.5, dash: "dot" },
      yaxis: "y",
    },
    // Gemeten Q Kampen (routing)
    {
      x: measDates, y: d.measured.q_kampen,
      type: "scatter", mode: "lines",
      name: "Debiet Kampen routing (m³/s)",
      line: { color: "#4db6ac", width: 2 },
      yaxis: "y",
    },
    // Statistisch debiet-forecast
    {
      x: fDates, y: d.forecast.q_mid,
      type: "scatter", mode: "lines",
      name: "Verwacht debiet Kampen",
      line: { color: "#4db6ac", width: 2, dash: "dash" },
      yaxis: "y",
    },
    // Drempel 1500 m³/s
    {
      x: [allX0, allX1], y: [1500, 1500],
      type: "scatter", mode: "lines",
      name: "Drempel 1500 m³/s",
      line: { color: "#f44336", width: 1, dash: "dash" },
      hoverinfo: "skip", yaxis: "y",
    },
  ];

  // Gemeten waterpeil Kampen (rechter y-as)
  if (hasH) {
    traces.push({
      x: measDates,
      y: d.measured.h_kampen_m,
      type: "scatter", mode: "lines",
      name: "Waterpeil Kampen (m+NAP)",
      line: { color: "#4caf50", width: 1.5, dash: "dot" },
      yaxis: "y2", connectgaps: true,
    });
  }
  // RWS officiële waterstandsverwachting
  if (hasRwsFcast) {
    traces.push({
      x: d.rws_forecast.dates,
      y: d.rws_forecast.values_m,
      type: "scatter", mode: "lines+markers",
      name: "RWS verwachting peil",
      line: { color: "#81c784", width: 2 },
      marker: { size: 5 },
      yaxis: "y2",
    });
  }

  const layout = {
    paper_bgcolor: "#080c14",
    plot_bgcolor:  "#0d1b2a",
    font:   { color: "#e0e0e0", size: 11 },
    margin: { t: 8, b: 36, l: 58, r: hasH ? 58 : 14 },
    legend: { orientation: "h", y: -0.28, font: { size: 10 } },
    xaxis: {
      gridcolor: "#1a3a5c", tickformat: "%d %b",
      range: [allX0, allX1],
    },
    yaxis: {
      title: "Debiet (m³/s)", gridcolor: "#1a3a5c",
      titlefont: { color: "#4db6ac" }, tickfont: { color: "#4db6ac" },
    },
    ...(hasH ? {
      yaxis2: {
        title: "Peil (m+NAP)", overlaying: "y", side: "right",
        titlefont: { color: "#4caf50" }, tickfont: { color: "#4caf50" },
        gridcolor: "rgba(0,0,0,0)",
      },
    } : {}),
    shapes: [{
      type: "line", x0: today, x1: today,
      yref: "paper", y0: 0, y1: 1,
      line: { color: "#4fc3f7", width: 1, dash: "dot" },
    }],
    annotations: [{
      x: today, yref: "paper", y: 1.0, text: "vandaag",
      showarrow: false, font: { size: 9, color: "#4fc3f7" },
      xanchor: "left", yanchor: "top",
    }],
  };

  Plotly.react("forecast-chart", traces, layout, { responsive: true, displayModeBar: false });
}

function renderForecastPrecip(d) {
  const today = d.generated_at;
  const traces = [
    {
      x: d.precip.past_dates, y: d.precip.past_values,
      type: "bar", name: "Neerslag gemeten (ERA5)",
      marker: { color: "rgba(100,130,160,0.7)" },
    },
    {
      x: d.precip.forecast_dates, y: d.precip.forecast_values,
      type: "bar", name: "Neerslag verwacht (IFS)",
      marker: { color: "rgba(77,182,172,0.7)" },
    },
  ];
  Plotly.react("forecast-precip", traces, {
    paper_bgcolor: "#080c14",
    plot_bgcolor:  "#0d1b2a",
    font:   { color: "#e0e0e0", size: 10 },
    margin: { t: 4, b: 36, l: 58, r: 14 },
    legend: { orientation: "h", y: -0.38, font: { size: 10 } },
    barmode: "overlay",
    xaxis: {
      gridcolor: "#1a3a5c", tickformat: "%d %b",
      range: [d.measured.dates[0], d.forecast.dates[d.forecast.dates.length - 1]],
    },
    yaxis: {
      title: "Neerslag (mm/dag)", gridcolor: "#1a3a5c",
      titlefont: { color: "#4db6ac" }, tickfont: { color: "#4db6ac" },
      autorange: "reversed",
    },
    shapes: [{
      type: "line", x0: today, x1: today,
      yref: "paper", y0: 0, y1: 1,
      line: { color: "#4fc3f7", width: 1, dash: "dot" },
    }],
  }, { responsive: true, displayModeBar: false });
}

// ── info-tab KPI's dynamisch laden ────────────────────────────────────────────

async function loadInfoKpis() {
  try {
    const [synth, real] = await Promise.all([
      fetch(`${API}/api/2021synth/kpis`).then(r => r.ok ? r.json() : null),
      fetch(`${API}/api/2021/kpis`).then(r => r.ok ? r.json() : null),
    ]);
    if (synth) {
      document.getElementById("cmp-synth-peak").textContent =
        synth.peak_q.toLocaleString("nl-NL") + " m³/s";
      document.getElementById("cmp-synth-date").textContent =
        synth.peak_date;
      document.getElementById("cmp-synth-days").textContent =
        synth.days_above_threshold;
    }
    if (real) {
      document.getElementById("cmp-real-peak").textContent =
        real.peak_q.toLocaleString("nl-NL") + " m³/s";
      document.getElementById("cmp-real-date").textContent =
        real.peak_date;
      document.getElementById("cmp-real-days").textContent =
        real.days_above_threshold;
    }
  } catch (_) {}
}

async function loadForecastIntervention() {
  const el = document.getElementById("forecast-llm-text");
  try {
    const data = await fetch(`${API}/api/forecast/intervention`).then(r => r.json());
    if (data.available && data.intervention) {
      el.innerHTML = data.intervention.replace(/\n/g, "<br>");
    } else {
      el.innerHTML = "<span class=\"llm-loading\">Geen AI-interventie beschikbaar</span>";
    }
    const gwEl = document.getElementById("forecast-gw-context");
    if (gwEl) {
      const gw = data.groundwater;
      if (gw && gw.wells && gw.wells.length) {
        const wells = gw.wells.map(w =>
          `${w.bro_id} (laatste meting ${w.last_date}: ${w.last_value} m, 90-d trend ${w.trend_90d >= 0 ? "+" : ""}${w.trend_90d} m)`
        ).join(" · ");
        gwEl.innerHTML = `💧 Grondwater-context (Veluwe-oostflank, BRO GLD): ${wells} — gekalibreerde koppeling IJsselpeil → grondwater: lag ~${gw.lag_days} d, r≈${gw.r}.`;
      } else {
        gwEl.innerHTML = "";
      }
    }
  } catch (_) {
    el.innerHTML = "<span class=\"llm-loading\">AI-interventie niet beschikbaar</span>";
  }
}

// ── ensemble tab ──────────────────────────────────────────────────────────────

/* ── Proef 9 · Grondwater ↔ IJssel (WL-BRO-1) ─────────────────────────────── */
async function loadGrondwater() {
  const unavail = document.getElementById("grondwater-unavailable");
  const content = document.getElementById("grondwater-content");
  const llmEl   = document.getElementById("gw-llm-text");
  try {
    llmEl.innerHTML = "<span class=\"llm-loading\">AI-duiding laden (Qwen2.5-32B lokaal, ~1 min)…</span>";
    const data = await fetch(`${API}/api/grondwater`).then(r => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
    if (!data.available) {
      unavail.style.display = ""; content.style.display = "none"; return;
    }
    unavail.style.display = "none"; content.style.display = "";
    renderGrondwaterKpis(data);
    renderGrondwaterChart(data);
    renderGrondwaterTable(data);
    loadGrondwaterInterpretation();  // trage Qwen-call apart, grafiek staat al
  } catch (err) {
    unavail.style.display = ""; content.style.display = "none";
    console.warn("grondwater load failed:", err);
  }
}

async function loadGrondwaterInterpretation() {
  const llmEl = document.getElementById("gw-llm-text");
  try {
    const d = await fetch(`${API}/api/grondwater/interpretation`).then(r => r.json());
    if (d.interpretation) {
      llmEl.innerHTML = d.interpretation.replace(/\n/g, "<br>");
    } else {
      llmEl.innerHTML = "<span class=\"llm-loading\">Geen AI-duiding beschikbaar (lokale LLM offline)</span>";
    }
  } catch (err) {
    llmEl.innerHTML = "<span class=\"llm-loading\">AI-duiding niet beschikbaar</span>";
    console.warn("grondwater interpretation failed:", err);
  }
}

function renderGrondwaterKpis(d) {
  const rs   = d.wells.map(w => w.r).filter(x => x != null);
  const lags = d.wells.map(w => w.lag_days).filter(x => x != null);
  const meanR   = rs.length   ? rs.reduce((a, b) => a + b, 0) / rs.length : null;
  const meanLag = lags.length ? Math.round(lags.reduce((a, b) => a + b, 0) / lags.length) : null;
  const h = d.river.h.filter(x => x != null);
  document.getElementById("gw-kpi-window").textContent    = d.window.start + " – " + d.window.end;
  document.getElementById("gw-kpi-riverdrop").textContent = h.length ? (h[0].toFixed(2) + " → " + h[h.length - 1].toFixed(2) + " m") : "—";
  document.getElementById("gw-kpi-r").textContent         = meanR   != null ? meanR.toFixed(2) : "—";
  document.getElementById("gw-kpi-lag").textContent       = meanLag != null ? (meanLag + " d") : "—";
}

function renderGrondwaterChart(d) {
  const colors = ["#4dd0e1", "#4db6ac", "#81c784", "#ffb74d", "#ba68c8"];
  const traces = d.wells.map((w, i) => ({
    x: w.series.dates, y: w.series.values, type: "scatter", mode: "lines",
    name: w.bro_id.replace("GLD0000000", "GLD…") + " · lag " + w.lag_days + "d (r " + w.r + ")",
    line: { color: colors[i % colors.length], width: 1.8 }, yaxis: "y",
  }));
  traces.push({
    x: d.river.dates, y: d.river.h, type: "scatter", mode: "lines",
    name: "IJssel-peil Kampen", line: { color: "#ef5350", width: 2.5, dash: "dash" }, yaxis: "y2",
  });
  Plotly.react("grondwater-chart", traces, {
    paper_bgcolor: "#080c14", plot_bgcolor: "#0d1b2a",
    font: { color: "#e0e0e0", size: 11 }, margin: { t: 8, b: 40, l: 58, r: 58 },
    legend: { orientation: "h", y: -0.3, font: { size: 9 } },
    xaxis: { gridcolor: "#1a3a5c", tickformat: "%d %b" },
    yaxis: { title: "Grondwaterstand (m)", gridcolor: "#1a3a5c",
             titlefont: { color: "#4dd0e1" }, tickfont: { color: "#4dd0e1" } },
    yaxis2: { title: "IJssel-peil (m+NAP)", overlaying: "y", side: "right", showgrid: false,
              titlefont: { color: "#ef5350" }, tickfont: { color: "#ef5350" } },
  }, { responsive: true, displayModeBar: false });
}

function renderGrondwaterTable(d) {
  document.getElementById("gw-table-body").innerHTML = d.wells.map(w =>
    `<tr><td><code>${w.bro_id}</code></td><td>${w.lat}, ${w.lon}</td>` +
    `<td>${w.gw_first} → ${w.gw_last} m</td>` +
    `<td>${w.lag_days != null ? w.lag_days + " d" : "—"}</td>` +
    `<td>${w.r != null ? w.r : "—"}</td></tr>`).join("");
}

async function loadEnsemble() {
  const unavail  = document.getElementById("ensemble-unavailable");
  const content  = document.getElementById("ensemble-content");
  const llmEl    = document.getElementById("ens-llm-text");

  try {
    const data = await fetch(`${API}/api/ensemble`).then(r => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });

    if (!data.available) {
      unavail.style.display = "";
      content.style.display = "none";
      return;
    }

    unavail.style.display = "none";
    content.style.display = "";

    renderEnsembleKpis(data);
    renderEnsembleChart(data);
    renderEnsembleScenarios(data);

    if (data.interpretation) {
      llmEl.innerHTML = data.interpretation.replace(/\n/g, "<br>");
    } else {
      llmEl.innerHTML = "<span class=\"llm-loading\">Geen AI-interpretatie beschikbaar</span>";
    }
  } catch (err) {
    unavail.style.display = "";
    content.style.display = "none";
    console.warn("ensemble load failed:", err);
  }
}

function renderEnsembleKpis(d) {
  const qs       = d.scenarios.map(s => s.peak_q);
  const qMin     = Math.min(...qs);
  const qMax     = Math.max(...qs);
  const baseline = d.scenarios.find(s => Math.abs(s.multiplier - 1.0) < 0.01) || d.scenarios[2];

  document.getElementById("ens-kpi-range").textContent =
    `${qMin.toLocaleString("nl-NL")} – ${qMax.toLocaleString("nl-NL")} m³/s`;
  document.getElementById("ens-kpi-baseline").textContent =
    `${baseline.peak_q.toLocaleString("nl-NL")} m³/s`;

  const ts     = d.timeseries;
  const spread = Math.round(Math.max(...ts.q_p90) - Math.min(...ts.q_p10));
  document.getElementById("ens-kpi-spread").textContent =
    spread.toLocaleString("nl-NL") + " m³/s";

  const maxMeanIdx  = ts.q_mean.indexOf(Math.max(...ts.q_mean));
  const hotspotDate = ts.dates[maxMeanIdx];
  document.getElementById("ens-kpi-hotspot").textContent =
    new Date(hotspotDate + "T12:00:00Z").toLocaleDateString("nl-NL",
      { day: "numeric", month: "short", year: "numeric" });
}

function renderEnsembleChart(d) {
  const ts = d.timeseries;
  const x0 = ts.dates[0];
  const x1 = ts.dates[ts.dates.length - 1];

  const traces = [
    { x: ts.dates, y: ts.q_p10, type: "scatter", mode: "lines",
      line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
    { x: ts.dates, y: ts.q_p90, type: "scatter", mode: "lines",
      line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(255,183,77,0.15)",
      name: "P10–P90 band", hoverinfo: "skip" },
    { x: ts.dates, y: ts.q_p10, type: "scatter", mode: "lines",
      name: "P10 (droog)", line: { color: "#ffe082", width: 1, dash: "dot" } },
    { x: ts.dates, y: ts.q_p90, type: "scatter", mode: "lines",
      name: "P90 (nat)", line: { color: "#ff6d00", width: 1, dash: "dot" } },
    { x: ts.dates, y: ts.q_mean, type: "scatter", mode: "lines",
      name: "Ensemble gemiddelde", line: { color: "#ffb74d", width: 2.5 } },
    { x: [x0, x1], y: [1500, 1500], type: "scatter", mode: "lines",
      name: "Drempel 1500 m³/s",
      line: { color: "#f44336", width: 1, dash: "dash" }, hoverinfo: "skip" },
  ];

  Plotly.react("ensemble-chart", traces, {
    paper_bgcolor: "#080c14",
    plot_bgcolor:  "#0d1b2a",
    font:   { color: "#e0e0e0", size: 11 },
    margin: { t: 8, b: 36, l: 58, r: 14 },
    legend: { orientation: "h", y: -0.28, font: { size: 10 } },
    xaxis: { gridcolor: "#1a3a5c", tickformat: "%d %b" },
    yaxis: {
      title: "Debiet (m³/s)", gridcolor: "#1a3a5c",
      titlefont: { color: "#ffb74d" }, tickfont: { color: "#ffb74d" },
    },
  }, { responsive: true, displayModeBar: false });
}

function renderEnsembleScenarios(d) {
  const rows = d.scenarios.map(sc => {
    const isBase = Math.abs(sc.multiplier - 1.0) < 0.01;
    return `<tr class="${isBase ? "sc-baseline" : ""}">
      <td>${sc.name}</td>
      <td>×${sc.multiplier.toFixed(2)}</td>
      <td>${sc.peak_q.toLocaleString("nl-NL")} m³/s</td>
      <td>${sc.peak_date}</td>
      <td>${sc.days_above}</td>
    </tr>`;
  });
  document.getElementById("ens-scenario-tbody").innerHTML = rows.join("");
}

let mmLeafletMap = null;

async function loadMultimodel() {
  const unavail = document.getElementById("multimodel-unavailable");
  const content = document.getElementById("multimodel-content");
  try {
    const resp = await fetch("/api/multimodel");
    const data = await resp.json();
    if (!data.available) {
      unavail.style.display = "block";
      content.style.display = "none";
      return;
    }
    unavail.style.display = "none";
    content.style.display = "block";
    renderMultimodelMap(data);
    document.getElementById("mm-trigger-reason").textContent =
      data.orchestrator.trigger_reason;
    document.getElementById("mm-llm-text").textContent =
      data.orchestrator.llm_explanation;
    renderMultimodelChart(data);
    renderMultimodelScenarios(data);
  } catch (e) {
    unavail.style.display = "block";
    content.style.display = "none";
  }
}

function renderMultimodelMap(d) {
  if (mmLeafletMap) {
    mmLeafletMap.remove();
    mmLeafletMap = null;
  }
  mmLeafletMap = L.map("multimodel-map").setView([52.1, 5.9], 8);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap"
  }).addTo(mmLeafletMap);

  const rivers = [
    [[51.862, 6.112], [51.850, 6.000], [51.960, 5.970]],
    [[51.960, 5.970], [52.252, 6.157], [52.555, 5.921]],
    [[51.960, 5.970], [51.960, 5.800], [51.900, 5.000]],
  ];
  rivers.forEach(r => L.polyline(r, {color: "#1565c0", weight: 3, opacity: 0.7})
    .addTo(mmLeafletMap));

  const criticalNode = d.ribasim.critical_node;
  d.ribasim.nodes.forEach(node => {
    const deficit = node.deficit_pct;
    const color   = deficit > 50 ? "#d32f2f" : deficit > 20 ? "#f57c00" : "#388e3c";
    const isCrit  = node.name === criticalNode;
    const circle  = L.circleMarker([node.lat, node.lon], {
      radius:      isCrit ? 14 : 10,
      fillColor:   color,
      color:       isCrit ? "#000" : "#fff",
      weight:      isCrit ? 3 : 1,
      fillOpacity: 0.85,
    }).addTo(mmLeafletMap);
    circle.bindPopup(
      `<b>${node.name}</b><br>` +
      `Peil: ${node.mean_level.toFixed(3)} m NAP<br>` +
      `Drempel: ${node.threshold_level} m<br>` +
      `Deficit: <b>${node.deficit_pct.toFixed(1)}%</b>` +
      (isCrit ? "<br><b>⚠ Kritieke knoop</b>" : "")
    );
  });

  L.marker([51.862, 6.112])
    .bindPopup("<b>Lobith</b><br>Bovenstroomse inflow")
    .addTo(mmLeafletMap);
}

function renderMultimodelChart(d) {
  const ts = d.ensemble.timeseries;
  const traces = [
    {x: ts.dates, y: ts.q_p10,  name: "P10",  line: {color: "#90caf9", dash: "dash"}},
    {x: ts.dates, y: ts.q_mean, name: "Gemiddeld", line: {color: "#1565c0", width: 2}},
    {x: ts.dates, y: ts.q_p90,  name: "P90",  line: {color: "#ef9a9a", dash: "dash"}},
  ];
  Plotly.newPlot("mm-ensemble-chart", traces, {
    margin: {t: 10, b: 40, l: 50, r: 10},
    yaxis:  {title: "Afvoer (m³/s)"},
    legend: {orientation: "h"},
    paper_bgcolor: "transparent", plot_bgcolor: "transparent",
  });
}

function renderMultimodelScenarios(d) {
  const tbody = document.getElementById("mm-scenario-tbody");
  tbody.innerHTML = "";
  d.ensemble.scenarios.forEach(s => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${s.name}</td><td>×${s.multiplier.toFixed(2)}</td>` +
      `<td>${s.peak_q}</td><td>${s.peak_date}</td><td>${s.days_above}</td>`;
    tbody.appendChild(tr);
  });
}

// ── FEWS PI REST tab ──────────────────────────────────────────────────────────

const FEWS_BASE = "/fews/rest/fewspiservice/v1";

async function fewsFetch(type) {
  document.querySelectorAll(".fews-ep-btn").forEach(b => b.classList.remove("active"));
  const btn = document.getElementById(`fews-btn-${type}`);
  if (btn) btn.classList.add("active");

  const pre = document.getElementById("fews-json-out");
  pre.textContent = "laden...";

  try {
    let url = `${FEWS_BASE}/${type}`;
    if (type === "timeseries") {
      const loc    = document.getElementById("fews-loc")?.value    || "KAMPEN";
      const period = document.getElementById("fews-period")?.value || "1995";
      url += `?filterId=Waterlab-IJssel&locationIds=${loc}&parameterIds=Q.sim&period=${period}`;
    } else {
      url += "?filterId=Waterlab-IJssel";
    }
    const data = await fetch(url).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    });
    pre.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    pre.textContent = `Fout: ${err}`;
  }
}

async function loadFewsChart() {
  const loc    = document.getElementById("fews-loc")?.value    || "KAMPEN";
  const period = document.getElementById("fews-period")?.value || "1995";

  try {
    const data = await fetch(`/api/fews/data?location=${loc}&period=${period}`).then(r => r.json());
    renderFewsChart(data);
  } catch (err) {
    console.warn("fews chart load failed:", err);
  }
}

function renderFewsChart(data) {
  const periodLabels = {
    "1995": "Jan 1995 (hoogwater)",
    "2018": "Zomer 2018 (droogte)",
    "2021": "Jul 2021 (hoogwater)",
  };
  const traces = [
    {
      x: data.sim.dates,
      y: data.sim.values,
      name: `Q.sim wflow (${periodLabels[data.period] || data.period})`,
      type: "scatter",
      mode: "lines",
      line: { color: "#4db6ac", width: 2 },
    },
  ];
  if (data.obs.dates.length > 0) {
    traces.push({
      x: data.obs.dates,
      y: data.obs.values,
      name: "Q.meting RWS live (laatste 30 d)",
      type: "scatter",
      mode: "lines",
      line: { color: "#ff8a65", width: 1.5, dash: "dot" },
    });
  }
  Plotly.react("fews-chart", traces, {
    margin: { t: 10, b: 40, l: 55, r: 10 },
    yaxis:  { title: "Afvoer (m³/s)", color: "#90a4ae" },
    xaxis:  { color: "#90a4ae" },
    legend: { orientation: "h", font: { color: "#90a4ae" } },
    paper_bgcolor: "transparent",
    plot_bgcolor:  "transparent",
    font: { color: "#90a4ae" },
  });
}

