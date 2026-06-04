"""Converteer Wflow NetCDF 2018 output naar JSON/GeoJSON voor het dashboard.

Uitvoer in data/output_2018/:
  river_day_2018-06-DD.geojson  -- een per dag in jun–aug 2018
  timeseries_kampen_2018.json
  kpis_2018.json
"""
import json
import logging
from pathlib import Path

import numpy as np
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT      = Path(__file__).parent
OUTPUT    = ROOT / "data" / "output_2018"

RIVER_LAT_MAX = 52.65
MAX_Q_THR     = 50.0    # droogte: ook lage-afvoer cellen tonen
MIN_LON       = 5.80
MAX_LON       = 6.25

KAMPEN_LON,      KAMPEN_LAT      = 5.921, 52.555
WESTERVOORT_LON, WESTERVOORT_LAT = 6.154, 51.987
LAAGWATER_THRESHOLD = 200.0   # m³/s — droogte-alarm Kampen (= days_above_threshold in kpis)


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
    return {"dates": dates, "q": q_vals, "h": h_vals}


def build_river_geojson_day(
    ds: xr.Dataset, day_idx: int, river_mask: np.ndarray
) -> dict:
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
            "properties": {
                "q": round(float(q_day[yi, xi]), 2),
                "h": round(float(h_day[yi, xi]), 3),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def compute_kpis(ds: xr.Dataset, lon: float, lat: float, threshold: float) -> dict:
    xi, yi = _nearest_idx(ds, lon, lat)
    q_series = ds["q_river"].isel(lon=xi, lat=yi).values
    dates    = [str(t)[:10] for t in ds["time"].values]

    # Analyse-periode: jun–aug 2018 (na warmup mei)
    analysis = [(i, q) for i, (d, q) in enumerate(zip(dates, q_series)) if d[:7] in ("2018-06", "2018-07", "2018-08")]
    if not analysis:
        return {}
    idxs, qs = zip(*analysis)
    qs = list(qs)
    peak_idx_local = int(np.argmax(qs))
    return {
        # Compatible with generic dashboard KPI rendering
        "peak_q":               round(float(qs[peak_idx_local]), 1),
        "peak_date":            dates[idxs[peak_idx_local]],
        "days_above_threshold": int(np.sum(np.array(qs) > threshold)),   # days with "reasonable" flow
        "laagwater_threshold":  threshold,
        "min_q":                round(float(np.min(qs)), 1),
        "min_date":             dates[idxs[int(np.argmin(qs))]],
        "mean_q_summer":        round(float(np.mean(qs)), 1),
    }


def export_all() -> None:
    nc_path = OUTPUT / "output_ijssel_2018.nc"
    if not nc_path.exists():
        raise FileNotFoundError(f"Voer eerst run_ijssel_2018.jl uit: {nc_path}")

    logger.info("Laden %s ...", nc_path)
    ds = xr.open_dataset(nc_path)

    max_q    = ds["q_river"].max(dim="time").values
    lons_1d  = ds["lon"].values if "lon" in ds else ds["x"].values
    lon_mask = (lons_1d >= MIN_LON) & (lons_1d < MAX_LON)
    river_mask = (max_q > MAX_Q_THR) & ~np.isnan(max_q) & lon_mask[np.newaxis, :]
    lat_key  = "lat" if "lat" in ds else "y"
    lat_cut  = int(np.searchsorted(ds[lat_key].values, RIVER_LAT_MAX))
    river_mask[lat_cut:, :] = False
    logger.info("Rivier-cellen: %d", int(river_mask.sum()))

    # Write timeseries for both stations (same filenames as 1995/2021 — within output_2018/)
    for name, lon, lat in [
        ("kampen",      KAMPEN_LON,      KAMPEN_LAT),
        ("westervoort", WESTERVOORT_LON, WESTERVOORT_LAT),
    ]:
        ts = extract_timeseries(ds, lon=lon, lat=lat)
        ts_path = OUTPUT / f"timeseries_{name}.json"
        ts_path.write_text(json.dumps(ts, indent=2))
        logger.info("Geschreven: %s", ts_path)

    kpis = compute_kpis(ds, lon=KAMPEN_LON, lat=KAMPEN_LAT, threshold=LAAGWATER_THRESHOLD)
    kpis_path = OUTPUT / "kpis.json"
    kpis_path.write_text(json.dumps(kpis, indent=2))
    logger.info("KPI's 2018: %s", kpis)

    summer_indices = [
        i for i, t in enumerate(ds["time"].values)
        if str(t)[:7] in ("2018-06", "2018-07", "2018-08")
    ]
    for i in summer_indices:
        day = str(ds["time"].values[i])[:10]
        gj = build_river_geojson_day(ds, day_idx=i, river_mask=river_mask)
        path = OUTPUT / f"river_day_{day}.geojson"
        path.write_text(json.dumps(gj))
    logger.info("GeoJSON bestanden: %d dagen", len(summer_indices))
    logger.info("Export 2018 klaar.")


if __name__ == "__main__":
    export_all()
