"""Vervang synthetische inflow in forcing-ijssel-2021.nc door gemeten RWS-debiet.

Bron: measured_2021.json (station westervoort.ijsselkop, RWS Waterinfo via rws-waterinfo 1.0.1)
Uitvoer: data/input_2021/forcing-ijssel-2021-real.nc
"""
import json
import logging
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT       = Path(__file__).parent
INPUT_2021 = ROOT / "data" / "input_2021"
INPUT      = ROOT / "data" / "input"
MEASURED   = ROOT / "data" / "output_2021" / "measured_2021.json"


def find_westervoort_cell() -> tuple[int, int]:
    ds = xr.open_dataset(INPUT / "staticmaps-ijssel.nc")
    xi = int(np.argmin(np.abs(ds["x"].values - 6.154)))
    yi = int(np.argmin(np.abs(ds["y"].values - 51.987)))
    return xi, yi


def build() -> None:
    src = INPUT_2021 / "forcing-ijssel-2021.nc"
    dst = INPUT_2021 / "forcing-ijssel-2021-real.nc"

    # Gemeten dagdebieten uit measured_2021.json
    m = json.loads(MEASURED.read_text())
    w = m["westervoort"]
    measured = pd.Series(
        w["q"],
        index=pd.to_datetime(w["dates"]),
        dtype=np.float32,
    )
    logger.info("Gemeten Westervoort: %d dagen, piek=%.0f m³/s op %s",
                len(measured), measured.max(), measured.idxmax().date())

    # Forcingbestand kopiëren en inflow vervangen
    shutil.copy2(src, dst)
    ds = xr.open_dataset(str(dst))

    sim_times = pd.DatetimeIndex(ds["time"].values)
    xi, yi = find_westervoort_cell()

    ny = ds.sizes["y"]
    nx = ds.sizes["x"]
    new_inflow = np.zeros((len(sim_times), ny, nx), dtype=np.float32)

    for t_idx, t in enumerate(sim_times):
        date = t.normalize()  # afkappen naar dag
        if date in measured.index:
            new_inflow[t_idx, yi, xi] = float(measured[date])
        else:
            # buiten meetbereik: gebruik dichtstbijzijnde waarde
            nearest = measured.index[np.argmin(np.abs(measured.index - date))]
            new_inflow[t_idx, yi, xi] = float(measured[nearest])
            logger.warning("Geen meting voor %s, gebruikt %s (%.0f m³/s)",
                           date.date(), nearest.date(), measured[nearest])

    # Vervang inflow-variabele
    inflow_da = xr.DataArray(
        new_inflow, dims=["time", "y", "x"],
        coords={"time": ds["time"], "y": ds["y"], "x": ds["x"]},
        attrs={"units": "m3 s-1", "long_name": "Measured inflow at Westervoort (RWS)"},
    )
    ds["inflow"] = inflow_da
    ds.close()

    # Opslaan via tmp zodat we niet een half-geschreven bestand achterlaten
    tmp = dst.with_suffix(".tmp.nc")
    xr.open_dataset(str(dst)).assign(inflow=inflow_da).to_netcdf(str(tmp))
    tmp.replace(dst)

    logger.info("Geschreven: %s", dst)
    peak_idx = np.unravel_index(np.argmax(new_inflow[:, yi, xi]), (len(sim_times),))
    logger.info("Piek inflow in NC: %.0f m³/s op %s",
                new_inflow[peak_idx[0], yi, xi],
                sim_times[peak_idx[0]].date())


if __name__ == "__main__":
    build()
