"""Download ERA5-Land forcing voor dec 1994 – jan 1995 over het IJssel-stroomgebied.

Vereist: ~/.cdsapirc met geldige CDS API credentials.
Uitvoer: data/input/forcing-ijssel.nc
"""
import logging
from pathlib import Path

import cdsapi
import numpy as np
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
INPUT = ROOT / "data" / "input"

# Bounding box IJssel stroomgebied: N, W, S, E (iets ruimer dan stroomgebied)
AREA = [53.5, 5.0, 51.0, 8.0]

# Simulatieperiode: dec 1994 (spin-up) + jan 1995 (analyse)
REQUESTS = [
    {"year": "1994", "month": "12"},
    {"year": "1995", "month": "01"},
]


def download_era5() -> Path:
    raw_files = []
    c = cdsapi.Client()

    for req in REQUESTS:
        out = INPUT / f"era5_raw_{req['year']}_{req['month']}.nc"
        if out.exists():
            logger.info("Al aanwezig: %s", out)
        else:
            logger.info("Downloaden: %s-%s ...", req["year"], req["month"])
            c.retrieve(
                "reanalysis-era5-land",
                {
                    "variable": [
                        "total_precipitation",
                        "2m_temperature",
                        "potential_evaporation",
                    ],
                    "year": req["year"],
                    "month": req["month"],
                    "day": [f"{d:02d}" for d in range(1, 32)],
                    "time": "00:00",
                    "format": "netcdf",
                    "area": AREA,
                },
                str(out),
            )
        raw_files.append(out)

    logger.info("Samenvoegen en hernoemen variabelen ...")
    ds = xr.open_mfdataset([str(f) for f in raw_files], combine="by_coords")

    # ERA5-Land variabelenamen → Wflow-conventie
    ds = ds.rename({
        "tp":  "precip",
        "t2m": "temp",
        "pev": "pet",
    })

    # Eenheden corrigeren
    ds["precip"] = (ds["precip"] * 1000).clip(min=0)   # m → mm/dag
    ds["temp"]   = ds["temp"] - 273.15                  # K → °C
    ds["pet"]    = (-ds["pet"] * 1000).clip(min=0)      # m (negatief) → mm/dag

    out_path = INPUT / "forcing-ijssel.nc"
    ds[["precip", "temp", "pet"]].to_netcdf(str(out_path))
    logger.info("Klaar: %s", out_path)
    return out_path


if __name__ == "__main__":
    download_era5()
