"""Schrijf de forcing-NetCDF voor een operationele wflow-run.

Schema exact als `wflow_ijssel/data/input/forcing-ijssel.nc`: dims
(time, y, x) = (n, 240, 300), variabelen precip/temp/pet/inflow, y AFLOPEND.

BELANGRIJK: wflow negeert `starttime`/`endtime` uit de TOML (gevolg van de
ARM-JIT-patches, zie tools/arm_patches/README.md). Het rekenvenster komt
volledig uit de tijdas van dít bestand — hier wordt het venster dus bepaald.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from wflow_ijssel.operational.meteo import MODEL_X, MODEL_Y

logger = logging.getLogger(__name__)

# Instroom-randvoorwaarde: Westervoort, conform docs/WL-PROV-2_schematisatie.md
WESTERVOORT_LON = 6.154
WESTERVOORT_LAT = 51.987


def westervoort_cell(dst_y, dst_x) -> tuple[int, int]:
    """(rij, kolom) van de cel die het dichtst bij Westervoort ligt."""
    rij = int(np.argmin(np.abs(np.asarray(dst_y) - WESTERVOORT_LAT)))
    kol = int(np.argmin(np.abs(np.asarray(dst_x) - WESTERVOORT_LON)))
    return rij, kol


def write_forcing(path, dates, precip, pet, temp, inflow_series) -> Path:
    """Schrijf de forcing weg. Retourneert het pad."""
    path = Path(path)
    n = len(dates)
    vorm = (n, len(MODEL_Y), len(MODEL_X))

    for naam, veld in (("precip", precip), ("pet", pet), ("temp", temp)):
        if np.shape(veld) != vorm:
            raise ValueError(f"{naam} moet vorm {vorm} hebben, kreeg {np.shape(veld)}")
    if len(inflow_series) != n:
        raise ValueError(f"inflow_series moet {n} waarden hebben, kreeg {len(inflow_series)}")

    inflow = np.zeros(vorm, dtype="float32")
    rij, kol = westervoort_cell(MODEL_Y, MODEL_X)
    inflow[:, rij, kol] = np.asarray(inflow_series, dtype="float32")

    ds = xr.Dataset(
        {
            "precip": (("time", "y", "x"), np.asarray(precip, dtype="float32")),
            "temp":   (("time", "y", "x"), np.asarray(temp, dtype="float32")),
            "pet":    (("time", "y", "x"), np.asarray(pet, dtype="float32")),
            "inflow": (("time", "y", "x"), inflow),
        },
        coords={"time": pd.to_datetime(list(dates)), "y": MODEL_Y, "x": MODEL_X},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path)
    ds.close()
    logger.info("forcing geschreven: %s (%d dagen, %s .. %s)", path, n, dates[0], dates[-1])
    return path


def build_forcing(path, start: str, end: str) -> dict:
    """Haal meteo + randvoorwaarde op en schrijf de forcing voor [start, end]."""
    from wflow_ijssel.operational import boundary, meteo

    lats, lons = meteo.grid_points()
    data = meteo.fetch_daily(lats, lons, start, end)
    dates = data["dates"]

    precip = meteo.to_model_grid(data["precip"], lats, lons, MODEL_Y, MODEL_X)
    pet = meteo.to_model_grid(data["pet"], lats, lons, MODEL_Y, MODEL_X)
    temp = meteo.to_model_grid(data["temp"], lats, lons, MODEL_Y, MODEL_X)

    bnd = boundary.build_boundary(dates)
    write_forcing(path, dates, precip, pet, temp, bnd["values"])
    return {"path": str(path), "dates": dates, "sources": bnd["sources"],
            "ratio": bnd["ratio"]}
