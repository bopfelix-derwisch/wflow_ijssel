"""Download dagdebiet bij Westervoort (IJssel) via RWS Waterinfo API.

Uitvoer: data/input/inflow-westervoort.nc  (variabele: inflow, dims: time/y/x)
De inflow-variabele heeft waarden != 0 alleen op de gridcel van Westervoort.
"""
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
INPUT = ROOT / "data" / "input"

RWS_URL = (
    "https://waterwebservices.rijkswaterstaat.nl"
    "/ONLINEWAARNEMINGENSERVICES_DBO/OphalenWaarnemingen"
)

RWS_PAYLOAD = {
    "AquoMetadataLijst": [{
        "Eenheid": {"Code": "m3/s"},
        "Grootheid": {"Code": "Q"},
        "Hoedanigheid": {"Code": "NVT"},
    }],
    "Locatie": {"Code": "WESL", "X": 189384, "Y": 441601},
    "Periode": {
        "Begindatumtijd": "1994-12-01T00:00:00.000+01:00",
        "Einddatumtijd": "1995-02-01T00:00:00.000+01:00",
    },
}


def parse_rws_response(response: dict) -> pd.Series:
    """Parseer RWS Waterinfo JSON-response naar een pd.Series (datum -> m3/s)."""
    metingen = response["WaarnemingenLijst"][0]["MetingenLijst"]
    data = {
        pd.Timestamp(m["Tijdstip"]).normalize(): m["Meetwaarde"]["Waarde_Numeriek"]
        for m in metingen
    }
    series = pd.Series(data).sort_index()
    series.index = series.index.tz_localize(None)
    return series


def inflow_to_netcdf(
    discharge: pd.Series,
    x_idx: int,
    y_idx: int,
    shape: tuple[int, int],
    out_path: Path,
) -> None:
    """Schrijf debiet-tijdreeks naar NetCDF met dims (time, y, x)."""
    ny, nx = shape
    data = np.zeros((len(discharge), ny, nx), dtype=np.float32)
    data[:, y_idx, x_idx] = discharge.values.astype(np.float32)

    ds = xr.Dataset(
        {"inflow": (["time", "y", "x"], data)},
        coords={"time": discharge.index},
    )
    ds["inflow"].attrs["units"] = "m3 s-1"
    ds.to_netcdf(str(out_path))
    logger.info("Geschreven: %s", out_path)


def find_westervoort_cell(staticmaps_path: Path) -> tuple[int, int]:
    """Vind de gridcel die het dichtst bij Westervoort (6.17E, 51.97N) ligt."""
    ds = xr.open_dataset(staticmaps_path)
    lon = ds["lon"].values if "lon" in ds else ds["x"].values
    lat = ds["lat"].values if "lat" in ds else ds["y"].values

    target_lon, target_lat = 6.17, 51.97

    if lon.ndim == 1:
        x_idx = int(np.argmin(np.abs(lon - target_lon)))
        y_idx = int(np.argmin(np.abs(lat - target_lat)))
    else:
        dist = (lon - target_lon) ** 2 + (lat - target_lat) ** 2
        y_idx, x_idx = np.unravel_index(np.argmin(dist), dist.shape)
    return int(x_idx), int(y_idx)


def download() -> Path:
    logger.info("Ophalen debiet Westervoort van RWS Waterinfo ...")
    resp = requests.post(RWS_URL, json=RWS_PAYLOAD, timeout=30)
    resp.raise_for_status()
    discharge = parse_rws_response(resp.json())

    full_index = pd.date_range("1994-12-01", "1995-01-31", freq="D")
    discharge = discharge.reindex(full_index).interpolate("linear")
    logger.info("Debiet opgehaald: %d dagen, piek=%.0f m3/s", len(discharge), discharge.max())

    staticmaps = INPUT / "staticmaps-ijssel.nc"
    assert staticmaps.exists(), f"Voer eerst build_staticmaps.py uit: {staticmaps}"
    x_idx, y_idx = find_westervoort_cell(staticmaps)
    logger.info("Westervoort gridcel: x=%d, y=%d", x_idx, y_idx)

    ds_static = xr.open_dataset(staticmaps)
    ny = ds_static.dims.get("y", ds_static.dims.get("latitude"))
    nx = ds_static.dims.get("x", ds_static.dims.get("longitude"))

    out = INPUT / "inflow-westervoort.nc"
    inflow_to_netcdf(discharge, x_idx=x_idx, y_idx=y_idx, shape=(ny, nx), out_path=out)
    return out


if __name__ == "__main__":
    download()
