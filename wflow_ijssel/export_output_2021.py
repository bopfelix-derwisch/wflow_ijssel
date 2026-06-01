"""Converteer Wflow NetCDF output 2021 naar JSON/GeoJSON voor het dashboard.

Uitvoer in data/output_2021/:
  river_day_YYYY-MM-DD.geojson  -- een per dag in juli/augustus 2021
  timeseries_kampen.json
  timeseries_westervoort.json
  kpis.json
"""
import json
import logging
from pathlib import Path

import numpy as np
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT         = Path(__file__).parent
OUTPUT       = ROOT / "data" / "output_2021"
STATIC_MAPS  = ROOT / "data" / "input" / "staticmaps-ijssel.nc"
UPAREA_THR   = 3000.0

KAMPEN_LON,      KAMPEN_LAT      = 5.496, 53.221
WESTERVOORT_LON, WESTERVOORT_LAT = 6.154, 51.987
DISCHARGE_THRESHOLD = 1500.0


def _nearest_idx(ds: xr.Dataset, lon: float, lat: float) -> tuple[int, int]:
    lons = ds["lon"].values if "lon" in ds else ds["x"].values
    lats = ds["lat"].values if "lat" in ds else ds["y"].values
    if lons.ndim == 1:
        xi = int(np.argmin(np.abs(lons - lon)))
        yi = int(np.argmin(np.abs(lats - lat)))
    else:
        dist = (lons - lon) ** 2 + (lats - lat) ** 2
        yi, xi = np.unravel_index(np.argmin(dist), dist.shape)
    return int(xi), int(yi)


def extract_timeseries(ds: xr.Dataset, lon: float, lat: float) -> dict:
    xi, yi = _nearest_idx(ds, lon, lat)
    q_vals = ds["q_river"].isel(lon=xi, lat=yi).values.tolist()
    h_vals = ds["h_river"].isel(lon=xi, lat=yi).values.tolist()
    dates  = [str(t)[:10] for t in ds["time"].values]
    return {"dates": dates, "q": q_vals, "h_nap": h_vals}


def build_river_geojson_day(ds: xr.Dataset, day_idx: int, river_mask: np.ndarray) -> dict:
    q_day = ds["q_river"].isel(time=day_idx).values
    h_day = ds["h_river"].isel(time=day_idx).values
    lons  = ds["lon"].values if "lon" in ds else ds["x"].values
    lats  = ds["lat"].values if "lat" in ds else ds["y"].values
    features = []
    ys, xs = np.where(river_mask)
    for yi, xi in zip(ys, xs):
        lon_val = float(lons[xi]) if lons.ndim == 1 else float(lons[yi, xi])
        lat_val = float(lats[yi]) if lats.ndim == 1 else float(lats[yi, xi])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon_val, lat_val]},
            "properties": {"q": round(float(q_day[yi, xi]), 2), "h": round(float(h_day[yi, xi]), 3)},
        })
    return {"type": "FeatureCollection", "features": features}


def compute_kpis(ds: xr.Dataset, lon: float, lat: float, threshold: float) -> dict:
    xi, yi   = _nearest_idx(ds, lon, lat)
    q_series = ds["q_river"].isel(lon=xi, lat=yi).values
    dates    = [str(t)[:10] for t in ds["time"].values]
    peak_idx = int(np.argmax(q_series))
    return {
        "peak_q":               round(float(q_series[peak_idx]), 1),
        "peak_date":            dates[peak_idx],
        "days_above_threshold": int(np.sum(q_series > threshold)),
    }


def export_all() -> None:
    nc_path = OUTPUT / "output_ijssel_2021.nc"
    assert nc_path.exists(), f"Voer eerst run_ijssel_2021.jl uit: {nc_path}"

    logger.info("Laden %s ...", nc_path)
    ds = xr.open_dataset(nc_path)

    ds_st      = xr.open_dataset(str(STATIC_MAPS))
    river_mask = np.flipud(ds_st["wflow_uparea"].values > UPAREA_THR)
    logger.info("Rivier-cellen: %d (wflow_uparea > %g km²)", int(river_mask.sum()), UPAREA_THR)

    for name, lon, lat in [
        ("kampen",      KAMPEN_LON,      KAMPEN_LAT),
        ("westervoort", WESTERVOORT_LON, WESTERVOORT_LAT),
    ]:
        ts   = extract_timeseries(ds, lon=lon, lat=lat)
        path = OUTPUT / f"timeseries_{name}.json"
        path.write_text(json.dumps(ts, indent=2))
        logger.info("Geschreven: %s", path)

    kpis = compute_kpis(ds, lon=KAMPEN_LON, lat=KAMPEN_LAT, threshold=DISCHARGE_THRESHOLD)
    (OUTPUT / "kpis.json").write_text(json.dumps(kpis, indent=2))
    logger.info("KPI's: %s", kpis)

    # GeoJSON voor alle dagen in juli en augustus 2021
    flood_indices = [
        i for i, t in enumerate(ds["time"].values)
        if str(t)[:7] in ("2021-07", "2021-08")
    ]
    for i in flood_indices:
        day  = str(ds["time"].values[i])[:10]
        gj   = build_river_geojson_day(ds, day_idx=i, river_mask=river_mask)
        path = OUTPUT / f"river_day_{day}.geojson"
        path.write_text(json.dumps(gj))
    logger.info("GeoJSON bestanden: %d dagen", len(flood_indices))
    logger.info("Export klaar.")


if __name__ == "__main__":
    export_all()
