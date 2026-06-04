"""FastAPI server: levert API-data en statische dashboard-bestanden."""
import json
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from dashboard.forecast import build_forecast

ROOT       = Path(__file__).parent.parent
STATIC_DIR = Path(__file__).parent

OUTPUT_DIRS = {
    "1995":      ROOT / "data" / "output",
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
