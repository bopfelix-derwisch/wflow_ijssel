"""Download ERA5-Land forcing voor dec 1994 – jan 1995 over het IJssel-stroomgebied.

Vereist:
  - ~/.cdsapirc met geldige CDS API credentials
  - data/input/staticmaps-ijssel.nc (voer eerst build_staticmaps_copernicus.py uit)

Uitvoer: data/input/forcing-ijssel.nc  (op modelgrid, klaar voor Wflow)
"""
import logging
import zipfile
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
        if out.exists() and not zipfile.is_zipfile(str(out)):
            logger.info("Al aanwezig: %s", out)
        else:
            if out.exists():
                out.unlink()  # verwijder oude ZIP die als .nc was opgeslagen
            tmp_zip = INPUT / f"era5_raw_{req['year']}_{req['month']}.zip"
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
                    "data_format": "netcdf",
                    "download_format": "zip",
                    "area": AREA,
                },
                str(tmp_zip),
            )
            # Extraheer het NetCDF-bestand uit de ZIP
            with zipfile.ZipFile(str(tmp_zip)) as zf:
                nc_names = [n for n in zf.namelist() if n.endswith(".nc")]
                if not nc_names:
                    raise RuntimeError(f"Geen .nc bestand in {tmp_zip}: {zf.namelist()}")
                zf.extract(nc_names[0], path=str(INPUT))
                extracted = INPUT / nc_names[0]
                extracted.rename(out)
            tmp_zip.unlink()
            logger.info("Geëxtraheerd: %s", out)
        raw_files.append(out)

    logger.info("Samenvoegen en hernoemen variabelen ...")
    ds = xr.open_mfdataset(
        [str(f) for f in raw_files],
        combine="by_coords",
        drop_variables=["number", "expver"],
    )

    # Nieuwe CDS API noemt tijdsdimensie 'valid_time' — hernoemen naar 'time'
    if "valid_time" in ds.dims:
        ds = ds.rename({"valid_time": "time"})

    # ERA5-Land variabelenamen → Wflow-conventie
    rename_map = {}
    if "tp"  in ds: rename_map["tp"]  = "precip"
    if "t2m" in ds: rename_map["t2m"] = "temp"
    if "pev" in ds: rename_map["pev"] = "pet"
    if rename_map:
        ds = ds.rename(rename_map)

    # Eenheden corrigeren
    ds["precip"] = (ds["precip"] * 1000).clip(min=0)   # m → mm/dag
    ds["temp"]   = ds["temp"] - 273.15                  # K → °C
    ds["pet"]    = (-ds["pet"] * 1000).clip(min=0)      # m (negatief) → mm/dag

    # Interpoleren naar modelgrid (Wflow vereist forcing op hetzelfde grid als staticmaps)
    staticmaps = INPUT / "staticmaps-ijssel.nc"
    assert staticmaps.exists(), (
        f"Voer eerst build_staticmaps_copernicus.py uit: {staticmaps}"
    )
    ds_static = xr.open_dataset(staticmaps)
    x_model = ds_static["x"].values  # 1-D, stijgend
    y_model = ds_static["y"].values  # 1-D, kan dalend zijn

    ds_interp = ds[["precip", "temp", "pet"]].interp(
        latitude=y_model,
        longitude=x_model,
        method="linear",
        kwargs={"fill_value": "extrapolate"},
    )
    ds_interp = ds_interp.rename({"latitude": "y", "longitude": "x"})

    out_path = INPUT / "forcing-ijssel.nc"
    ds_interp.to_netcdf(str(out_path))
    logger.info("Forcing geïnterpoleerd naar modelgrid (%dx%d): %s", len(y_model), len(x_model), out_path)
    return out_path


if __name__ == "__main__":
    download_era5()
