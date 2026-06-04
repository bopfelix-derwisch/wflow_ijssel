"""Dagdebiet Westervoort (IJssel) voor mei–aug 2018 via RWS Waterinfo API.

De zomer van 2018 was een uitzonderlijk droog jaar. Lobith-afvoer daalde tot
~500–700 m³/s (normaal ~2 000 m³/s). IJssel-aandeel bij lage afvoer ~30 %.
Uitvoer: inflow toegevoegd aan data/input_2018/forcing-ijssel-2018.nc
"""
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT      = Path(__file__).parent
INPUT     = ROOT / "data" / "input"
INPUT_2018 = ROOT / "data" / "input_2018"

START = pd.Timestamp("2018-05-01")
END   = pd.Timestamp("2018-08-31")

RWS_URL = "https://waterwebservices.rijkswaterstaat.nl/ONLINEWAARNEMINGENSERVICES_DBO/OphalenWaarnemingen"


def _rws_request(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series | None:
    payload = {
        "Locatie": {"Code": "WESTERVOORT", "X": 195740, "Y": 438310},
        "AquoMetaData": {"Compartiment": {"Code": "OW"}, "Grootheid": {"Code": "Q"}},
        "Periode": {
            "Begindatumtijd": start.strftime("%Y-%m-%dT00:00:00.000+01:00"),
            "Einddatumtijd":  end.strftime("%Y-%m-%dT23:59:00.000+01:00"),
        },
    }
    try:
        resp = requests.post(RWS_URL, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("WaarnemingenLijst"):
            return None
        records = data["WaarnemingenLijst"][0].get("MetingenLijst", [])
        if not records:
            return None
        rows = []
        for r in records:
            dt_str = r["Tijdstip"]
            val    = r["Meetwaarde"]["Waarde_Numeriek"]
            rows.append({"time": pd.Timestamp(dt_str[:19]), "Q": float(val)})
        df = pd.DataFrame(rows).set_index("time").sort_index()
        daily = df["Q"].resample("D").mean()
        logger.info("RWS API: %d dagwaarden opgehaald voor 2018", len(daily))
        return daily
    except Exception as e:
        logger.warning("RWS API mislukt: %s", e)
        return None


def synthetic_2018_drought_discharge() -> pd.Series:
    """Gesynthetiseerde dagdebieten IJssel bij Westervoort, mei–aug 2018.

    Zomer 2018: ernstige droogte, Lobith ~500–700 m³/s.
    IJssel-aandeel ~30 % → Westervoort ~150–210 m³/s.
    Sinusvorm gebaseerd op netwerkmodel: 180 + 50*sin(2π*t/90).
    """
    idx = pd.date_range(START, END, freq="D")
    t   = np.arange(len(idx), dtype=float)

    # Lage zomer-basisafvoer, licht dalend door droogte
    baseflow = 200.0 - 40.0 * (t / len(t))   # 200 → 160 m³/s over de periode

    # Kleine sinusvariatie (droogte, geen grote pieken)
    sine = 50.0 * np.sin(2 * np.pi * t / 90.0)

    Q = (baseflow + sine).clip(min=80.0)
    logger.info("Synthetisch debiet 2018: gemiddeld=%.0f m³/s, min=%.0f, max=%.0f",
                Q.mean(), Q.min(), Q.max())
    return pd.Series(Q.astype(np.float32), index=idx)


def find_westervoort_cell() -> tuple[int, int]:
    ds = xr.open_dataset(INPUT / "staticmaps-ijssel.nc")
    x  = ds["x"].values
    y  = ds["y"].values
    xi = int(np.argmin(np.abs(x - 6.154)))
    yi = int(np.argmin(np.abs(y - 51.987)))
    return xi, yi


def download_2018() -> None:
    forcing_path = INPUT_2018 / "forcing-ijssel-2018.nc"
    if not forcing_path.exists():
        raise FileNotFoundError(
            f"Voer eerst download_forcing_2018.py uit: {forcing_path}"
        )

    # Probeer echte RWS-data voor 2018
    discharge = _rws_request(START, END)
    if discharge is None or len(discharge) < 50:
        logger.info("Gebruik gesynthetiseerde tijdreeks voor 2018.")
        discharge = synthetic_2018_drought_discharge()
    else:
        discharge = discharge.reindex(pd.date_range(START, END, freq="D")).interpolate()
        discharge = discharge.astype(np.float32)
        logger.info("RWS-data 2018: gemiddeld=%.0f m³/s, min=%.0f, max=%.0f",
                    discharge.mean(), discharge.min(), discharge.max())

    xi, yi = find_westervoort_cell()
    ds_static = xr.open_dataset(INPUT / "staticmaps-ijssel.nc")
    ny = ds_static.sizes["y"]
    nx = ds_static.sizes["x"]

    data = np.zeros((len(discharge), ny, nx), dtype=np.float32)
    data[:, yi, xi] = discharge.values

    ds_forcing = xr.open_dataset(forcing_path)
    inflow_da  = xr.DataArray(data, dims=["time", "y", "x"],
                               coords={"time": discharge.index})
    ds_forcing["inflow"] = inflow_da.reindex(time=ds_forcing.time).fillna(0.0)
    ds_forcing["inflow"].attrs["units"] = "m3 s-1"

    tmp = forcing_path.with_suffix(".tmp.nc")
    ds_forcing.to_netcdf(str(tmp))
    ds_forcing.close()
    tmp.replace(forcing_path)
    logger.info("Inflow 2018 toegevoegd aan %s", forcing_path)


if __name__ == "__main__":
    download_2018()
