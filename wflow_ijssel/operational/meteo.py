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

# Het archief loopt enkele dagen achter op vandaag. Gemeten 2026-09-08 had D−3
# al data; 7 dagen is daarmee een ruime, veilige marge. Alles vanaf
# D−ARCHIEF_MARGE_DAGEN+1 komt van de forecast-API, die ~92 dagen terugreikt.
ARCHIEF_MARGE_DAGEN = 7

# Tolerantie voor de respons-volgorde-toets in _check_response_order, in graden.
# Moet ruim ONDER de halve bevragingsstap van grid_points() (standaard 0,25°,
# dus halve stap 0,125°) blijven — anders wordt een verwisseling met het
# dichtstbijzijnde buurpunt nooit opgemerkt (die ligt namelijk maar 0,25° weg).
# Verander je de stap van grid_points(), controleer dan of deze constante nog
# steeds kleiner is dan de helft daarvan. 0,1° is ruim genoeg voor Open-Meteo's
# snap-naar-roosterpunt-afwijking (in de praktijk << 0,1°, zie de rooktest).
RESPONS_TOLERANTIE_GRADEN = 0.1

# Het archief snapt naar een grover rooster dan de forecast-API: gemeten
# 2026-09-08 tot 0,131° afwijking, tegen 0,041° bij de forecast. Dat is méér dan
# de halve bevragingsstap (0,125°), dus afstand alleen kan daar een buurpunt niet
# uitsluiten — de bijectie-eis in _match_response_order doet dat wel.
ARCHIEF_TOLERANTIE_GRADEN = 0.3

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


def _match_response_order(payload: list, lats, lons,
                          tol: float = RESPONS_TOLERANTIE_GRADEN) -> list:
    """Koppel elk respons-object aan het opgevraagde punt dat erbij hoort.

    We nemen de volgorde van de respons niet aan maar leiden hem af uit de
    `latitude`/`longitude` die Open-Meteo per object meestuurt. Dat is robuuster
    dan een volgordetoets: raakt de volgorde verstoord, dan herstellen we hem in
    plaats van alleen te klagen.

    Waarom niet gewoon op afstand toetsen: de API snapt elk punt naar zijn eigen
    roosterpunt, en dat rooster verschilt per bron. Gemeten 2026-09-08 wijkt de
    forecast-API hooguit 0,041° af, maar het archief tot 0,131° — méér dan de
    halve bevragingsstap van 0,125°. Een pure afstandstoets kan daar "gesnapt
    naar eigen roosterpunt" niet onderscheiden van "verwisseld met de buur".
    De koppeling moet daarom een *bijectie* zijn: elk opgevraagd punt krijgt
    precies één respons. Dat sluit een verwisseling uit, ongeacht de snap.

    De koppeling gaat van opgevraagd punt náár respons, niet andersom. Dat is
    bewust: het archiefrooster is grover dan ons bevragingsraster van 0,25°, dus
    meerdere opgevraagde punten kunnen op dezelfde archiefcel uitkomen. Die cel
    mag dan door beide gebruikt worden — dat is geen fout maar de resolutie van
    de bron. Andersom koppelen (respons → punt) zou daar ten onrechte op
    "geen bijectie" stuklopen.

    Retourneert de respons, geordend als de opgevraagde punten. Gooit een
    ValueError als een opgevraagd punt verder dan `tol` van élk respons-object
    ligt — dan is er echt iets mis, en dat moet luid falen.
    """
    if len(payload) != len(lats):
        raise ValueError(
            f"respons bevat {len(payload)} locaties, er zijn er {len(lats)} opgevraagd")

    coords = []
    for i, loc in enumerate(payload):
        rla, rlo = loc.get("latitude"), loc.get("longitude")
        # Zonder coördinaten kunnen we niet koppelen; dan rest de aangenomen volgorde.
        coords.append(None if rla is None or rlo is None else (float(rla), float(rlo)))
    if all(c is None for c in coords):
        return payload

    geordend = []
    for j, (la, lo) in enumerate(zip(lats, lons)):
        beste_i, beste_d = None, None
        for i, c in enumerate(coords):
            if c is None:
                continue
            d = ((c[0] - float(la)) ** 2 + (c[1] - float(lo)) ** 2) ** 0.5
            if beste_d is None or d < beste_d:
                beste_i, beste_d = i, d
        if beste_d is None or beste_d > tol:
            raise ValueError(
                f"opgevraagd punt {j} ({float(la):.4f},{float(lo):.4f}) ligt "
                f"{beste_d:.4f}° van het dichtstbijzijnde respons-object — verder dan "
                f"de tolerantie {tol}°; de koppeling tussen punten en waarden zou "
                "stil verkeerd lopen")
        geordend.append(payload[beste_i])
    return geordend


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
    # Het archief snapt grover dan de forecast-API (0,131° vs 0,041°, gemeten
    # 2026-09-08), dus daar is een ruimere tolerantie nodig. De bijectie-eis in
    # _match_response_order blijft een verwisseling uitsluiten.
    tol = ARCHIEF_TOLERANTIE_GRADEN if archive else RESPONS_TOLERANTIE_GRADEN
    payload = _match_response_order(payload, lats, lons, tol)

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


def fetch_daily_window(lats, lons, start: str, end: str, today=None) -> dict:
    """Haal een venster op dat het archief én de forecast-API kan overspannen.

    Waarom dit nodig is: de forecast-API reikt ongeveer 92 dagen terug (gemeten
    2026-09-08: niet verder dan D−92), en het archief loopt enkele dagen achter.
    Een spin-up over een jaar past dus in geen van beide alleen. Deze functie
    splitst het venster op `ARCHIEF_MARGE_DAGEN` en naait de twee helften aan
    elkaar.

    De aanroeper controleert de aansluiting alsnog streng (zie
    `forcing._check_dagreeks_sluit_aan`), dus een naadfout valt luid door de mand
    in plaats van stil een dag te verschuiven.
    """
    from datetime import date as _date, timedelta as _timedelta

    today = today or _date.today()
    archief_eind = today - _timedelta(days=ARCHIEF_MARGE_DAGEN)
    s, e = _date.fromisoformat(start), _date.fromisoformat(end)
    if s > e:
        raise ValueError(f"start {start} ligt na end {end}")

    delen = []
    if s <= archief_eind:
        delen.append(fetch_daily(lats, lons, s.isoformat(),
                                 min(e, archief_eind).isoformat(), archive=True))
    if e > archief_eind:
        f_start = max(s, archief_eind + _timedelta(days=1))
        delen.append(fetch_daily(lats, lons, f_start.isoformat(), e.isoformat()))

    if len(delen) == 1:
        return delen[0]

    logger.info("venster %s..%s uit %d bronnen genaaid (archief t/m %s)",
                start, end, len(delen), archief_eind.isoformat())
    return {
        "dates": delen[0]["dates"] + delen[1]["dates"],
        "precip": np.concatenate([d["precip"] for d in delen], axis=1),
        "pet": np.concatenate([d["pet"] for d in delen], axis=1),
        "temp": np.concatenate([d["temp"] for d in delen], axis=1),
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
