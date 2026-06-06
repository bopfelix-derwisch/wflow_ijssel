"""FastAPI server: levert API-data en statische dashboard-bestanden."""
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

# Laad .env als ANTHROPIC_API_KEY nog niet in omgeving staat
_env_file = Path(__file__).parent.parent.parent / ".env"
if _env_file.exists() and not os.environ.get("ANTHROPIC_API_KEY"):
    for _line in _env_file.read_text().splitlines():
        if _line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = _line.split("=", 1)[1].strip()

ROOT       = Path(__file__).parent.parent
STATIC_DIR = Path(__file__).parent

OUTPUT_DIRS = {
    "1995":      ROOT / "data" / "output",
    "2018":      ROOT / "data" / "output_2018",
    "2021":      ROOT / "data" / "output_2021_real",   # echte gemeten inflow
    "2021synth": ROOT / "data" / "output_2021",        # synthetische inflow (vergelijking)
}

ENSEMBLE_DIR = Path("/home/bob/waterlab/ensemble_data/outputs")

app = FastAPI(title="IJssel Hoogwater Dashboard API")

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
        OUTPUT_DIRS.get(f"{base}synth", ROOT / "data" / f"output_{base}") / "measured_2021.json",
        OUTPUT_DIRS.get(base, ROOT / "data" / f"output_{base}") / "measured_2021.json",
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

# IJssel Kampen waterpeil referentiewaarden (m+NAP)
# Bron: RWS Watermanagementcentrum drempelwaarden
_H_REFS = {
    "laag":     0.5,   # zomerpeil, droogte-zorg
    "normaal":  1.2,   # gemiddeld zomerpeil
    "waakzaam": 3.0,   # eerste aandachtspeil
    "verhoogd": 4.2,   # verhoogd waakzaamheidsniveau
    "hoog":     5.4,   # dijkbewaking actief
    "extreem":  6.4,   # nabij dijkhoogte (referentie jan 1995: ~6.5 m+NAP)
}


def _build_intervention(forecast: dict) -> str:
    kpis  = forecast["kpis"]
    alert = forecast["alert"]
    alert_nl = {"normaal": "Normaal", "waakzaam": "Waakzaam",
                "verhoogd": "Verhoogd", "hoog": "HOOG"}

    h_now = kpis.get("current_h_kampen_m")
    h_str = f"{h_now:.2f} m+NAP" if h_now is not None else "niet beschikbaar"

    # RWS officiële waterpeil-verwachting (2–5 d)
    rws_fcast = forecast.get("rws_forecast", {})
    rws_lines = []
    for dt, hm in zip(rws_fcast.get("dates", []), rws_fcast.get("values_m", [])):
        rws_lines.append(f"  {dt}: {hm:.2f} m+NAP")
    rws_block = (
        "RWS officiële waterpeil-verwachting Kampen:\n" + "\n".join(rws_lines)
        if rws_lines else "RWS officiële verwachting: niet beschikbaar"
    )

    prompt = (
        f"Actuele IJssel-situatie bij Kampen ({forecast['generated_at']}):\n\n"
        f"Waakzaamheidsniveau: {alert_nl.get(alert, alert)}\n"
        f"Huidig waterpeil Kampen: {h_str}\n"
        f"Huidig debiet Kampen:    {kpis['current_q_kampen']} m³/s\n"
        f"Verwacht piekdebiet:     {kpis['peak_forecast_q']} m³/s op {kpis['peak_forecast_date']}\n"
        f"Dagen boven 1500 m³/s:  {kpis['days_above_threshold']}\n"
        f"Neerslag komende 14 d:  {kpis['total_precip_14d']} mm\n\n"
        f"{rws_block}\n\n"
        "Referentiepeilen Kampen (m+NAP):\n"
        + "\n".join(f"  {k}: {v} m" for k, v in _H_REFS.items()) + "\n\n"
        "Stel als waterbeheerder een concrete interventie voor die past bij de huidige situatie. "
        "Focus op het waterpeil, niet het debiet. Beschrijf acties in chronologische volgorde."
    )

    client = _anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=(
            "Je bent een ervaren waterbeheerder bij Rijkswaterstaat, district IJssel. "
            "Geef een beknopte, concrete interventie-aanbeveling in het Nederlands op basis "
            "van de actuele waterpeilsituatie. Maximaal 180 woorden. Doorlopende tekst, "
            "geen opsomming. Noem specifieke maatregelen in chronologische volgorde."
        ),
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
