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
let validationLoaded = false;   // WL-VAL-1: skill-data 6u server-cached, één keer per sessie laden
let hindcastLoaded   = false;   // WL-VAL-2: hindcast idem (top-level state i.v.m. hash-deeplink TDZ)
let stationTs        = {};      // WL-VIS-1: per station de geladen tijdreeks (kampen/westervoort)
let selectedStation  = null;    // WL-VIS-1: welk netwerkpunt is aangeklikt
let chatToken        = null;    // WL-CHAT-1: sessie-token (top-level state i.v.m. hash-deeplink TDZ)
let chatHistory      = [];      // WL-CHAT-1: gespreksgeschiedenis (voor context)
let currentFewsRun   = null;    // POC via FEWS: actieve run (top-level i.v.m. hash-deeplink TDZ)
let fewsRunInit      = false;   // eerste-load-guard voor de FEWS-run-tab
const FEWS_PI_BASE   = "/fews/rest/fewspiservice/v1";
const FEWS_RUN_LABELS = { "1995": "Hoogwater 1995", "2018": "Droogte 2018", "2021": "Hoogwater 2021" };
let assimilationLoaded = false;   // POC E: 6u server-cache, één keer per sessie laden (TDZ-veilig)

// WL-VIS-1 · netwerkpunten met data (= waar wflow een uitspraak over doet)
const STATIONS = {
  Kampen: {
    coords: [5.921, 52.555], color: [244, 67, 54],
    role: "Uitstroompunt van de IJssel naar het Ketelmeer/IJsselmeer. wflow doet hier een uitspraak over debiet (m³/s) en rivierwaterdiepte (m).",
  },
  Westervoort: {
    coords: [6.154, 51.987], color: [255, 152, 0],
    role: "Instroompunt: de IJssel-tak net na de Pannerdense Kop — de bovenstroomse randvoorwaarde van het model (zie WL-PROV-2).",
  },
};

// ── kaart ─────────────────────────────────────────────────────────────────────

// Kaart-init in try/catch: faalt WebGL (bv. headless/oude browser), dan blijft
// de rest van het dashboard (data-tabs, grafieken) gewoon werken.
let map = null;
try {
  map = new maplibregl.Map({
    container: "map",
    style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    center: [6.1, 52.4],
    zoom: 9.5,
    pitch: 45,
    bearing: 0,
  });

  map.on("load", () => {
    overlay = new deck.MapboxOverlay({
      layers: [],
      pickingRadius: 8,
      onClick: handleDeckClick,
      getTooltip: deckTooltip,
    });
    map.addControl(overlay);
    loadYear("1995");
  });
} catch (err) {
  console.warn("Kaart kon niet initialiseren (WebGL?) — kaart-tabs uitgeschakeld, rest van het dashboard werkt:", err);
}

// ── jaar wisselen ─────────────────────────────────────────────────────────────

document.querySelectorAll(".year-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    const y = btn.dataset.year;
    if (y === currentYear) return;
    history.replaceState(null, "", "#" + y);
    switchYear(y);
  });
});

// Deep-link: open een tab via #hash (bv. /#grondwater) — handig voor delen/embedden.
(function () {
  const h = (location.hash || "").replace(/^#/, "");
  if (h && document.querySelector('.year-tab[data-year="' + h + '"]')) {
    switchYear(h);
  }
})();

// ── Interactieve rondleiding ───────────────────────────────────────────────
const TOUR_STEPS = [
  { year: "handleiding", title: "Handleiding",
    text: "Waterlab draait op één NVIDIA Jetson AGX Orin. API-first: dashboard, FEWS en GraphQL zijn verwisselbare clients op dezelfde data." },
  { year: "uitleg", title: "Rijn & IJssel",
    text: "De IJssel krijgt ~13% van de Rijn via de Pannerdense Kop. Rode draad door alle proeven: het traject Westervoort → Kampen." },
  { year: "forecast", title: "Live verwachting + integrale AI",
    text: "14-daagse debietverwachting uit RWS Waterinfo + Open-Meteo. Claude duidt integraal — óók drinkwater, landbouw en kwel via de grondwater-koppeling." },
  { year: "grondwater", title: "Grondwater ↔ IJssel",
    text: "Gemeten BRO-grondwater vs IJssel-peil: sterke lag-correlatie (r tot 0.94, 6–28 dagen). Scroll voor de vooruitblik — de live verwachting geprojecteerd naar grondwatertrend." },
  { year: "pocs", title: "Negen proeven",
    text: "Elke proef langs drie lijnen: functioneel, technisch, opvolging. Van ensemble-AI en multimodel-pipeline tot FEWS en grondwater." },
  { year: "fews", title: "Interoperabel — FEWS",
    text: "Dezelfde data ook als Deltares PI REST 1.25. Tip: open ook /graphql voor één query die station, verwachting én nabije grondwaterputten stitcht." },
];
let tourIdx = -1;
let tourTimer = null;
const TOUR_MS = 9000;

function tourShow(i) {
  if (i < 0) i = 0;
  if (i >= TOUR_STEPS.length) { tourStop(); return; }
  tourIdx = i;
  const s = TOUR_STEPS[i];
  switchYear(s.year);
  const ov = document.getElementById("tour-overlay");
  document.getElementById("tour-title").textContent = `Stap ${i + 1}/${TOUR_STEPS.length} · ${s.title}`;
  document.getElementById("tour-text").textContent = s.text;
  document.getElementById("tour-next").textContent = (i === TOUR_STEPS.length - 1) ? "Klaar ✓" : "Volgende ›";
  ov.classList.add("visible");
  clearTimeout(tourTimer);
  tourTimer = setTimeout(() => tourShow(tourIdx + 1), TOUR_MS);  // op laatste stap → tourStop
}
function tourStart() { tourShow(0); }
function tourNext()  { tourShow(tourIdx + 1); }
function tourPrev()  { tourShow(tourIdx - 1); }
function tourStop()  {
  clearTimeout(tourTimer);
  const ov = document.getElementById("tour-overlay");
  if (ov) ov.classList.remove("visible");
  tourIdx = -1;
}

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
    ["multimodel-panel","roadmap-panel","arch-panel","fews-panel","fewsrun-panel","pocs-panel","grondwater-panel","validatie-panel","assimilatie-panel","chat-panel","handleiding-panel"].forEach(id => {
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

  if (year === "fewsrun") {
    hideAll();
    document.getElementById("fewsrun-panel").classList.add("visible");
    banner.textContent = "POC via FEWS · een proef gedraaid als FEWS-client · PI REST 1.25";
    document.getElementById("alert-badge").textContent = "🔌 POC via FEWS";
    document.getElementById("alert-badge").style.background = "#004d40";
    document.body.className = "";
    initFewsRun();
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

  if (year === "chat") {
    hideAll();
    document.getElementById("chat-panel").classList.add("visible");
    banner.textContent = "Vraag het · uitleg-assistent · gegrond in de eigen herkomst-/uitleg-bronnen";
    document.getElementById("alert-badge").textContent = "💬 Vraag het";
    document.getElementById("alert-badge").style.background = "#00695c";
    document.body.className = "";
    initChat();
    return;
  }

  if (year === "assimilatie") {
    hideAll();
    document.getElementById("assimilatie-panel").classList.add("visible");
    banner.textContent = "Data-assimilatie · EnKF-update van de recessie met de RWS-meting · POC E";
    document.getElementById("alert-badge").textContent = "🛰 Assimilatie";
    document.getElementById("alert-badge").style.background = "#00695c";
    document.body.className = "";
    loadAssimilation();
    return;
  }

  if (year === "validatie") {
    hideAll();
    document.getElementById("validatie-panel").classList.add("visible");
    banner.textContent = "Validatie · gesimuleerd vs gemeten per punt · skill-score (NSE · KGE · r · bias)";
    document.getElementById("alert-badge").textContent = "🎯 Validatie";
    document.getElementById("alert-badge").style.background = "#00695c";
    document.body.className = "";
    loadValidation();
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

  // simulatie-view — hideAll() verbergt álle panels (single source of truth),
  // daarna alleen de sim-view tonen. Voorkomt dat een eerder paneel (bv. Handleiding)
  // onder de jaar-tabs (1995/2018/2021) blijft staan.
  hideAll();
  simView.style.display = "";

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

    stationTs = { kampen: tsK, westervoort: tsW };   // WL-VIS-1
    renderKpis(kpis, tsW, cfg);
    renderChart(tsK, tsW, days, cfg, measured);
    if (selectedStation) showStationDetail(selectedStation);   // ander event → ververs detail
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
      name: "Gesimuleerd · debiet Kampen (m³/s)",
      line: { color: `rgb(${r},${g},${b})`, width: 2 },
      yaxis: "y",
      fill: "tozeroy",
      fillcolor: `rgba(${r},${g},${b},0.1)`,
    },
    {
      x: tsK.dates, y: tsK.h_nap,
      type: "scatter", mode: "lines",
      name: "Gesimuleerd · rivierdiepte Kampen (m)",
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
        name: "Gemeten · debiet Westervoort (m³/s, RWS)",
        line: { color: "#80cbc4", width: 2, dash: "dashdot" },
        yaxis: "y",
      });
    }
    if (measured.lobith) {
      traces.push({
        x: measured.lobith.dates, y: measured.lobith.q,
        type: "scatter", mode: "lines",
        name: "Gemeten · debiet Lobith (m³/s, Rijn totaal)",
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
      title: "Rivierdiepte (m)", overlaying: "y", side: "right",
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
  refreshStationCursor();   // WL-VIS-1: schuif de cursor + ververs "hoger/lager dan normaal"
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
        data: Object.entries(STATIONS).map(([name, s]) => ({ name, coords: s.coords, color: s.color })),
        getPosition:   d => d.coords,
        getFillColor:  d => (d.name === selectedStation ? [79, 195, 247] : d.color),
        getLineColor:  [255, 255, 255],
        getLineWidth:  2,
        lineWidthMinPixels: 2,
        stroked:       true,
        getRadius:     d => (d.name === selectedStation ? 1100 : 850),
        radiusMinPixels: 7,
        pickable:      true,
      }),
    ],
  });
}

// ── WL-VIS-1 · klikbare netwerkpunten + tooltip ────────────────────────────────
const _TOOLTIP_STYLE = {
  background: "#07131e", color: "#cfd8dc", fontSize: "11px",
  maxWidth: "240px", padding: "8px 10px", border: "1px solid #1a3a5c",
  borderRadius: "6px", lineHeight: "1.5",
};

function deckTooltip(info) {
  if (!info || !info.object) return null;
  if (info.layer && info.layer.id === "stations") {
    const s = STATIONS[info.object.name] || {};
    return { html: `<b>${info.object.name}</b><br>${s.role || ""}<br><i>Klik voor de detailgrafiek.</i>`,
             style: _TOOLTIP_STYLE };
  }
  const q = info.object.q;          // river-q cel
  if (q == null) return null;
  const h = info.object.h;
  return { html: `<b>Riviercel (wflow ~1 km)</b><br>Debiet: ${Math.round(q)} m³/s` +
                 (h != null ? `<br>Rivierdiepte: ${h.toFixed(1)} m` : "") +
                 `<br><i>Eén rastercel waarover het model rekent.</i>`,
           style: _TOOLTIP_STYLE };
}

function handleDeckClick(info) {
  if (info && info.layer && info.layer.id === "stations" && info.object) {
    showStationDetail(info.object.name);
    return true;
  }
  return false;
}

function _stationSeries(name) {
  const ts = stationTs[name.toLowerCase()];
  if (!ts) return null;
  return { dates: ts.dates || [], q: ts.q || [], h: ts.h_nap || ts.h || [] };
}

function _normalBadge(q) {
  const n = q.length;
  if (!n) return { html: "", pct: 0 };
  const mean = q.reduce((a, b) => a + b, 0) / n;
  const i = Math.min(dayIdx, n - 1);
  const cur = q[i];
  const pct = mean ? Math.round((cur - mean) / mean * 100) : 0;
  const up = pct >= 0;
  return {
    html: `<span class="${up ? "sd-high" : "sd-low"}">${up ? "↑" : "↓"} ${Math.abs(pct)}% ` +
          `${up ? "boven" : "onder"} normaal</span> ` +
          `<span style="color:#607d8b">· debiet nu ${Math.round(cur)} m³/s · normaal = gemiddelde over deze periode (${Math.round(mean)} m³/s)</span>`,
    pct,
  };
}

function showStationDetail(name) {
  const host = document.getElementById("station-detail");
  const ser = _stationSeries(name);
  if (!host || !ser) return;
  selectedStation = name;
  host.style.display = "block";
  document.getElementById("sd-title").textContent = `${name} — wat gebeurt hier?`;
  document.getElementById("sd-role").textContent = (STATIONS[name] || {}).role || "";
  document.getElementById("sd-badge").innerHTML = _normalBadge(ser.q).html;
  renderStationDetailChart(ser);
  renderDeckLayers();   // markeer het gekozen punt
}

function renderStationDetailChart(ser) {
  const curDate = ser.dates[Math.min(dayIdx, ser.dates.length - 1)];
  const traces = [
    { x: ser.dates, y: ser.q, type: "scatter", mode: "lines",
      name: "Debiet (m³/s)", line: { color: "#4db6ac", width: 2 }, yaxis: "y" },
    { x: ser.dates, y: ser.h, type: "scatter", mode: "lines",
      name: "Rivierdiepte (m)", line: { color: "#4caf50", width: 1.5, dash: "dot" }, yaxis: "y2" },
  ];
  Plotly.react("station-detail-chart", traces, {
    paper_bgcolor: "#080c14", plot_bgcolor: "#0d1b2a", font: { color: "#e0e0e0", size: 10 },
    margin: { t: 6, b: 28, l: 48, r: 48 }, legend: { orientation: "h", y: -0.3, font: { size: 9 } },
    xaxis: { gridcolor: "#1a3a5c", tickformat: "%d %b" },
    yaxis: { title: "m³/s", gridcolor: "#1a3a5c", titlefont: { color: "#4db6ac" }, tickfont: { color: "#4db6ac" } },
    yaxis2: { title: "m", overlaying: "y", side: "right", gridcolor: "rgba(0,0,0,0)",
              titlefont: { color: "#4caf50" }, tickfont: { color: "#4caf50" } },
    shapes: curDate ? [{ type: "line", x0: curDate, x1: curDate, yref: "paper", y0: 0, y1: 1,
                         line: { color: "#4fc3f7", width: 1, dash: "dot" } }] : [],
  }, { responsive: true, displayModeBar: false });
}

function hideStationDetail() {
  selectedStation = null;
  const host = document.getElementById("station-detail");
  if (host) host.style.display = "none";
  renderDeckLayers();   // deselecteer de bol
}

function refreshStationCursor() {
  if (!selectedStation) return;
  const ser = _stationSeries(selectedStation);
  if (!ser) return;
  const badge = document.getElementById("sd-badge");
  if (badge) badge.innerHTML = _normalBadge(ser.q).html;
  const curDate = ser.dates[Math.min(dayIdx, ser.dates.length - 1)];
  if (curDate) Plotly.relayout("station-detail-chart",
    { "shapes[0].x0": curDate, "shapes[0].x1": curDate });
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

// ── WL-VAL-1 · validatie ───────────────────────────────────────────────────
async function loadValidation() {
  if (validationLoaded) return;          // 6u server-cache; één keer per sessie volstaat
  const cards = document.getElementById("val-cards");
  const matrix = document.getElementById("val-matrix-body");
  const wait = document.getElementById("val-unavailable");
  wait.style.display = "block";
  try {
    const d = await fetch(`${API}/api/validation`).then(r => r.json());
    wait.style.display = "none";
    document.getElementById("val-disclaimer").textContent =
      `${d.disclaimer || ""}  ·  gegenereerd ${d.generated_at || "—"} · ${d.n_validated || 0} punt(en) met meting.`;
    cards.innerHTML = "";
    matrix.innerHTML = "";
    (d.points || []).forEach(p => {
      if (p.available) cards.appendChild(renderValidationCard(p));
      else matrix.insertAdjacentHTML("beforeend",
        `<tr><td><strong style="color:#b0bec5">${p.label}</strong></td>` +
        `<td class="vx">✗ geen meting</td><td style="color:#8aa1ae">${p.reason}</td></tr>`);
    });
    validationLoaded = true;
  } catch (err) {
    wait.textContent = "Validatie niet beschikbaar.";
    console.warn("validation load failed:", err);
  }
  loadHindcast();   // WL-VAL-2 — aparte (tragere) fetch; grafieken erboven staan al
}

async function loadHindcast() {
  if (hindcastLoaded) return;
  const wait = document.getElementById("hindcast-unavailable");
  const content = document.getElementById("hindcast-content");
  wait.style.display = "block";
  try {
    const d = await fetch(`${API}/api/validation/hindcast`).then(r => r.json());
    if (!d.available) {
      wait.textContent = d.reason || "Hindcast niet beschikbaar.";
      return;
    }
    const s = d.summary || {};
    document.getElementById("hindcast-summary").innerHTML =
      `Over <strong>${d.n_forecasts}</strong> uitgegeven verwachtingen (${d.window}): ` +
      `fout (RMSE) op dag 7 ≈ <strong>${s.rmse_day7} ${d.unit}</strong>, dag 14 ≈ <strong>${s.rmse_day14} ${d.unit}</strong>. ` +
      `De onzekerheidsband ving gemiddeld <strong>${s.mean_coverage}%</strong> van de realisaties. ${d.method}`;
    document.getElementById("hindcast-window").textContent = d.window;
    document.getElementById("hindcast-ex-title").textContent =
      `Voorbeeld — verwachting uitgegeven op ${d.example.issue_date}, over de realisatie`;
    renderHindcastExample(d.example, d.unit);
    renderHindcastHorizon(d.per_horizon, d.unit);
    wait.style.display = "none";
    content.style.display = "block";
    hindcastLoaded = true;
  } catch (err) {
    wait.textContent = "Hindcast niet beschikbaar.";
    console.warn("hindcast load failed:", err);
  }
}

function renderHindcastExample(ex, unit) {
  const traces = [
    { x: ex.dates, y: ex.low, type: "scatter", mode: "lines", line: { width: 0 },
      showlegend: false, hoverinfo: "skip" },
    { x: ex.dates, y: ex.high, type: "scatter", mode: "lines", line: { width: 0 },
      fill: "tonexty", fillcolor: "rgba(77,182,172,0.15)", name: "Onzekerheidsband", hoverinfo: "skip" },
    { x: ex.dates, y: ex.pred, type: "scatter", mode: "lines",
      name: "Verwachting (uitgegeven)", line: { color: "#4db6ac", width: 2, dash: "dash" } },
    { x: ex.dates, y: ex.obs, type: "scatter", mode: "lines+markers",
      name: "Realisatie (RWS gemeten)", line: { color: "#4caf50", width: 2 }, marker: { size: 4 } },
  ];
  Plotly.react("hindcast-example-chart", traces, {
    paper_bgcolor: "#080c14", plot_bgcolor: "#0d1b2a",
    font: { color: "#e0e0e0", size: 11 }, margin: { t: 8, b: 34, l: 56, r: 14 },
    legend: { orientation: "h", y: -0.25, font: { size: 10 } },
    xaxis: { gridcolor: "#1a3a5c", tickformat: "%d %b" },
    yaxis: { title: `Debiet (${unit})`, gridcolor: "#1a3a5c" },
  }, { responsive: true, displayModeBar: false });
}

function renderHindcastHorizon(ph, unit) {
  const traces = [
    { x: ph.horizon, y: ph.rmse, type: "scatter", mode: "lines+markers",
      name: "RMSE", line: { color: "#ef5350", width: 2 } },
    { x: ph.horizon, y: ph.bias, type: "scatter", mode: "lines+markers",
      name: "Bias", line: { color: "#ffb74d", width: 2 } },
  ];
  Plotly.react("hindcast-horizon-chart", traces, {
    paper_bgcolor: "#080c14", plot_bgcolor: "#0d1b2a",
    font: { color: "#e0e0e0", size: 11 }, margin: { t: 8, b: 38, l: 56, r: 14 },
    legend: { orientation: "h", y: -0.32, font: { size: 10 } },
    xaxis: { title: "Lead-time (dagen vooruit)", gridcolor: "#1a3a5c", dtick: 1 },
    yaxis: { title: `Fout (${unit})`, gridcolor: "#1a3a5c", zeroline: true, zerolinecolor: "#37474f" },
  }, { responsive: true, displayModeBar: false });
}

function valClass(metric, v) {
  if (v === null || v === undefined) return "val-neutral";
  if (metric === "nse" || metric === "kge" || metric === "r")
    return v >= 0.5 ? "val-good" : (v >= 0 ? "val-mid" : "val-bad");
  return "val-neutral";
}

function scoreBox(label, value, cls, suffix) {
  const shown = (value === null || value === undefined) ? "—" : value + (suffix || "");
  return `<div class="val-score"><div class="vs-label">${label}</div>` +
         `<div class="vs-val ${cls || "val-neutral"}">${shown}</div></div>`;
}

function renderValidationCard(p) {
  const card = document.createElement("div");
  card.className = "val-card";
  const sc = p.scores || {};
  const anom = p.mode === "anomaly";

  let boxes = scoreBox("NSE", sc.nse, valClass("nse", sc.nse))
            + scoreBox("KGE", sc.kge, valClass("kge", sc.kge))
            + scoreBox("Pearson r", sc.r, valClass("r", sc.r));
  if (anom) {
    boxes += scoreBox("Datum-offset", p.datum_offset, "val-bad", " m")
           + scoreBox("Amplitude", sc.amplitude_ratio, "val-bad", "×")
           + scoreBox("RMSE", sc.rmse, "val-neutral", " m");
  } else {
    boxes += scoreBox("Bias", sc.bias, "val-neutral", " " + (p.unit || ""))
           + scoreBox("pBias", sc.pbias, "val-neutral", " %")
           + scoreBox("RMSE", sc.rmse, "val-neutral", " " + (p.unit || ""));
  }
  boxes += scoreBox("n dagen", sc.n, "val-neutral");

  const chartId = `val-chart-${p.id}`;
  card.innerHTML =
    `<div class="val-card-head">` +
      `<h3>${p.label}</h3>` +
      `<span class="val-mode ${anom ? "anomaly" : "absolute"}">${anom ? "dynamiek (geanomaliseerd)" : "absoluut"}</span>` +
      `<span class="val-period">${p.period || ""}</span>` +
    `</div>` +
    `<div class="val-body">` +
      `<div class="val-scores">${boxes}</div>` +
      `<div id="${chartId}" class="val-chart"></div>` +
      `<p class="val-note">${p.note || ""}</p>` +
    `</div>`;

  // grafiek na invoegen in DOM
  setTimeout(() => renderValidationChart(chartId, p), 0);
  return card;
}

function renderValidationChart(id, p) {
  const s = p.series; if (!s) return;
  const yTitle = (p.mode === "anomaly") ? (p.anomaly_unit || "afwijking") : (p.unit || "");
  const traces = [
    { x: s.dates, y: s.obs, type: "scatter", mode: "lines",
      name: p.obs_label || "Gemeten", line: { color: "#4caf50", width: 2 } },
    { x: s.dates, y: s.sim, type: "scatter", mode: "lines",
      name: p.sim_label || "Gesimuleerd", line: { color: "#4db6ac", width: 2, dash: "dash" } },
  ];
  Plotly.react(id, traces, {
    paper_bgcolor: "#080c14", plot_bgcolor: "#0d1b2a",
    font: { color: "#e0e0e0", size: 11 },
    margin: { t: 8, b: 34, l: 56, r: 14 },
    legend: { orientation: "h", y: -0.25, font: { size: 10 } },
    xaxis: { gridcolor: "#1a3a5c", tickformat: "%d %b" },
    yaxis: { title: yTitle, gridcolor: "#1a3a5c" },
  }, { responsive: true, displayModeBar: false });
}

// ── POC E · data-assimilatie (EnKF) ────────────────────────────────────────
async function loadAssimilation() {
  if (assimilationLoaded) return;
  const wait = document.getElementById("as-unavailable");
  const content = document.getElementById("as-content");
  wait.style.display = "block"; wait.textContent = "Assimilatie laden… (eerste keer ~15–30 s: RWS-fetch + hindcast).";
  try {
    const d = await fetch(`${API}/api/assimilation`).then(r => r.json());
    if (!d.available) { wait.textContent = d.reason || "Assimilatie niet beschikbaar."; return; }
    const s = d.summary, lv = d.live;
    const impr7 = Math.round((1 - s.rmse_assim_day7 / s.rmse_free_day7) * 100);
    const impr14 = Math.round((1 - s.rmse_assim_day14 / s.rmse_free_day14) * 100);
    document.getElementById("as-kpis").innerHTML =
      asKpi(`−${impr14}%`, "RMSE dag 14 beter", "#4db6ac") +
      asKpi(`−${impr7}%`, "RMSE dag 7 beter", "#4db6ac") +
      asKpi(`${s.coverage_assim}%`, "band-dekking", "#90a4ae") +
      asKpi(`${s.n_forecasts}`, "hindcast-verwachtingen", "#90a4ae");
    renderAssimLiveChart(lv);
    document.getElementById("as-live-note").innerHTML =
      `De assimilatie paste de recessie aan: <strong>τ ${lv.tau_prior} → ${lv.tau_post}</strong> ` +
      `en <strong>seizoensdoel ${lv.target_prior} → ${lv.target_post} m³/s</strong>. ` +
      `Vrij verwacht dag 14 ${lv.free[lv.free.length-1]} m³/s; geassimileerd ${lv.mean[lv.mean.length-1]} m³/s ` +
      `(band ${lv.p10[lv.p10.length-1]}–${lv.p90[lv.p90.length-1]}).`;
    renderAssimHorizonChart(d.per_horizon_free, d.per_horizon_assim);
    document.getElementById("as-horizon-note").innerHTML =
      `Over ${s.n_forecasts} gereconstrueerde verwachtingen (${d.window}) daalt de RMSE op dag 7 van ` +
      `<strong>${s.rmse_free_day7}</strong> naar <strong>${s.rmse_assim_day7} m³/s</strong> en op dag 14 van ` +
      `<strong>${s.rmse_free_day14}</strong> naar <strong>${s.rmse_assim_day14} m³/s</strong>. De systematische ` +
      `overschatting uit de hindcast is dus meetbaar kleiner geworden.`;
    wait.style.display = "none"; content.style.display = "block";
    assimilationLoaded = true;
  } catch (e) {
    wait.textContent = "Assimilatie niet beschikbaar.";
    console.warn("assimilation load failed:", e);
  }
}

function asKpi(val, label, color) {
  return `<div class="as-kpi"><b style="color:${color}">${val}</b><span>${label}</span></div>`;
}

function renderAssimLiveChart(lv) {
  const traces = [
    { x: lv.fdates, y: lv.p10, type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
    { x: lv.fdates, y: lv.p90, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty",
      fillcolor: "rgba(77,182,172,0.15)", name: "Ensembleband (geassimileerd)", hoverinfo: "skip" },
    { x: lv.recent_dates, y: lv.recent_obs, type: "scatter", mode: "lines+markers",
      name: "Gemeten (RWS Westervoort)", line: { color: "#4caf50", width: 2 }, marker: { size: 4 } },
    { x: lv.fdates, y: lv.free, type: "scatter", mode: "lines",
      name: "Vrije verwachting (recessie)", line: { color: "#ef5350", width: 2, dash: "dash" } },
    { x: lv.fdates, y: lv.mean, type: "scatter", mode: "lines",
      name: "Geassimileerd (EnKF)", line: { color: "#4db6ac", width: 2 } },
  ];
  Plotly.react("as-live-chart", traces, {
    paper_bgcolor: "#080c14", plot_bgcolor: "#0d1b2a", font: { color: "#e0e0e0", size: 11 },
    margin: { t: 8, b: 34, l: 56, r: 14 }, legend: { orientation: "h", y: -0.28, font: { size: 9 } },
    xaxis: { gridcolor: "#1a3a5c", tickformat: "%d %b" },
    yaxis: { title: "Debiet Westervoort (m³/s)", gridcolor: "#1a3a5c" },
  }, { responsive: true, displayModeBar: false });
}

function renderAssimHorizonChart(free, assim) {
  const traces = [
    { x: free.horizon, y: free.rmse, type: "scatter", mode: "lines+markers",
      name: "Vrij — RMSE", line: { color: "#ef5350", width: 2 } },
    { x: assim.horizon, y: assim.rmse, type: "scatter", mode: "lines+markers",
      name: "Geassimileerd — RMSE", line: { color: "#4db6ac", width: 2 } },
  ];
  Plotly.react("as-horizon-chart", traces, {
    paper_bgcolor: "#080c14", plot_bgcolor: "#0d1b2a", font: { color: "#e0e0e0", size: 11 },
    margin: { t: 8, b: 38, l: 56, r: 14 }, legend: { orientation: "h", y: -0.3, font: { size: 10 } },
    xaxis: { title: "Lead-time (dagen vooruit)", gridcolor: "#1a3a5c", dtick: 1 },
    yaxis: { title: "RMSE (m³/s)", gridcolor: "#1a3a5c" },
  }, { responsive: true, displayModeBar: false });
}

// ── POC via FEWS · draai een proef als FEWS-client ─────────────────────────
function initFewsRun() {
  if (!fewsRunInit) { fewsRunInit = true; loadFewsRun("2021"); }
}

function _frSetStep(step, val, url) {
  const v = document.getElementById("fr-s-" + step);
  if (v) { v.textContent = "✓ " + val; v.className = "fr-step-val"; }
  const u = document.getElementById("fr-u-" + step);
  if (u) u.textContent = url;
}

async function loadFewsRun(run) {
  currentFewsRun = run;
  document.querySelectorAll("#fr-runs .fr-run-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.run === run));
  const unavail = document.getElementById("fr-unavailable");
  unavail.style.display = "none";
  ["filters", "locations", "parameters", "timeseries"].forEach(s => {
    const v = document.getElementById("fr-s-" + s);
    if (v) { v.textContent = "…"; v.className = "fr-step-val pending"; }
    const u = document.getElementById("fr-u-" + s);
    if (u) u.textContent = "";
  });
  try {
    // 1–3: discovery — echt de FEWS-bron ontdekken
    const fUrl = `${FEWS_PI_BASE}/filters`;
    const f = await fetch(fUrl).then(r => r.json());
    _frSetStep("filters", `${f.filters.length} filter(s)`, fUrl);
    const lUrl = `${FEWS_PI_BASE}/locations`;
    const l = await fetch(lUrl).then(r => r.json());
    _frSetStep("locations", `${l.locations.length} locaties`, lUrl);
    const pUrl = `${FEWS_PI_BASE}/parameters`;
    const p = await fetch(pUrl).then(r => r.json());
    _frSetStep("parameters", `${p.parameters.length} parameters`, pUrl);
    // 4: de tijdreeks binnenhalen als PI JSON
    const tsUrl = `${FEWS_PI_BASE}/timeseries?locationIds=KAMPEN,WESTERVOORT&parameterIds=Q.sim&period=${run}`;
    const ts = await fetch(tsUrl).then(r => r.json());
    const nEv = (ts.timeSeries || []).reduce((a, s) => a + (s.events ? s.events.length : 0), 0);
    _frSetStep("timeseries", `${(ts.timeSeries || []).length} reeks(en) · ${nEv} events`, tsUrl);
    if (!ts.timeSeries || !ts.timeSeries.length) throw new Error("geen reeksen");
    renderFewsRunChart(ts, run);
    renderFewsRunHeaders(ts);
  } catch (e) {
    unavail.textContent = "Deze run is niet via FEWS beschikbaar — is de wflow-simulatie voor deze periode aanwezig?";
    unavail.style.display = "block";
    Plotly.purge("fr-chart");
    document.getElementById("fr-headers").innerHTML = "";
    console.warn("fewsrun failed:", e);
  }
}

function renderFewsRunChart(ts, run) {
  const colors = { KAMPEN: "#4db6ac", WESTERVOORT: "#ff9800" };
  const traces = ts.timeSeries.map(s => ({
    x: s.events.map(e => e.date),
    y: s.events.map(e => parseFloat(e.value)),
    type: "scatter", mode: "lines",
    name: `${s.header.locationId} · ${s.header.parameterId} (${s.header.units})`,
    line: { color: colors[s.header.locationId] || "#90caf9", width: 2 },
  }));
  document.getElementById("fr-chart-title").textContent =
    `Resultaat — ${FEWS_RUN_LABELS[run] || run} · Q.sim uit PI JSON (via FEWS)`;
  Plotly.react("fr-chart", traces, {
    paper_bgcolor: "#080c14", plot_bgcolor: "#0d1b2a", font: { color: "#e0e0e0", size: 11 },
    margin: { t: 8, b: 36, l: 58, r: 14 }, legend: { orientation: "h", y: -0.22, font: { size: 10 } },
    xaxis: { gridcolor: "#1a3a5c", tickformat: "%d %b" },
    yaxis: { title: "Debiet (m³/s)", gridcolor: "#1a3a5c" },
  }, { responsive: true, displayModeBar: false });
}

function renderFewsRunHeaders(ts) {
  const rows = ts.timeSeries.map(s => {
    const h = s.header;
    return `<tr><td><code>${h.locationId}</code></td><td><code>${h.parameterId}</code></td>` +
           `<td>${h.units}</td><td>${h.startDate.date} → ${h.endDate.date}</td><td>${s.events.length}</td></tr>`;
  }).join("");
  document.getElementById("fr-headers").innerHTML =
    `<table><thead><tr><th>locationId</th><th>parameterId</th><th>units</th>` +
    `<th>periode (PI header)</th><th>events</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ── WL-CHAT-1 · uitleg-chat ────────────────────────────────────────────────
function initChat() {
  if (!chatToken) chatToken = localStorage.getItem("wl_chat_token");
  const loggedIn = !!chatToken;
  document.getElementById("chat-login").style.display = loggedIn ? "none" : "block";
  document.getElementById("chat-ui").style.display = loggedIn ? "block" : "none";
  if (loggedIn && !document.getElementById("chat-messages").children.length) {
    chatAddNote("Stel een vraag over Waterlab — bijvoorbeeld “waarom is het Kampen-peil niet te valideren?” of “wat doet Proef 9?”");
  }
}

async function chatLogin() {
  const pw = document.getElementById("chat-pw").value;
  const msg = document.getElementById("chat-login-msg");
  msg.textContent = "Inloggen…";
  try {
    const r = await fetch(`${API}/api/chat/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pw }),
    });
    const d = await r.json();
    if (!r.ok || !d.ok) { msg.textContent = d.reason || "Inloggen mislukt."; return; }
    chatToken = d.token;
    localStorage.setItem("wl_chat_token", chatToken);
    msg.textContent = "";
    document.getElementById("chat-pw").value = "";
    initChat();
  } catch (e) { msg.textContent = "Inloggen mislukt — server niet bereikbaar."; }
}

function chatAddMessage(role, text, sources) {
  const box = document.getElementById("chat-messages");
  const el = document.createElement("div");
  el.className = "chat-msg " + role;
  el.textContent = text;
  if (role === "bot" && sources && sources.length) {
    const src = document.createElement("div");
    src.className = "chat-src";
    src.appendChild(document.createTextNode("Lees verder: "));
    sources.forEach(s => {
      const a = document.createElement("a");
      a.textContent = s.label;
      if (s.doc) { a.href = "/docs/" + s.doc; a.target = "_blank"; a.rel = "noopener"; }
      else { a.onclick = () => switchYear(s.tab); }
      src.appendChild(a);
    });
    el.appendChild(src);
  }
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
  return el;
}

function chatAddNote(text) {
  const box = document.getElementById("chat-messages");
  const el = document.createElement("div");
  el.className = "chat-msg note";
  el.textContent = text;
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
}

async function chatSend() {
  const input = document.getElementById("chat-input");
  const q = input.value.trim();
  if (!q) return;
  input.value = "";
  chatAddMessage("user", q);
  chatHistory.push({ role: "user", content: q });
  const btn = document.getElementById("chat-send");
  btn.disabled = true;
  const thinking = chatAddMessage("bot", "…");
  try {
    const r = await fetch(`${API}/api/chat`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: chatToken, question: q, history: chatHistory.slice(0, -1) }),
    });
    const d = await r.json();
    thinking.remove();
    if (r.status === 401) {
      chatToken = null; localStorage.removeItem("wl_chat_token");
      chatAddNote("Sessie verlopen — log opnieuw in."); initChat(); return;
    }
    if (!d.ok) { chatAddNote(d.reason || "Er ging iets mis."); return; }
    chatAddMessage("bot", d.answer, d.sources);
    chatHistory.push({ role: "assistant", content: d.answer });
    if (d.remaining != null)
      document.getElementById("chat-budget").textContent =
        `Nog ${d.remaining} vragen in deze sessie.`;
  } catch (e) {
    thinking.remove();
    chatAddNote("De assistent is even niet bereikbaar.");
  } finally {
    btn.disabled = false;
    input.focus();
  }
}

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

    // Verwachte absolute grondwaterstand (reservoirmodel v2) als extra reeks
    fetch(`${API}/api/grondwater/reservoir`).then(r => r.json())
      .then(res => renderForecastChart(data, res))
      .catch(() => { /* grondwater optioneel; grafiek staat al */ });

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

function renderForecastChart(d, res) {
  const today     = d.generated_at;
  const measDates = d.measured.dates;
  const fDates    = d.forecast.dates;
  const allX0     = measDates[0];
  const allX1     = fDates[fDates.length - 1];

  // Reservoirmodel (v2): verwachte absolute grondwaterstand + onzekerheidsband (beste-NSE put)
  let gwTraces = [];
  if (res && res.available && res.wells && res.wells.length) {
    const w = res.wells[0];   // hoogste NSE
    const xs = [], ys = [], lo = [], hi = [];
    (w.dates || []).forEach((dt, i) => {
      if (dt >= allX0 && dt <= allX1) { xs.push(dt); ys.push(w.gw[i]); lo.push(w.lower[i]); hi.push(w.upper[i]); }
    });
    if (xs.length) {
      const wid = w.bro_id.replace("GLD0000000", "GLD…");
      gwTraces = [
        { x: xs, y: lo, type: "scatter", mode: "lines", line: { width: 0 },
          yaxis: "y3", showlegend: false, hoverinfo: "skip" },
        { x: xs, y: hi, type: "scatter", mode: "lines", line: { width: 0 },
          fill: "tonexty", fillcolor: "rgba(186,104,200,0.13)", yaxis: "y3",
          name: "Verwacht · grondwater onzekerheid", hoverinfo: "skip" },
        { x: xs, y: ys, type: "scatter", mode: "lines",
          name: `Verwacht · grondwater ${wid} (m, NSE ${w.nse})`,
          line: { color: "#ba68c8", width: 2 }, yaxis: "y3",
          hovertemplate: "%{y:.2f} m<extra>grondwater</extra>" },
      ];
    }
  }

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
      name: "Verwacht · onzekerheidsband (debiet)", hoverinfo: "skip", yaxis: "y",
    },
    // Gemeten Westervoort Q
    {
      x: measDates, y: d.measured.q_westervoort,
      type: "scatter", mode: "lines",
      name: "Gemeten · debiet Westervoort (m³/s, RWS)",
      line: { color: "#ff9800", width: 1.5, dash: "dot" },
      yaxis: "y",
    },
    // Gemeten Q Kampen (routing)
    {
      x: measDates, y: d.measured.q_kampen,
      type: "scatter", mode: "lines",
      name: "Gemeten · debiet Kampen (routing, m³/s)",
      line: { color: "#4db6ac", width: 2 },
      yaxis: "y",
    },
    // Statistisch debiet-forecast
    {
      x: fDates, y: d.forecast.q_mid,
      type: "scatter", mode: "lines",
      name: "Verwacht · debiet Kampen (m³/s)",
      line: { color: "#4db6ac", width: 2, dash: "dash" },
      yaxis: "y",
    },
    // Drempel 1500 m³/s
    {
      x: [allX0, allX1], y: [1500, 1500],
      type: "scatter", mode: "lines",
      name: "Drempel · 1500 m³/s (referentie)",
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
      name: "Gemeten · waterpeil Kampen (m+NAP, RWS)",
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
      name: "Verwacht · waterpeil Kampen (m+NAP, RWS)",
      line: { color: "#81c784", width: 2 },
      marker: { size: 5 },
      yaxis: "y2",
    });
  }

  if (gwTraces.length) traces.push(...gwTraces);
  const hasGw = gwTraces.length > 0;

  const layout = {
    paper_bgcolor: "#080c14",
    plot_bgcolor:  "#0d1b2a",
    font:   { color: "#e0e0e0", size: 11 },
    margin: { t: 8, b: 36, l: 58, r: (hasH || hasGw) ? 58 : 14 },
    legend: { orientation: "h", y: -0.28, font: { size: 10 } },
    xaxis: {
      gridcolor: "#1a3a5c", tickformat: "%d %b",
      range: [allX0, allX1],
      domain: hasGw ? [0, 0.88] : [0, 1],
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
        ...(hasGw ? { anchor: "free", position: 0.88 } : {}),
      },
    } : {}),
    ...(hasGw ? {
      yaxis3: {
        title: "Grondwater (m)", overlaying: "y", side: "right",
        anchor: "free", position: 1.0,
        titlefont: { color: "#ba68c8" }, tickfont: { color: "#ba68c8" },
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
      type: "bar", name: "Gemeten · neerslag (mm, ERA5)",
      marker: { color: "rgba(100,130,160,0.7)" },
    },
    {
      x: d.precip.forecast_dates, y: d.precip.forecast_values,
      type: "bar", name: "Verwacht · neerslag (mm, IFS)",
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
    loadGrondwaterProjection();       // vooruitblik o.b.v. live verwachting
    loadGrondwaterReservoir();        // reservoirmodel fit-kwaliteit (traag, apart)
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
    name: "IJssel-stand Kampen (wflow rivierdiepte, m)", line: { color: "#ef5350", width: 2.5, dash: "dash" }, yaxis: "y2",
  });
  Plotly.react("grondwater-chart", traces, {
    paper_bgcolor: "#080c14", plot_bgcolor: "#0d1b2a",
    font: { color: "#e0e0e0", size: 11 }, margin: { t: 8, b: 40, l: 58, r: 58 },
    legend: { orientation: "h", y: -0.3, font: { size: 9 } },
    xaxis: { gridcolor: "#1a3a5c", tickformat: "%d %b" },
    yaxis: { title: "Grondwaterstand (m)", gridcolor: "#1a3a5c",
             titlefont: { color: "#4dd0e1" }, tickfont: { color: "#4dd0e1" } },
    yaxis2: { title: "IJssel-rivierdiepte (m)", overlaying: "y", side: "right", showgrid: false,
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

async function loadGrondwaterProjection() {
  const chart   = document.getElementById("grondwater-projection-chart");
  const unavail = document.getElementById("grondwater-projection-unavailable");
  try {
    const d = await fetch(`${API}/api/grondwater/projection`).then(r => r.json());
    if (!d.available || !d.wells || !d.wells.length) {
      unavail.style.display = ""; chart.style.display = "none"; return;
    }
    unavail.style.display = "none"; chart.style.display = "";
    renderGrondwaterProjectionChart(d);
    renderGrondwaterProjectionTable(d);
  } catch (err) {
    unavail.style.display = ""; chart.style.display = "none";
    console.warn("grondwater projection failed:", err);
  }
}

function renderGrondwaterProjectionChart(d) {
  const colors = ["#4dd0e1", "#4db6ac", "#81c784", "#ffb74d", "#ba68c8"];
  const traces = d.wells.map((w, i) => ({
    x: w.projection.dates, y: w.projection.delta_m, type: "scatter", mode: "lines",
    name: w.bro_id.replace("GLD0000000", "GLD…") + " · lag " + w.lag_days + "d",
    line: { color: colors[i % colors.length], width: 1.8 },
  }));
  let lastDate = d.today;
  traces.forEach(t => { if (t.x.length && t.x[t.x.length - 1] > lastDate) lastDate = t.x[t.x.length - 1]; });
  const shapes = [
    { type: "line", x0: d.today, x1: d.today, yref: "paper", y0: 0, y1: 1,
      line: { color: "#90a4ae", width: 1, dash: "dot" } },
  ];
  if (d.river.forecast_from) {
    shapes.push({ type: "rect", xref: "x", yref: "paper",
      x0: d.river.forecast_from, x1: lastDate, y0: 0, y1: 1,
      fillcolor: "rgba(77,208,225,0.07)", line: { width: 0 } });
  }
  Plotly.react("grondwater-projection-chart", traces, {
    paper_bgcolor: "#080c14", plot_bgcolor: "#0d1b2a",
    font: { color: "#e0e0e0", size: 11 }, margin: { t: 16, b: 40, l: 64, r: 14 },
    legend: { orientation: "h", y: -0.3, font: { size: 9 } },
    xaxis: { gridcolor: "#1a3a5c", tickformat: "%d %b" },
    yaxis: { title: "Δ grondwater t.o.v. vandaag (m)", gridcolor: "#1a3a5c",
             zeroline: true, zerolinecolor: "#37474f" },
    shapes: shapes,
    annotations: [{ x: d.today, yref: "paper", y: 1.04, text: "vandaag",
                    showarrow: false, font: { size: 10, color: "#90a4ae" } }],
  }, { responsive: true, displayModeBar: false });
}

function renderGrondwaterProjectionTable(d) {
  const el = document.getElementById("gw-proj-table");
  if (!el) return;
  const rows = d.wells.map(w => {
    const dir = w.direction === "stijgend" ? "↑ stijgend"
              : (w.direction === "dalend" ? "↓ dalend" : "→ stabiel");
    const col = w.direction === "stijgend" ? "#4db6ac"
              : (w.direction === "dalend" ? "#ef5350" : "#90a4ae");
    const sign = w.expected_change_m >= 0 ? "+" : "";
    return `<tr><td><code>${w.bro_id}</code></td><td>lag ${w.lag_days} d</td>` +
           `<td>${w.committed_days} d vastgelegd</td>` +
           `<td style="color:${col}">${sign}${w.expected_change_m} m (${dir})</td></tr>`;
  }).join("");
  el.innerHTML = `<table class="ensemble-scenario-table" style="margin-top:8px">` +
    `<thead><tr><th>BRO-ID</th><th>Lag</th><th>Reeds vastgelegd</th><th>Verwachte Δ (horizon)</th></tr></thead>` +
    `<tbody>${rows}</tbody></table>`;
}

async function loadGrondwaterReservoir() {
  const tbl = document.getElementById("gw-reservoir-table");
  const un  = document.getElementById("gw-reservoir-unavailable");
  if (!tbl) return;
  un.style.display = "";
  try {
    const d = await fetch(`${API}/api/grondwater/reservoir`).then(r => r.json());
    if (!d.available || !d.wells || !d.wells.length) {
      un.textContent = "Reservoirmodel niet beschikbaar."; return;
    }
    un.style.display = "none";
    const rows = d.wells.map(w => {
      const nse = w.nse;
      const col = nse >= 0.7 ? "#4db6ac" : (nse >= 0.4 ? "#ffb74d" : "#ef5350");
      const tau = w.tau_river_days ? `${w.tau_days} / ${w.tau_river_days} d` : `${w.tau_days} d`;
      const modBadge = w.model === "recharge+river" ? "recharge + river" : "recharge";
      return `<tr><td><code>${w.bro_id}</code></td>` +
        `<td>${modBadge}</td>` +
        `<td style="color:${col}; font-weight:700">${nse}</td>` +
        `<td>${tau}</td>` +
        `<td>±${w.band_m} m</td>` +
        `<td>${w.nowcast_today} → ${w.forecast_horizon} m</td>` +
        `<td>${w.last_value} m (${w.last_date})</td></tr>`;
    }).join("");
    tbl.innerHTML = `<table class="ensemble-scenario-table" style="margin-top:8px">` +
      `<thead><tr><th>BRO-ID</th><th>Model</th><th>NSE</th><th>τ recharge / river</th>` +
      `<th>Band</th><th>Nowcast → +14d</th><th>Laatste meting</th></tr></thead>` +
      `<tbody>${rows}</tbody></table>`;
  } catch (err) {
    un.textContent = "Reservoirmodel niet beschikbaar.";
    console.warn("grondwater reservoir failed:", err);
  }
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

