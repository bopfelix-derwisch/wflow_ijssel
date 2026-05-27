"""FastAPI server: levert API-data en statische dashboard-bestanden."""
import json
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT       = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "data" / "output"
STATIC_DIR = Path(__file__).parent

app = FastAPI(title="IJssel Hoogwater Dashboard API")

if os.path.isdir(str(STATIC_DIR)):
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/kpis")
def get_kpis():
    path = OUTPUT_DIR / "kpis.json"
    if not path.exists():
        raise HTTPException(503, "Voer eerst export_output.py uit")
    return JSONResponse(json.loads(path.read_text()))


@app.get("/api/timeseries/{station}")
def get_timeseries(station: str):
    if station not in ("kampen", "westervoort"):
        raise HTTPException(400, f"Onbekend station: {station}")
    path = OUTPUT_DIR / f"timeseries_{station}.json"
    if not path.exists():
        raise HTTPException(503, f"Geen data voor {station}")
    return JSONResponse(json.loads(path.read_text()))


@app.get("/api/river/{day}")
def get_river_day(day: str):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise HTTPException(400, "Ongeldig datumformaat (verwacht YYYY-MM-DD)")
    path = OUTPUT_DIR / f"river_day_{day}.geojson"
    if not path.exists():
        raise HTTPException(404, f"Geen data voor dag {day}")
    return JSONResponse(json.loads(path.read_text()))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
