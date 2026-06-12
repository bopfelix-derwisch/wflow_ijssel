"""v2 — grondwaterstand-voorspelling via een lineair reservoir (recharge-gedreven).

Klassiek transfer-functie-ruis / single-reservoir model (Pastas-stijl):

    GW(t) = base + k · Σ_i recharge(t-i) · exp(-i/τ)

met recharge = neerslag − referentieverdamping (Open-Meteo: precip − ET0). Per put
gekalibreerd op de volledige BRO-historie (grid over τ + lineaire regressie voor
k/base). Pijplijn: nowcast (laatste meting → vandaag) + forecast (+14 d), met
bias-correctie op de laatste echte meting en een onzekerheidsband uit het residu.

Lost de BRO-meetlatentie op: de maanden tussen laatste meting en vandaag worden
gereconstrueerd uit gemeten neerslag/verdamping i.p.v. genegeerd. Zie
docs/grondwater_voorspelling_voorstel.md.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import numpy as np
import requests

from dashboard import bro_gld

logger = logging.getLogger(__name__)

ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

CALIB_YEARS = 8
RIVER_YEARS = 4             # v2b: river-term kalibratievenster (RWS-fetch-kosten)
WARMUP_DAYS = 1095          # ~3·τ_max convolutie-aanloop
TAU_GRID    = [10, 20, 30, 45, 60, 90, 120, 180, 250, 365]  # dagen
_cache: dict = {}
_river_cache: dict = {}
_TTL = 6 * 3600             # 6 uur


def _river_series(years: int = RIVER_YEARS) -> dict:
    """v2b — Kampen waterstand (WATHTE, m+NAP) daggemiddeld over ~years jaar; gedeelde
    river-driver. Lege dict bij uitval → het model valt terug op recharge-only (v2)."""
    hit = _river_cache.get(years)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    out: dict = {}
    try:
        import pandas as pd
        import rws_waterinfo as rw
        end = date.today()
        start = end - timedelta(days=365 * years)
        df = rw.get_data([{"locatie_code": "kampen.ijssel", "compartiment_code": "OW",
                           "grootheid_code": "WATHTE", "eenheid_code": "cm",
                           "start_date": str(start), "end_date": str(end),
                           "proces_type": "meting"}], return_df=True, parallel=False)
        if df is not None and len(df):
            df2 = df[["Tijdstip", "Meetwaarde.Waarde_Numeriek"]].copy()
            df2["Tijdstip"] = pd.to_datetime(df2["Tijdstip"].str[:19])
            daily = df2.set_index("Tijdstip")["Meetwaarde.Waarde_Numeriek"].resample("D").mean().dropna()
            out = {ts.strftime("%Y-%m-%d"): float(v) / 100.0 for ts, v in daily.items()}  # cm → m
    except Exception as e:
        logger.warning("v2b river-fetch faalde: %s", e)
    _river_cache[years] = (time.monotonic(), out)
    return out


def _daterange(start: str, end: str) -> list[str]:
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def _recharge_series(lat: float, lon: float, start: str, horizon: int) -> dict:
    """date → recharge (mm/dag, = precip − ET0) over [start, vandaag+horizon].
    Archief voor de historie, forecast-API voor recent + de komende dagen."""
    today = date.today()
    out: dict = {}
    arch_end = today - timedelta(days=6)
    if date.fromisoformat(start) <= arch_end:
        r = requests.get(ARCHIVE_URL, params={
            "latitude": lat, "longitude": lon,
            "start_date": start, "end_date": arch_end.isoformat(),
            "daily": "precipitation_sum,et0_fao_evapotranspiration",
            "timezone": "Europe/Amsterdam"}, timeout=60)
        r.raise_for_status()
        d = r.json().get("daily", {})
        for dt, p, e in zip(d.get("time", []), d.get("precipitation_sum", []),
                            d.get("et0_fao_evapotranspiration", [])):
            out[dt] = (p or 0.0) - (e or 0.0)
    r2 = requests.get(FORECAST_URL, params={
        "latitude": lat, "longitude": lon,
        "daily": "precipitation_sum,et0_fao_evapotranspiration",
        "past_days": 16, "forecast_days": horizon, "timezone": "Europe/Amsterdam"}, timeout=30)
    r2.raise_for_status()
    d2 = r2.json().get("daily", {})
    for dt, p, e in zip(d2.get("time", []), d2.get("precipitation_sum", []),
                        d2.get("et0_fao_evapotranspiration", [])):
        out[dt] = (p or 0.0) - (e or 0.0)   # forecast overschrijft recent archief
    return out


def _convolve(dates: list[str], rech: dict, tau: float) -> np.ndarray:
    """S[t] = Σ_i recharge[t-i]·exp(-i/τ), recursief: S[t] = a·S[t-1] + R[t]."""
    a = np.exp(-1.0 / tau)
    S = np.zeros(len(dates))
    prev = 0.0
    for i, dt in enumerate(dates):
        prev = a * prev + rech.get(dt, 0.0)
        S[i] = prev
    return S


def predict_well(bro_id: str, lat: float, lon: float, horizon: int = 14) -> dict:
    """Kalibreer + voorspel de absolute grondwaterstand voor één put."""
    key = f"res_{bro_id}_{horizon}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]

    gw = bro_gld.fetch_series(bro_id)
    if len(gw) < 100:
        return {"available": False, "error": "te weinig BRO-metingen"}

    today = date.today()
    # v2b: river-term meenemen als RWS-data beschikbaar is; venster dan tot RIVER_YEARS.
    river = _river_series()
    use_river = len(river) > 200
    calib_years = RIVER_YEARS if use_river else CALIB_YEARS
    cstart = max(gw[0]["date"], (today - timedelta(days=365 * calib_years)).isoformat())
    if use_river:
        cstart = max(cstart, min(river))
    gw = [e for e in gw if e["date"] >= cstart]
    if len(gw) < 50:
        return {"available": False, "error": "te weinig metingen in kalibratievenster"}
    gw_map = {e["date"]: e["value"] for e in gw}

    warmup_start = (date.fromisoformat(gw[0]["date"]) - timedelta(days=WARMUP_DAYS)).isoformat()
    end_future = (today + timedelta(days=horizon)).isoformat()
    try:
        rech = _recharge_series(lat, lon, warmup_start, horizon)
    except Exception as e:
        logger.warning("reservoir recharge-fetch faalde voor %s: %s", bro_id, e)
        return {"available": False, "error": f"neerslagdata niet beschikbaar: {e}"}

    all_dates = _daterange(warmup_start, end_future)
    idx = {d: i for i, d in enumerate(all_dates)}
    obs_dates = [d for d in gw_map if d in idx]
    ys = np.array([gw_map[d] for d in obs_dates])

    # rivier-driver over alle datums: backfill vóór eerste meting, flat-hold ná laatste
    rivmap = None
    if use_river:
        rk = sorted(river)
        r_first, r_last = river[rk[0]], river[rk[-1]]
        rivmap = {d: river.get(d, r_first if d < rk[0] else r_last) for d in all_dates}

    def _nse(pred):
        ss_res = float(np.sum((ys - pred) ** 2))
        ss_tot = float(np.sum((ys - ys.mean()) ** 2))
        return 1 - ss_res / ss_tot if ss_tot > 0 else -999.0

    best = None
    for tau_r in TAU_GRID:
        Sr = _convolve(all_dates, rech, tau_r)
        xr = np.array([Sr[idx[d]] for d in obs_dates])
        tauq_list = TAU_GRID if use_river else [None]
        for tau_q in tauq_list:
            if tau_q is None:
                Sq = None
                A = np.vstack([xr, np.ones_like(xr)]).T
            else:
                Sq = _convolve(all_dates, rivmap, tau_q)
                xq = np.array([Sq[idx[d]] for d in obs_dates])
                A = np.vstack([xr, xq, np.ones_like(xr)]).T
            coef = np.linalg.lstsq(A, ys, rcond=None)[0]
            nse = _nse(A @ coef)
            if best is None or nse > best["nse"]:
                best = {"tau_r": tau_r, "tau_q": tau_q, "coef": coef, "nse": round(nse, 3),
                        "resid_std": float(np.std(ys - A @ coef)), "Sr": Sr, "Sq": Sq}

    if best["tau_q"] is None:
        model = best["coef"][0] * best["Sr"] + best["coef"][1]
    else:
        model = best["coef"][0] * best["Sr"] + best["coef"][1] * best["Sq"] + best["coef"][2]
    mmap = {d: model[idx[d]] for d in all_dates}
    last_date = max(gw_map)
    last_value = gw_map[last_date]
    bias = last_value - mmap.get(last_date, last_value)   # anker op laatste echte meting

    out_dates = [d for d in all_dates if last_date <= d <= end_future]
    gw_pred = [round(mmap[d] + bias, 3) for d in out_dates]
    band = round(1.96 * best["resid_std"], 3)
    today_iso = today.isoformat()

    def at(d):
        return next((gw_pred[i] for i, x in enumerate(out_dates) if x == d), None)

    result = {
        "available": True,
        "bro_id": bro_id, "lat": lat, "lon": lon,
        "last_date": last_date, "last_value": last_value,
        "tau_days": best["tau_r"], "tau_river_days": best["tau_q"],
        "model": "recharge+river" if best["tau_q"] else "recharge",
        "nse": best["nse"], "band_m": band,
        "dates": out_dates, "gw": gw_pred,
        "lower": [round(v - band, 3) for v in gw_pred],
        "upper": [round(v + band, 3) for v in gw_pred],
        "nowcast_today": at(today_iso),
        "forecast_horizon": gw_pred[-1] if gw_pred else None,
        "horizon_date": end_future,
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    _cache[key] = (time.monotonic(), result)
    return result


# Representatieve, datadichte putten langs de Veluwe-oostflank (zuid → noord).
RESERVOIR_WELLS = [
    ("GLD000000008239", 52.3050, 5.9834),
    ("GLD000000008262", 52.3797, 6.0570),
    ("GLD000000053138", 52.5444, 6.0242),
]


def predict_set(horizon: int = 14) -> dict:
    """Voorspel een set representatieve putten, gesorteerd op fit-kwaliteit (NSE)."""
    out = []
    for bid, lat, lon in RESERVOIR_WELLS:
        try:
            r = predict_well(bid, lat, lon, horizon)
            if r.get("available"):
                out.append(r)
        except Exception as e:
            logger.warning("reservoir %s faalde: %s", bid, e)
    out.sort(key=lambda w: w["nse"], reverse=True)
    return {"available": bool(out), "wells": out,
            "generated_at": time.strftime("%Y-%m-%d %H:%M")}
