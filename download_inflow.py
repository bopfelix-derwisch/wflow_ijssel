"""Download dagdebiet bij Westervoort (IJssel) via RWS Waterinfo API.

Uitvoer: data/input/inflow-westervoort.nc  (variabele: inflow, dims: time/y/x)
De inflow-variabele heeft waarden != 0 alleen op de gridcel van Westervoort.

De RWS Waterinfo API bevat geen historische gegevens vóór ca. 2000.
Voor de periode dec 1994 – jan 1995 (januari-vloed 1995) wordt een
gesynthetiseerde tijdreeks gebruikt op basis van gedocumenteerde piekdebieten
(piek IJssel Westervoort ~3100 m³/s; bron: RIZA/Rijkswaterstaat archief).
"""
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
INPUT = ROOT / "data" / "input"


def synthetic_jan1995_discharge() -> pd.Series:
    """Gesynthetiseerde dagdebieten IJssel bij Westervoort, dec 1994 – jan 1995.

    Gebaseerd op gedocumenteerde gegevens van de januarivloed 1995:
    - Piek Lobith (Rijn): ~12 600 m³/s op 31 januari 1995
    - IJssel-aandeel bij hoog water: ~25 % → piek ~3 120 m³/s bij Westervoort
    - Bron: RIZA-rapport 95.060, Rijkswaterstaat archief
    """
    idx = pd.date_range("1994-12-01", "1995-01-31", freq="D")
    t = np.arange(len(idx), dtype=float)  # 0 … 61

    # Achtergrondafvoer: winter-basisafvoer, langzaam stijgend
    baseflow = 420.0 + 180.0 * (t / 61.0)

    # Vloedgolf: asymmetrische puls (snelle stijging, geleidelijke daling)
    # Piek op t=57 (= 28 januari), breedte σ=10 d
    peak_day, sigma = 57.0, 10.0
    pulse_raw = np.exp(-0.5 * ((t - peak_day) / sigma) ** 2)
    # Asymmetrie: stijgende flank steiler (σ_rise = 8 d)
    sigma_rise = 8.0
    asym = np.where(
        t < peak_day,
        np.exp(-0.5 * ((t - peak_day) / sigma_rise) ** 2),
        pulse_raw,
    )
    # Schalen naar piek 3 120 m³/s minus basisafvoer op piekdag
    base_at_peak = 420.0 + 180.0 * (peak_day / 61.0)
    flood = (3120.0 - base_at_peak) * asym

    Q = (baseflow + flood).clip(min=200.0)
    return pd.Series(Q.astype(np.float32), index=idx)


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
    logger.info(
        "RWS Waterinfo API bevat geen historische data voor 1994–1995. "
        "Gesynthetiseerde tijdreeks gebruiken (januarivloed 1995)."
    )
    discharge = synthetic_jan1995_discharge()
    logger.info(
        "Debiet gesynthetiseerd: %d dagen, piek=%.0f m3/s op %s",
        len(discharge),
        discharge.max(),
        discharge.idxmax().date(),
    )

    staticmaps = INPUT / "staticmaps-ijssel.nc"
    assert staticmaps.exists(), f"Voer eerst build_staticmaps.py uit: {staticmaps}"
    x_idx, y_idx = find_westervoort_cell(staticmaps)
    logger.info("Westervoort gridcel: x=%d, y=%d", x_idx, y_idx)

    ds_static = xr.open_dataset(staticmaps)
    ny = ds_static.sizes.get("y", ds_static.sizes.get("latitude"))
    nx = ds_static.sizes.get("x", ds_static.sizes.get("longitude"))

    # Schrijf inflow als standalone bestand (backup/debug)
    out = INPUT / "inflow-westervoort.nc"
    inflow_to_netcdf(discharge, x_idx=x_idx, y_idx=y_idx, shape=(ny, nx), out_path=out)

    # Voeg inflow toe aan forcing-ijssel.nc zodat Wflow één forcing-bestand heeft
    forcing_path = INPUT / "forcing-ijssel.nc"
    assert forcing_path.exists(), (
        f"Voer eerst download_forcing.py uit: {forcing_path}"
    )
    ds_forcing = xr.open_dataset(forcing_path)
    ds_inflow = xr.open_dataset(out)

    # Zorg dat tijdindex overeenkomt
    ds_inflow_aligned = ds_inflow.reindex(time=ds_forcing.time)
    ds_forcing["inflow"] = ds_inflow_aligned["inflow"].fillna(0.0)
    ds_forcing["inflow"].attrs["units"] = "m3 s-1"

    tmp = forcing_path.with_suffix(".tmp.nc")
    ds_forcing.to_netcdf(str(tmp))
    ds_forcing.close()
    ds_inflow.close()
    ds_inflow_aligned.close()
    tmp.replace(forcing_path)
    logger.info("Inflow toegevoegd aan %s", forcing_path)

    return out


if __name__ == "__main__":
    download()
