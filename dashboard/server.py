"""FastAPI server: levert API-data en statische dashboard-bestanden."""
import collections
import json
import os
import re
import time
from pathlib import Path

import anthropic as _anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
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
