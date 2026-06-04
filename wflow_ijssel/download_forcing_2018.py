"""Download ERA5-Land forcing voor mei–aug 2018 over het IJssel-stroomgebied.

Simulatieperiode: 2018-05-01 → 2018-08-31 (mei = warmup, jun–aug = droogte-analyse)
Uitvoer: data/input_2018/forcing-ijssel-2018.nc
"""
import logging
import zipfile
from pathlib import Path

import cdsapi
import netCDF4 as nc
import numpy as np
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT      = Path(__file__).parent
INPUT     = ROOT / "data" / "input"
INPUT_2018 = ROOT / "data" / "input_2018"

AREA = [53.5, 5.0, 51.0, 8.0]   # N, W, S, E — zelfde als 1995/2021

REQUESTS = [
    {"year": "2018", "month": "05"},
    {"year": "2018", "month": "06"},
    {"year": "2018", "month": "07"},
    {"year": "2018", "month": "08"},
]


def download_era5_2018() -> Path:
    INPUT_2018.mkdir(parents=True, exist_ok=True)
    raw_files = []
    c = cdsapi.Client()

    for req in REQUESTS:
        out = INPUT_2018 / f"era5_raw_{req['year']}_{req['month']}.nc"
        if out.exists() and not zipfile.is_zipfile(str(out)):
            logger.info("Al aanwezig: %s", out)
        else:
            if out.exists():
                out.unlink()
            tmp_zip = INPUT_2018 / f"era5_raw_{req['year']}_{req['month']}.zip"
            logger.info("Downloaden: %s-%s ...", req["year"], req["month"])
            c.retrieve(
                "reanalysis-era5-land",
                {
                    "variable": ["total_precipitation", "2m_temperature", "potential_evaporation"],
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
            with zipfile.ZipFile(str(tmp_zip)) as zf:
                nc_names = [n for n in zf.namelist() if n.endswith(".nc")]
                if not nc_names:
                    raise RuntimeError(f"Geen .nc in {tmp_zip}")
                zf.extract(nc_names[0], path=str(INPUT_2018))
                (INPUT_2018 / nc_names[0]).rename(out)
            tmp_zip.unlink()
            logger.info("Geëxtraheerd: %s", out)
        raw_files.append(out)

    logger.info("Samenvoegen en hernoemen variabelen ...")
    ds = xr.open_mfdataset(
        [str(f) for f in raw_files],
        combine="by_coords",
        drop_variables=["number", "expver"],
    )
    if "valid_time" in ds.dims:
        ds = ds.rename({"valid_time": "time"})

    rename_map = {}
    if "tp"  in ds: rename_map["tp"]  = "precip"
    if "t2m" in ds: rename_map["t2m"] = "temp"
    if "pev" in ds: rename_map["pev"] = "pet"
    if rename_map:
        ds = ds.rename(rename_map)

    ds["precip"] = (ds["precip"] * 1000).clip(min=0)
    ds["temp"]   = ds["temp"] - 273.15
    ds["pet"]    = (-ds["pet"] * 1000).clip(min=0)

    # Interpoleer naar modelgrid (zelfde grid als staticmaps)
    ds_static = xr.open_dataset(INPUT / "staticmaps-ijssel.nc")
    x_model = ds_static["x"].values
    y_model = ds_static["y"].values

    ds_interp = ds[["precip", "temp", "pet"]].interp(
        latitude=y_model, longitude=x_model, method="linear",
        kwargs={"fill_value": "extrapolate"},
    )
    ds_interp = ds_interp.rename({"latitude": "y", "longitude": "x"})

    # Vul NaN-cellen in actief stroomgebied met nearest neighbour
    with nc.Dataset(INPUT / "staticmaps-ijssel.nc", "r") as ds_nc:
        ldd = np.ma.filled(ds_nc.variables["wflow_ldd"][:], 0)
    active = (ldd > 0)
    ds_arr = ds_interp.load()
    for vname in ["precip", "temp", "pet"]:
        arr = ds_arr[vname].values
        for t in range(arr.shape[0]):
            slice2d = arr[t]
            nan_ys, nan_xs = np.where(np.isnan(slice2d) & active)
            for ny_i, nx_i in zip(nan_ys, nan_xs):
                ay, ax = np.where(active & ~np.isnan(slice2d))
                if len(ay) == 0:
                    arr[t, ny_i, nx_i] = 0.0
                else:
                    dist = (ay - ny_i)**2 + (ax - nx_i)**2
                    best = np.argmin(dist)
                    arr[t, ny_i, nx_i] = slice2d[ay[best], ax[best]]
        ds_arr[vname].values[:] = arr

    out_path = INPUT_2018 / "forcing-ijssel-2018.nc"
    ds_arr.to_netcdf(str(out_path))
    logger.info("Forcing 2018 klaar: %s (%d tijdstappen)", out_path, ds_arr.sizes["time"])
    return out_path


if __name__ == "__main__":
    download_era5_2018()
