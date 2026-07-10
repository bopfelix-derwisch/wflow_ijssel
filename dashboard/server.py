"""FastAPI server: levert API-data en statische dashboard-bestanden."""
import collections
import json
import os
import re
import time
from pathlib import Path

import anthropic as _anthropic
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from dashboard.forecast import build_forecast
from dashboard.grondwater import (
    build_grondwater, build_interpretation, forecast_groundwater_context, project_groundwater,
)
from fews_poc.router import router as _fews_router
from fews_poc.data_adapter import get_wflow_timeseries, get_waterinfo_timeseries

# Laad .env als ANTHROPIC_API_KEY nog niet in omgeving staat
_env_file = Path(__file__).parent.parent.parent / ".env"
if _env_file.exists() and not os.environ.get("ANTHROPIC_API_KEY"):
    for _line in _env_file.read_text().splitlines():
        if _line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = _line.split("=", 1)[1].strip()

ROOT       = Path(__file__).parent.parent
STATIC_DIR = Path(__file__).parent
# wflow-uitvoer staat onder wflow_ijssel/data/ (de model-werkmap), niet onder <root>/data/.
DATA_ROOT  = ROOT / "wflow_ijssel" / "data"

OUTPUT_DIRS = {
    "1995":      DATA_ROOT / "output",
    "2018":      DATA_ROOT / "output_2018",
    "2021":      DATA_ROOT / "output_2021_real",   # echte gemeten inflow
    "2021synth": DATA_ROOT / "output_2021",        # synthetische inflow (vergelijking)
}

ENSEMBLE_DIR = Path("/home/bob/waterlab/ensemble_data/outputs")

app = FastAPI(title="Waterlab API")
app.include_router(_fews_router)

# WL-GQL-1: read-only GraphQL-façade (resolvers delegeren naar bestaande bronfuncties)
from dashboard.graphql_api import graphql_app  # noqa: E402
app.include_router(graphql_app, prefix="/graphql")

# Rate-limiting op /graphql: per IP een sliding window. Schema-limieten (depth/tokens/
# aliases) zitten in graphql_api.py; dit beschermt tegen request-floods.
_GQL_RATE_WINDOW = 60   # seconden
_GQL_RATE_MAX    = 60   # verzoeken per window per IP
_gql_hits: dict = collections.defaultdict(list)


@app.middleware("http")
async def _graphql_rate_limit(request, call_next):
    if request.url.path.startswith("/graphql"):
        xff = request.headers.get("x-forwarded-for", "")
        ip = xff.split(",")[0].strip() or (request.client.host if request.client else "?")
        now = time.monotonic()
        hits = _gql_hits[ip]
        cutoff = now - _GQL_RATE_WINDOW
        while hits and hits[0] < cutoff:
            hits.pop(0)
        if len(hits) >= _GQL_RATE_MAX:
            return JSONResponse(
                {"errors": [{"message": f"Rate limit overschreden — max "
                                        f"{_GQL_RATE_MAX} GraphQL-verzoeken per minuut."}]},
                status_code=429,
            )
        hits.append(now)
    return await call_next(request)

if os.path.isdir(str(STATIC_DIR)):
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _output_dir(year: str) -> Path:
    if year not in OUTPUT_DIRS:
        raise HTTPException(400, f"Onbekend jaar: {year}.")
    return OUTPUT_DIRS[year]


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"),
                        headers={"Cache-Control": "no-store"})


# ── docs-viewer: markdown uit docs/ leesbaar op de site (WL-PROV-1/2, WL-GOV-1) ──
DOCS_DIR     = ROOT / "docs"
_DOC_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")   # geen path-traversal
_DOC_TITLES  = {
    "WL-PROV-2_schematisatie": "WL-PROV-2 · Herkomst van schematisatie en randvoorwaarden",
    "WL-GOV-1_wel_niet":       "WL-GOV-1 · Wat Waterlab wél en niet bewijst",
}
_DOC_PAGE = """<!doctype html><html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — Waterlab</title>
<style>
  :root { color-scheme: dark; }
  body { background:#080c14; color:#c2d0d8; font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
         line-height:1.65; margin:0; }
  .wrap { max-width:860px; margin:0 auto; padding:1.5rem 1.4rem 4rem; }
  .topbar { position:sticky; top:0; background:#07111c; border-bottom:1px solid #1a2e3f;
            padding:.7rem 1.4rem; font-size:13px; }
  .topbar a { color:#4db6ac; text-decoration:none; font-weight:600; }
  .topbar a:hover { text-decoration:underline; }
  .doc-src { color:#455a64; font-size:11px; margin:.3rem 0 1.6rem; }
  h1 { font-size:1.5rem; color:#e0e0e0; border-bottom:1px solid #1a2e3f; padding-bottom:.5rem; }
  h2 { font-size:1.15rem; color:#4db6ac; margin-top:2rem; }
  h3 { font-size:1rem; color:#90caf9; }
  a { color:#4db6ac; }
  code { background:#001a13; color:#4db6ac; padding:1px 5px; border-radius:3px; font-size:.9em; }
  pre { background:#0a1620; border:1px solid #14283a; border-radius:6px; padding:12px; overflow:auto; }
  pre code { background:none; padding:0; color:#a7c0cc; }
  blockquote { border-left:3px solid #c55a11; margin:1.2rem 0; padding:.4rem 0 .4rem 1rem;
               color:#90a4ae; background:#0a1620; }
  table { border-collapse:collapse; width:100%; margin:1rem 0; font-size:13px; }
  th, td { border:1px solid #1a2e3f; padding:6px 10px; text-align:left; vertical-align:top; }
  th { background:#0d2230; color:#b0c4ce; }
  tr:nth-child(even) td { background:#0a1620; }
  strong { color:#cfd8dc; }
  hr { border:none; border-top:1px solid #1a2e3f; margin:2rem 0; }
</style></head><body>
<div class="topbar"><a href="/#pocs">← Terug naar het dashboard</a></div>
<div class="wrap">
<p class="doc-src">Bron: <code>docs/__NAME__.md</code> · live uit de repo gerenderd</p>
__BODY__
</div></body></html>"""


@app.get("/docs/{name}")
def serve_doc(name: str):
    if not _DOC_NAME_RE.match(name):
        raise HTTPException(404, "Doc niet gevonden.")
    path = DOCS_DIR / f"{name}.md"
    if not path.is_file():
        raise HTTPException(404, "Doc niet gevonden.")
    text = path.read_text(encoding="utf-8")
    try:
        import markdown as _md
        body = _md.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    except Exception:
        import html as _h
        body = "<pre>" + _h.escape(text) + "</pre>"
    import html as _h
    title = _DOC_TITLES.get(name, name)
    page = (_DOC_PAGE.replace("__TITLE__", _h.escape(title))
                     .replace("__NAME__", _h.escape(name))
                     .replace("__BODY__", body))
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


# ── jaar-specifieke endpoints ────────────────────────────────────────────────

@app.get("/api/{year}/kpis")
def get_kpis(year: str):
    d = _output_dir(year)
    path = d / "kpis.json"
    if not path.exists():
        raise HTTPException(503, f"Voer eerst export_output{'_2021' if year == '2021' else ''}.py uit")
    return JSONResponse(json.loads(path.read_text()))


@app.get("/api/{year}/timeseries/{station}")
def get_timeseries(year: str, station: str):
    if station not in ("kampen", "westervoort"):
        raise HTTPException(400, f"Onbekend station: {station}")
    d = _output_dir(year)
    path = d / f"timeseries_{station}.json"
    if not path.exists():
        raise HTTPException(503, f"Geen data voor {station} ({year})")
    return JSONResponse(json.loads(path.read_text()))


@app.get("/api/{year}/measured")
def get_measured(year: str):
    # gemeten data zit altijd in de synth-map (ongeacht inflow-variant)
    base = year.replace("synth", "")
    candidates = [
        OUTPUT_DIRS.get(f"{base}synth", DATA_ROOT / f"output_{base}") / "measured_2021.json",
        OUTPUT_DIRS.get(base, DATA_ROOT / f"output_{base}") / "measured_2021.json",
    ]
    for path in candidates:
        if path.exists():
            return JSONResponse(json.loads(path.read_text()))
    raise HTTPException(404, f"Geen gemeten data voor {year}")


@app.get("/api/{year}/river/{day}")
def get_river_day(year: str, day: str):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise HTTPException(400, "Ongeldig datumformaat (verwacht YYYY-MM-DD)")
    d = _output_dir(year)
    path = d / f"river_day_{day}.geojson"
    if not path.exists():
        raise HTTPException(404, f"Geen data voor dag {day} ({year})")
    return JSONResponse(json.loads(path.read_text()))


# ── backwards compat: /api/kpis → 1995 ──────────────────────────────────────

@app.get("/api/kpis")
def get_kpis_legacy():
    return get_kpis("1995")


@app.get("/api/timeseries/{station}")
def get_timeseries_legacy(station: str):
    return get_timeseries("1995", station)


@app.get("/api/river/{day}")
def get_river_day_legacy(day: str):
    return get_river_day("1995", day)


@app.get("/api/forecast")
def get_forecast():
    try:
        return JSONResponse(build_forecast())
    except Exception as e:
        raise HTTPException(503, f"Voorspelling niet beschikbaar: {e}")


_intv_cache: dict = {}
_INTV_TTL = 900  # 15 min — zelfde als forecast cache

# Drempelwaarden en gevolgen per regime (m+NAP, Kampen)
_REGIME_CONTEXT = """
LAAGWATER-REGIMES (droogte, lage afvoer):
  < 0.0 m+NAP  — EXTREEM LAAG: beroepsvaart grotendeels stilgelegd, kritische waterinname
                  drinkwater en landbouw in gevaar, ecologische minimumafvoer onderschreden,
                  RWS activeert laagwaterprotocol, afstemming met Duitsland over Rijn-beheer
  0.0–0.5 m+NAP — LAAG: ondiepgang binnenvaart beperkt tot <2.0 m, waterwinning onder druk,
                  peilbesluit Veluwemeer onder spanning, HHNK en Waterschap Vallei en Veluwe
                  in overleg over inlaatbeheer, natuur droogtestresstekens
  0.5–1.2 m+NAP — BENEDENNORMAAL: scheepvaart met beperkingen, verhoogde monitoring,
                  innamepunten waterschap in laagste stand

NORMAAL REGIME:
  1.2–3.0 m+NAP — NORMAAL: geen bijzondere maatregelen vereist, reguliere monitoring

HOOGWATER-REGIMES:
  3.0–4.2 m+NAP — WAAKZAAM: eerste aandachtspeil, dijkbewaking start, waterstandberichten
  4.2–5.4 m+NAP — VERHOOGD: uitgebreide dijkbewaking, crisisoverleg gemeenten, noodplannen gereed
  5.4–6.4 m+NAP — HOOG: dijkbewaking 24/7, evacuatieplannen actief
  > 6.4 m+NAP   — EXTREEM: referentie jan 1995 (6.5 m+NAP Kampen), dijken op kritisch niveau
"""


def _classify_regime(h: float | None) -> str:
    if h is None:
        return "onbekend"
    if h < 0.0:
        return "extreem_laag"
    if h < 0.5:
        return "laag"
    if h < 1.2:
        return "benedennormaal"
    if h < 3.0:
        return "normaal"
    if h < 4.2:
        return "waakzaam"
    if h < 5.4:
        return "verhoogd"
    if h < 6.4:
        return "hoog"
    return "extreem_hoog"


def _build_intervention(forecast: dict) -> str:
    kpis   = forecast["kpis"]
    h_now  = kpis.get("current_h_kampen_m")
    h_str  = f"{h_now:.2f} m+NAP" if h_now is not None else "niet beschikbaar"
    regime = _classify_regime(h_now)

    # RWS officiële waterpeil-verwachting (2–5 d)
    rws_fcast = forecast.get("rws_forecast", {})
    rws_lines = [
        f"  {dt}: {hm:.2f} m+NAP"
        for dt, hm in zip(rws_fcast.get("dates", []), rws_fcast.get("values_m", []))
    ]
    rws_block = (
        "RWS officiële waterpeilprognose Kampen:\n" + "\n".join(rws_lines)
        if rws_lines else "RWS officiële prognose: niet beschikbaar"
    )

    # Verwacht peil op basis van verwacht piekdebiet (ruwe schatting via rating curve)
    peak_q   = kpis["peak_forecast_q"]
    peak_h_est = round(0.0012 * peak_q - 0.05, 2)  # grove linearisatie Q~H Kampen

    # Grondwater-context (BRO GLD, Veluwe-oostflank) voor een integrale interventie
    gw = forecast_groundwater_context()
    if gw["wells"]:
        gw_lines = "\n".join(
            f"  {w['bro_id']}: laatste meting {w['last_date']} = {w['last_value']} m"
            f" (90-daagse trend {w['trend_90d']:+.2f} m)" for w in gw["wells"]
        )
    else:
        gw_lines = "  (geen recente BRO-meting beschikbaar)"

    # Verwachte grondwaterrespons o.b.v. de live afvoerverwachting (projectie per put)
    try:
        proj = project_groundwater()
        proj_lines = "\n".join(
            f"  {w['bro_id']}: verwachte respons over ~{w['committed_days'] + 14} d = "
            f"{w['expected_change_m']:+.2f} m ({w['direction']})"
            for w in proj.get("wells", [])[:5]
        ) if proj.get("available") and proj.get("wells") else "  (projectie niet beschikbaar)"
    except Exception:
        proj_lines = "  (projectie niet beschikbaar)"

    # Absolute grondwaterstand-voorspelling (reservoirmodel v2, recharge-gedreven)
    try:
        from dashboard.reservoir import predict_set
        resv = predict_set()
        resv_lines = "\n".join(
            f"  {w['bro_id']} (NSE {w['nse']}): nowcast vandaag {w['nowcast_today']} m → "
            f"+14 d {w['forecast_horizon']} m (±{w['band_m']} m); laatste meting {w['last_value']} m"
            for w in resv.get("wells", [])[:3]
        ) if resv.get("available") and resv.get("wells") else "  (reservoirmodel niet beschikbaar)"
    except Exception:
        resv_lines = "  (reservoirmodel niet beschikbaar)"

    gw_block = (
        "GRONDWATER-CONTEXT (Veluwe-oostflank, BRO GLD — let op: meetlatentie ~maanden):\n"
        f"{gw_lines}\n"
        f"Gekalibreerde koppeling IJsselpeil → Veluwe-grondwater (droogte 2018): "
        f"lag ~{gw['lag_days']} dagen, r≈{gw['r']}.\n"
        "VERWACHTE GRONDWATERRESPONS (projectie via de afvoerverwachting; eerste ~lag dagen "
        "al vastgelegd door reeds-gemeten afvoer):\n"
        f"{proj_lines}\n"
        "ABSOLUTE GRONDWATERSTAND-VOORSPELLING (reservoirmodel, neerslag/verdamping-gedreven, "
        "geankerd op laatste meting; NSE = fit-kwaliteit, hoger = betrouwbaarder):\n"
        f"{resv_lines}"
    )

    prompt = (
        f"Actuele IJssel-situatie bij Kampen ({forecast['generated_at']}):\n\n"
        f"Huidig waterpeil:     {h_str}  →  regime: {regime}\n"
        f"Huidig debiet Kampen: {kpis['current_q_kampen']} m³/s\n"
        f"Verwacht piekdebiet:  {peak_q} m³/s op {kpis['peak_forecast_date']}"
        f"  (geschat peil ≈ {peak_h_est} m+NAP)\n"
        f"Neerslag komende 14 d: {kpis['total_precip_14d']} mm\n\n"
        f"{rws_block}\n\n"
        f"{gw_block}\n\n"
        f"Regimecontext:\n{_REGIME_CONTEXT}\n"
        "Geef een INTEGRALE interventie die past bij het HUIDIGE regime. Behandel primair het "
        "waterpeil en de scheepvaart; betrek — alleen waar het regime én de grondwater-context "
        "dat rechtvaardigen (vooral bij laagwater/droogte) — ook de grondwaterafhankelijke "
        "domeinen: drinkwaterwinning (Vitens), landbouw/beregening en natuur/verdroging en "
        "kweldruk op de Veluwe. Leg het verband expliciet via de IJssel→grondwater-koppeling. "
        "Benoem hierbij CONCREET de grondwatercijfers uit de context: de laatste gemeten stand "
        "en trend, en de verwachte respons (richting + grootte in meters, met de lag). Verbind "
        "die cijfers aan een gevolg of maatregel; noem de meetlatentie als onzekerheid. "
        "Beschrijf acties chronologisch; noem geen domein dat nu niet relevant is. "
        "Schrijf vloeiende lopende tekst zonder kopjes, vetgedrukte koppen, opsommingstekens of "
        "markdown-symbolen (# of *); strikt maximaal 240 woorden."
    )

    client = _anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=750,
        system="""Je bent dr. Marieke van den Berg, senior hydroloog bij RWS Water, Verkeer en Leefomgeving \
met 25 jaar ervaring in het IJssel-Rijngebied. Je combineert diepgaande hydrologische expertise \
met grondige kennis van lokale infrastructuur, bestuurlijke verhoudingen en praktijkervaring \
uit meerdere extreme situaties.

GEBIEDSSCHEMATISATIE RIJN–IJSSEL:

  Duitsland
      │
  [Lobith] ──── meetpunt grensoverschrijding Rijn (~2.200 m³/s gemiddeld)
      │
  [Pannerdense Kop] ── stuwbeheer RWS
      ├── 67% ──▶ [Waal] ──▶ Nijmegen ──▶ Rotterdam (niet in model)
      ├── 22% ──▶ [Neder-Rijn] ──▶ stuw Driel/Amerongen ──▶ Lek ──▶ Rotterdam
      └── 13% ──▶ [Westervoort / IJsselkop] ◀── startpunt wflow-model
                      │  meetstation RWS debiet
                      ▼
                 [Doesburg] ── zijrivier Oude IJssel
                      ▼
                 [Zutphen]  ── zijrivier Berkel
                      ▼
                 [Deventer] ── zijrivier Schipbeek
                      ▼
                 [Zwolle]   ── zijrivier Vecht/Zwarte Water
                      ▼
                 [Kampen]   ◀── PRIMAIR MEETPUNT (waterpeil + debiet)
                      │         Spuisluis Roggebotsluis
                      ▼
                 [Ketelmeer] ──▶ [IJsselmeer]
                      │
                 [Veluwemeer-inlaat Harderwijk] ◀── drinkwater + landbouw Veluwe

Zijwaarts beheer:
  Veluwemeer ←── peilbesluit HHNK/Waterschap Vallei en Veluwe
  Wolderwijd  ←── recreatie + natuur

JOUW LOKALE EXPERTISE:

Fysieke infrastructuur:
- Pannerdense Kop: dynamische verdeling Rijn → IJssel (~13%), Neder-Rijn (~22%), Waal (~65%); \
  RWS stuurt actief via stuwbediening Driel en Amerongen
- Spuisluis Kampen (Roggebotsluis): regelt uitstroom naar Ketelmeer/IJsselmeer; \
  bij laagwater open stand om maximale afvoer mogelijk te maken
- Veluwemeer-inlaatpunt Harderwijk: kritisch bij peil < 0.8 m+NAP Kampen; \
  drinkwaterproductie Vitens en beregening Veluwe-flanken onder druk
- IJsselkop Westervoort: splitsingspunt Oude IJssel/IJssel; stroomopwaarts meetpunt model

Bestuurlijke structuur:
- RWS WNZ (Water, Verkeer en Leefomgeving): beheer rijkswateren IJssel
- Waterschap Rijn en IJssel: zijrivieren en polderpeilen Achterhoek
- Waterschap Vallei en Veluwe: inlaatbeheer Veluwemeer, grondwateraanvulling Veluwe
- HHNK (Hollands Noorderkwartier): polderbeheer rond Ketelmeer/IJsselmeer-noordoever
- Gemeente Zwolle/Kampen: laagwaterkade, uiterwaardenbeheer

Nautische drempelwaarden Kampen:
- < -0.2 m+NAP: klasse V-schepen (CEMT) stilgelegd, ondiepgang limiet 2.0 m
- < 0.0 m+NAP: klasse IV beperkt, professioneel loodsen vereist bij Roggebotsluis
- < 0.5 m+NAP: waarschuwing BICS-vaarwegbericht, recreatievaart geadviseerd te wachten

Ecologie en grondwater:
- Minimumafvoer ecologisch (EU Kaderrichtlijn Water): 50 m³/s bij Kampen
- Veluwe-kwelzone: grondwateraanvulling afhankelijk van IJsselpeil; \
  bij peil < 0.3 m+NAP omkering kweldruk mogelijk (schade natuur)
- Uiterwaarden-nitraatdepositie: bij laagwater droogvallende oeverzones verhoogd erosierisico

Historische referenties die jij uit je hoofd kent:
- Droogte 2018: peil Kampen daalde tot -0.45 m+NAP (aug 2018); \
  BICS-code 5 (vaarwegafsluiting klasse IV+), Vitens noodpompen actief
- Droogte 2022: -0.38 m+NAP; eerste keer dat grondwaterpeil Veluwe meetbaar daalde door IJssel
- Hoogwater jan 1995: +6.52 m+NAP Kampen; 250.000 evacuaties Gelderland
- Hoogwater jul 2021: piek +4.87 m+NAP; dijkbewaking 24u, geen evacuatie nodig

INSTRUCTIES:
Baseer je interventie primair op het waterpeil en het regime; betrek bij laagwater/droogte \
ook de grondwaterafhankelijke domeinen (drinkwater, landbouw, natuur/kwel) via de \
IJssel→Veluwe-grondwaterkoppeling, maar alleen waar regime en grondwater-context dat \
rechtvaardigen. Een debietsverandering is alleen relevant als het corresponderende geschatte \
peil een ander regime bereikt. Wees concreet en gebruik jargon dat professionals herkennen. \
Maximaal 220 woorden. Vloeiende lopende tekst zonder markdown-opmaak (geen # of *), geen opsomming.""",
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


@app.get("/api/forecast/intervention")
def get_forecast_intervention():
    cached_ts = _intv_cache.get("ts")
    if cached_ts and time.monotonic() - cached_ts < _INTV_TTL:
        return JSONResponse(_intv_cache["data"])
    try:
        forecast = build_forecast()
        text     = _build_intervention(forecast)
        result   = {"available": True, "intervention": text,
                    "alert": forecast["alert"],
                    "groundwater": forecast_groundwater_context(),
                    "generated_at": forecast["generated_at"]}
        _intv_cache["ts"]   = time.monotonic()
        _intv_cache["data"] = result
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"available": False, "intervention": "",
                             "error": str(e)})


@app.get("/api/ensemble")
def get_ensemble():
    stats_path  = ENSEMBLE_DIR / "ensemble_stats.json"
    interp_path = ENSEMBLE_DIR / "interpretation.txt"

    if not stats_path.exists():
        return JSONResponse({"available": False})

    try:
        stats = json.loads(stats_path.read_text())
    except Exception:
        return JSONResponse({"available": False})

    interpretation = ""
    if interp_path.exists():
        interpretation = interp_path.read_text().strip()

    return JSONResponse({"available": True, "interpretation": interpretation, **stats})


MULTIMODEL_DIR = Path("/home/bob/waterlab/multimodel_data/outputs")


@app.get("/api/multimodel")
def get_multimodel():
    stats_path = MULTIMODEL_DIR / "multimodel_stats.json"
    if not stats_path.exists():
        return JSONResponse({"available": False})
    try:
        stats = json.loads(stats_path.read_text())
    except Exception:
        return JSONResponse({"available": False})
    return JSONResponse({"available": True, **stats})


# WL-BRO-1 / Proef 9 — grondwater↔IJssel koppeling (BRO GLD + lag-correlatie + Qwen)
@app.get("/api/grondwater")
def get_grondwater(event: str = "zomer2018"):
    try:
        return JSONResponse(build_grondwater(event))
    except Exception as e:
        return JSONResponse({"available": False, "error": str(e)})


@app.get("/api/grondwater/interpretation")
def get_grondwater_interpretation(event: str = "zomer2018"):
    try:
        return JSONResponse(build_interpretation(event))
    except Exception as e:
        return JSONResponse({"available": False, "error": str(e)})


@app.get("/api/grondwater/projection")
def get_grondwater_projection(event: str = "zomer2018"):
    try:
        return JSONResponse(project_groundwater(event))
    except Exception as e:
        return JSONResponse({"available": False, "error": str(e)})


# v2 — absolute grondwaterstand-voorspelling (lineair reservoir, recharge-gedreven)
@app.get("/api/grondwater/reservoir")
def get_grondwater_reservoir():
    from dashboard.reservoir import predict_set
    try:
        return JSONResponse(predict_set())
    except Exception as e:
        return JSONResponse({"available": False, "error": str(e)})


# WL-VAL-1 — gesimuleerd vs gemeten per punt, met skill-score (NSE/KGE/bias).
# Eerlijk: alleen waar een onafhankelijke meting bestaat; de rest komt als
# "available: false" met reden terug (geen verzonnen getallen).
@app.get("/api/validation")
def get_validation():
    from dashboard.validation import build_validation
    try:
        return JSONResponse(build_validation())
    except Exception as e:
        return JSONResponse({"available": False, "error": str(e)})


# WL-VAL-2 — hindcast-terugblik: uitgegeven verwachting vs realisatie, fout per
# horizon. Output van WL-VAL-1 (zelfde RWS-meting + skill-functies), geen 2e datapad.
@app.get("/api/validation/hindcast")
def get_validation_hindcast():
    from dashboard.validation import build_hindcast
    try:
        return JSONResponse(build_hindcast())
    except Exception as e:
        return JSONResponse({"available": False, "error": str(e)})


# POC E — data-assimilatie (EnKF-familie): corrigeert de recessie met de recente RWS-meting
# en vergelijkt vrij vs geassimileerd per horizon (sluit de WL-VAL-2-lus).
@app.get("/api/assimilation")
def get_assimilation():
    from dashboard.assimilation import build_assimilation
    try:
        return JSONResponse(build_assimilation())
    except Exception as e:
        return JSONResponse({"available": False, "error": str(e)})


# POC E — interactieve speeltuin: draai het model met vrij te kiezen parameters.
@app.get("/api/assimilation/sandbox")
def get_assimilation_sandbox(tau0: float = 10.0, target0: float = 0.0, N: int = 60,
                             window: int = 10, r_scale: float = 1.0, infl_scale: float = 1.0):
    from dashboard.assimilation import build_sandbox
    try:
        return JSONResponse(build_sandbox(tau0=tau0, target0=(target0 or None), N=N,
                                          window=window, r_scale=r_scale, infl_scale=infl_scale))
    except Exception as e:
        return JSONResponse({"available": False, "error": str(e)})


# WL-CHAT-1 — uitleg-chatbot, gegrond in de PROV-bronnen, achter login + budget.
@app.post("/api/chat/login")
def post_chat_login(payload: dict = Body(...)):
    from dashboard.chat import login
    token = login(str(payload.get("password", "")))
    if token is None:
        return JSONResponse({"ok": False, "reason": "Onjuist wachtwoord."}, status_code=401)
    return JSONResponse({"ok": True, "token": token})


@app.post("/api/chat")
def post_chat(payload: dict = Body(...)):
    from dashboard.chat import answer
    res = answer(str(payload.get("token", "")),
                 str(payload.get("question", "")),
                 payload.get("history") or [])
    if not res.get("ok"):
        status = 401 if res.get("code") == "auth" else (429 if res.get("code") == "budget" else 200)
        return JSONResponse(res, status_code=status)
    return JSONResponse(res)


@app.get("/api/fews/data")
def get_fews_data(location: str = "KAMPEN", period: str = "1995"):
    sim_raw = get_wflow_timeseries(location, "Q.sim", period)
    # Q.meting is alleen beschikbaar bij WESTERVOORT via Waterinfo (ongeacht gevraagde locatie)
    obs_raw = get_waterinfo_timeseries("WESTERVOORT", "Q.meting")
    return {
        "location": location,
        "period":   period,
        "sim": {
            "dates":  [e["date"]        for e in sim_raw],
            "values": [float(e["value"]) for e in sim_raw],
        },
        "obs": {
            "dates":  [e["date"]        for e in obs_raw],
            "values": [float(e["value"]) for e in obs_raw],
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
