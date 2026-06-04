"""Extraheer Kampen-tijdreeks uit Wflow NC-output; verwijder NC na extractie."""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import xarray as xr


def _nearest_idx(coord: np.ndarray, target: float) -> int:
    return int(np.argmin(np.abs(coord - target)))


def collect(output_nc: Path, station_lon: float, station_lat: float,
            threshold: float, delete_nc: bool = True) -> dict:
    """
    Retourneert dict met:
      dates, q, h_nap, peak_q, peak_date, days_above_threshold
    """
    ds = xr.open_dataset(str(output_nc))

    # Support both lon/lat and x/y dimension names
    if "lon" in ds.dims:
        lon_dim, lat_dim = "lon", "lat"
    else:
        lon_dim, lat_dim = "x", "y"

    lons = ds[lon_dim].values
    lats = ds[lat_dim].values

    xi = _nearest_idx(lons, station_lon)
    yi = _nearest_idx(lats, station_lat)

    q    = ds["q_river"].isel({lon_dim: xi, lat_dim: yi}).values.tolist()
    h    = ds["h_river"].isel({lon_dim: xi, lat_dim: yi}).values.tolist()
    dates = [str(t)[:10] for t in ds["time"].values]
    ds.close()

    q_arr    = np.array(q)
    peak_idx = int(np.argmax(q_arr))

    result = {
        "dates":               dates,
        "q":                   [round(v, 2) for v in q],
        "h":                   [round(v, 3) for v in h],
        "peak_q":              round(float(q_arr[peak_idx]), 1),
        "peak_date":           dates[peak_idx],
        "days_above_threshold": int(np.sum(q_arr > threshold)),
    }

    if delete_nc:
        output_nc.unlink(missing_ok=True)

    return result


def save_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
