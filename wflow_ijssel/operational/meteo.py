"""Meteo-forcing voor de operationele nowcast: Open-Meteo → modelgrid.

De historische forcing komt uit ERA5-Land via CDS (`download_forcing.py`), met
~5 dagen latentie en zonder verwachting — operationeel onbruikbaar. Hier halen
we Open-Meteo op een grover puntenraster op en interpoleren naar het modelgrid.

Geverifieerd op 2026-09-08: 99 punten in één call geeft HTTP 200 (~86 KB). Bij
meerdere punten is de respons een LIJST van objecten, bij één punt een enkel
object.
"""
from __future__ import annotations

import logging

import numpy as np
import requests

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

DAILY_VARS = "precipitation_sum,et0_fao_evapotranspiration,temperature_2m_mean"

# Tolerantie voor de respons-volgorde-toets in _check_response_order, in graden.
# Moet ruim ONDER de halve bevragingsstap van grid_points() (standaard 0,25°,
# dus halve stap 0,125°) blijven — anders wordt een verwisseling met het
# dichtstbijzijnde buurpunt nooit opgemerkt (die ligt namelijk maar 0,25° weg).
# Verander je de stap van grid_points(), controleer dan of deze constante nog
# steeds kleiner is dan de helft daarvan. 0,1° is ruim genoeg voor Open-Meteo's
# snap-naar-roosterpunt-afwijking (in de praktijk << 0,1°, zie de rooktest).
RESPONS_TOLERANTIE_GRADEN = 0.1

# Modelgrid van staticmaps-ijssel.nc / forcing-ijssel.nc — exact overnemen.
# LET OP: y loopt AFLOPEND (noord → zuid). Een oplopende as spiegelt het
# stroomgebied zonder dat wflow klaagt.
MODEL_X = np.linspace(5.004166666666666, 7.495833333333334, 300)
MODEL_Y = np.linspace(53.49583333333333, 51.50416666666667, 240)


def grid_points(step: float = 0.25) -> tuple[list[float], list[float]]:
    """Bevragingsraster dat het modelgrid ruim omsluit (geen extrapolatie)."""
    lats = np.arange(np.floor(MODEL_Y.min() / step) * step,
                     np.ceil(MODEL_Y.max() / step) * step + step / 2, step)
    lons = np.arange(np.floor(MODEL_X.min() / step) * step,
                     np.ceil(MODEL_X.max() / step) * step + step / 2, step)
    out_lat, out_lon = [], []
    for la in lats:
        for lo in lons:
            out_lat.append(round(float(la), 4))
            out_lon.append(round(float(lo), 4))
    return out_lat, out_lon


def _get_json(url: str, params: dict):
    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def _as_list(payload) -> list:
    return payload if isinstance(payload, list) else [payload]


def _check_response_order(payload: list, lats, lons,
                           tol: float = RESPONS_TOLERANTIE_GRADEN) -> None:
    """Toets dat de respons dezelfde volgorde heeft als de opgevraagde punten.

    Open-Meteo snapt elk punt naar zijn eigen roosterpunt, dus de teruggegeven
    `latitude`/`longitude` wijken licht af van wat is opgevraagd — vandaar een
    tolerantie. Die moet wel ruim onder de halve bevragingsstap blijven (zie
    RESPONS_TOLERANTIE_GRADEN hierboven), anders detecteert deze toets een
    verwisseling met het dichtstbijzijnde buurpunt niet. De afstand wordt
    Euclidisch getoetst (niet lat/lon los met een `of`), anders glipt een
    diagonale buur — die op elke as afzonderlijk binnen tolerantie valt — erdoor.
    Wijkt een punt verder af, dan is de volgorde vermoedelijk veranderd en zou
    de koppeling tussen punt en waarde stil verkeerd lopen.
    """
    for i, (loc, la, lo) in enumerate(zip(payload, lats, lons)):
        rla, rlo = loc.get("latitude"), loc.get("longitude")
        if rla is None or rlo is None:
            continue
        afstand = ((float(rla) - float(la)) ** 2 + (float(rlo) - float(lo)) ** 2) ** 0.5
        if afstand > tol:
            raise ValueError(
                f"respons op index {i} komt niet overeen met het opgevraagde punt "
                f"(opgevraagd {la:.4f},{lo:.4f}; gekregen {rla:.4f},{rlo:.4f}; "
                f"afstand {afstand:.4f}° > tolerantie {tol}°) — "
                "volgorde van de respons wijkt af van de opgevraagde punten")


def fetch_daily(lats, lons, start: str, end: str, archive: bool = False) -> dict:
    """Daggegevens per punt. Retourneert arrays met vorm (n_punten, n_dagen)."""
    url = ARCHIVE_URL if archive else FORECAST_URL
    params = {
        "latitude": ",".join(f"{v:.4f}" for v in lats),
        "longitude": ",".join(f"{v:.4f}" for v in lons),
        "daily": DAILY_VARS,
        "timezone": "Europe/Amsterdam",
        "start_date": start,
        "end_date": end,
    }
    payload = _as_list(_get_json(url, params))
    _check_response_order(payload, lats, lons)

    dates = payload[0]["daily"]["time"]
    n_pts, n_days = len(payload), len(dates)

    def column(key):
        arr = np.zeros((n_pts, n_days), dtype=float)
        for i, loc in enumerate(payload):
            vals = loc["daily"][key]
            arr[i, :] = [0.0 if v is None else float(v) for v in vals]
        return arr

    return {
        "dates": dates,
        "precip": column("precipitation_sum"),
        "pet": column("et0_fao_evapotranspiration"),
        "temp": column("temperature_2m_mean"),
    }


def to_model_grid(values, src_lats, src_lons, dst_y, dst_x) -> np.ndarray:
    """Bilineaire interpolatie van een puntenwolk naar het modelgrid.

    `values` heeft vorm (n_punten, n_dagen); de punten liggen op een regelmatig
    lat/lon-raster, rijgewijs geordend zoals `grid_points` ze oplevert.
    Resultaat: (n_dagen, len(dst_y), len(dst_x)).
    """
    values = np.asarray(values, dtype=float)
    if values.ndim != 2 or values.shape[0] != len(src_lats):
        raise ValueError(
            f"values moet vorm (n_punten, n_dagen) hebben met n_punten={len(src_lats)}, "
            f"kreeg {values.shape}")

    lat_arr = np.asarray(src_lats, dtype=float)
    lon_arr = np.asarray(src_lons, dtype=float)
    ulat = np.unique(lat_arr)
    ulon = np.unique(lon_arr)

    # De aantallen-check (len(ulat)*len(ulon) == len(src_lats)) is nodig maar
    # niet genoeg: een dubbele coördinaat plus een ontbrekende cel geeft
    # hetzelfde aantal punten terwijl het raster toch onvolledig is. Toets
    # daarom op de complete verzameling (lat, lon)-paren — dat vangt zowel
    # duplicaten als gaten.
    pairs = set(zip(lat_arr.tolist(), lon_arr.tolist()))
    expected_pairs = {(la, lo) for la in ulat.tolist() for lo in ulon.tolist()}
    if len(pairs) != len(lat_arr) or pairs != expected_pairs:
        raise ValueError(
            "bronpunten vormen geen regelmatig lat/lon-raster "
            "(dubbele en/of ontbrekende coördinaten)")

    n_days = values.shape[1]
    out = np.empty((n_days, len(dst_y), len(dst_x)), dtype=float)

    # index van elk bronpunt in het (lat, lon)-raster
    lat_idx = np.searchsorted(ulat, lat_arr)
    lon_idx = np.searchsorted(ulon, lon_arr)

    for d in range(n_days):
        # np.nan i.p.v. np.empty: een cel die door een fout in de check heen
        # glipt en dus nooit gevuld wordt, faalt zo luid (NaN in de output)
        # in plaats van stil ongeïnitialiseerd geheugen door te geven.
        field = np.full((len(ulat), len(ulon)), np.nan, dtype=float)
        field[lat_idx, lon_idx] = values[:, d]
        # interpoleer eerst over lengtegraad, dan over breedtegraad
        tmp = np.empty((len(ulat), len(dst_x)), dtype=float)
        for i in range(len(ulat)):
            tmp[i, :] = np.interp(dst_x, ulon, field[i, :])
        for j in range(len(dst_x)):
            out[d, :, j] = np.interp(dst_y, ulat, tmp[:, j])
    return out
