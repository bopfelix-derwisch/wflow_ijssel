"""Dagdebieten Westervoort voor mei–aug 2021 via RWS Waterinfo API.

Uitvoer: data/input_2021/forcing-ijssel-2021.nc (inflow toegevoegd)

De juli-2021 Rijnvloed: piek Lobith ~8 900 m³/s op 15 juli 2021.
IJssel-aandeel bij hoog water ~25 % → ~2 200 m³/s bij Westervoort.
Bron: Rijkswaterstaat waterstandsberichten juli 2021.

Probeert eerst de Waterinfo REST API; als die faalt wordt een
gesynthetiseerde tijdreeks gebruikt.
"""
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT       = Path(__file__).parent
INPUT_2021 = ROOT / "data" / "input_2021"
INPUT      = ROOT / "data" / "input"

START = pd.Timestamp("2021-05-01")
END   = pd.Timestamp("2021-08-31")


# ── RWS Waterinfo API ──────────────────────────────────────────────────────────

RWS_URL = "https://waterwebservices.rijkswaterstaat.nl/ONLINEWAARNEMINGENSERVICES_DBO/OphalenWaarnemingen"

def _rws_request(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series | None:
    """Haal daggemiddeld debiet op bij Westervoort via de RWS Waterinfo API."""
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
            dt_str = r["Tijdstip"]                     # "2021-05-01T00:00:00.000+01:00"
            val    = r["Meetwaarde"]["Waarde_Numeriek"]
            rows.append({"time": pd.Timestamp(dt_str[:19]), "Q": float(val)})
        df = pd.DataFrame(rows).set_index("time").sort_index()
        # daggemiddelde
        daily = df["Q"].resample("D").mean()
        logger.info("RWS API: %d dagwaarden opgehaald", len(daily))
        return daily
    except Exception as e:
        logger.warning("RWS API mislukt: %s", e)
        return None


def synthetic_2021_discharge() -> pd.Series:
    """Gesynthetiseerde dagdebieten IJssel bij Westervoort, mei–aug 2021.

    Gebaseerd op de Rijn-hoogwatergolf juli 2021:
    - Piek Lobith: ~8 900 m³/s op 15 juli 2021
    - IJssel-aandeel ~25 % → piek ~2 200 m³/s bij Westervoort
    - Zomer-basisafvoer: ~200–350 m³/s
    """
    idx = pd.date_range(START, END, freq="D")
    t   = np.arange(len(idx), dtype=float)

    baseflow = 250.0 + 50.0 * np.sin(np.pi * t / len(t))   # zachte zomercurve

    # Twee pulsen: kleine juni-regen + grote juli-vloed
    def pulse(peak_day, sigma, height):
        raw = np.exp(-0.5 * ((t - peak_day) / sigma) ** 2)
        # steilere stijging
        sr = sigma * 0.7
        asym = np.where(t < peak_day,
                        np.exp(-0.5 * ((t - peak_day) / sr) ** 2), raw)
        return height * asym

    t_juli15 = float((pd.Timestamp("2021-07-15") - START).days)
    t_juni20 = float((pd.Timestamp("2021-06-20") - START).days)
    base_at_peak = 250.0 + 50.0 * np.sin(np.pi * t_juli15 / len(t))

    Q = baseflow + pulse(t_juni20, 6.0, 400.0) + pulse(t_juli15, 8.0, 2200.0 - base_at_peak)
    return pd.Series(Q.clip(min=150.0).astype(np.float32), index=idx)


def find_westervoort_cell() -> tuple[int, int]:
    ds = xr.open_dataset(INPUT / "staticmaps-ijssel.nc")
    x  = ds["x"].values
    y  = ds["y"].values
    xi = int(np.argmin(np.abs(x - 6.154)))
    yi = int(np.argmin(np.abs(y - 51.987)))
    return xi, yi


def download_2021() -> None:
    forcing_path = INPUT_2021 / "forcing-ijssel-2021.nc"
    assert forcing_path.exists(), f"Voer eerst download_forcing_2021.py uit: {forcing_path}"

    # Probeer echte RWS-data
    discharge = _rws_request(START, END)
    if discharge is None or len(discharge) < 50:
        logger.info("Gebruik gesynthetiseerde tijdreeks voor 2021.")
        discharge = synthetic_2021_discharge()
    else:
        discharge = discharge.reindex(pd.date_range(START, END, freq="D")).interpolate()
        discharge = discharge.astype(np.float32)

    logger.info("Debiet: %d dagen, piek=%.0f m3/s op %s",
                len(discharge), discharge.max(), discharge.idxmax().date())

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
    logger.info("Inflow toegevoegd aan %s", forcing_path)


if __name__ == "__main__":
    download_2021()
