"""Live IJssel-verwachting: RWS Waterinfo metingen + Open-Meteo neerslag + routeringsmodel.

Databronnen:
  - Westervoort Q (m³/s, 30 dagen) — rws_waterinfo, station 'westervoort'
  - Kampen waterpeil WATHTE (cm→m NAP, 30 dagen) — rws_waterinfo, station 'kampen.ijssel'
  - RWS officiële verwachting waterpeil Kampen (2–5 dagen) — procestype 'verwachting'
  - Neerslagneerslagneerslag IJssel-stroomgebied (30 d hist + 14 d forecast) — Open-Meteo
  - Statistisch debietmodel (14 dagen): recessie + neerslagimpulsrespons

Resultaat is indicatief — voor operationele beslissingen: zie waterinfo.rws.nl.
"""
import logging
import time

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

try:
    import rws_waterinfo as rw
    _RWS_OK = True
except ImportError:
    _RWS_OK = False
    logger.warning("rws_waterinfo niet geïnstalleerd — RWS-data niet beschikbaar")

OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"

DISCHARGE_THRESHOLD = 1500.0
CATCHMENT_KM2       = 12_500.0

_cache: dict = {}
CACHE_TTL = 900


def _cached() -> dict | None:
    if _cache.get("ts") and time.monotonic() - _cache["ts"] < CACHE_TTL:
        return _cache.get("data")
    return None


def _cache_set(data: dict) -> None:
    _cache["ts"]   = time.monotonic()
    _cache["data"] = data


# ── RWS Waterinfo ─────────────────────────────────────────────────────────────

def _rws_daily(locatie: str, grootheid: str, eenheid: str,
               start: "date", end: "date",
               proces_type: str = "meting") -> pd.Series | None:
    if not _RWS_OK:
        return None
    try:
        df = rw.get_data(
            [{
                "locatie_code":     locatie,
                "compartiment_code": "OW",
                "grootheid_code":   grootheid,
                "eenheid_code":     eenheid,
                "start_date":       str(start),
                "end_date":         str(end),
                "proces_type":      proces_type,
            }],
            return_df=True,
            parallel=False,
        )
        if df is None or len(df) == 0:
            return None
        df2 = df[["Tijdstip", "Meetwaarde.Waarde_Numeriek"]].copy()
        df2["Tijdstip"] = pd.to_datetime(df2["Tijdstip"].str[:19])
        df2 = df2.set_index("Tijdstip").sort_index()
        daily = df2["Meetwaarde.Waarde_Numeriek"].resample("D").mean()
        logger.info("RWS %s/%s/%s: %d dagwaarden", locatie, grootheid, proces_type, len(daily))
        return daily.astype(float)
    except Exception as e:
        logger.warning("RWS %s/%s: %s", locatie, grootheid, e)
        return None


# ── Open-Meteo neerslag ───────────────────────────────────────────────────────

def _openmeteo_precip(lat: float = 52.3, lon: float = 6.0,
                      past_days: int = 35) -> dict | None:
    try:
        resp = requests.get(
            OPENMETEO_URL,
            params={
                "latitude":      lat,
                "longitude":     lon,
                "daily":         "precipitation_sum",
                "past_days":     past_days,
                "forecast_days": 14,
                "timezone":      "Europe/Amsterdam",
            },
            timeout=20,
        )
        resp.raise_for_status()
        d      = resp.json().get("daily", {})
        dates  = d.get("time", [])
        precip = d.get("precipitation_sum", [])
        today  = pd.Timestamp.now().normalize()
        result = {"past": {"dates": [], "values": []}, "forecast": {"dates": [], "values": []}}
        for dt, p in zip(dates, precip):
            bucket = "forecast" if pd.Timestamp(dt) >= today else "past"
            result[bucket]["dates"].append(dt)
            result[bucket]["values"].append(round(float(p or 0.0), 1))
        return result
    except Exception as e:
        logger.warning("Open-Meteo: %s", e)
        return None


# ── Hydrologisch model ────────────────────────────────────────────────────────

def _route_to_kampen(q_west: np.ndarray) -> np.ndarray:
    """Lag-routing Westervoort → Kampen: 2 dagen vertraging, schaalfactor 0.85."""
    lag = 2
    q   = np.zeros_like(q_west, dtype=float)
    q[:lag] = q_west[:lag] * 0.85
    q[lag:] = q_west[:-lag] * 0.85
    return q


def _seasonal_mean(month: int) -> float:
    return {
        12: 600, 1: 650, 2: 580,
        3: 480, 4: 380, 5: 310,
        6: 270, 7: 240, 8: 240,
        9: 290, 10: 380, 11: 490,
    }.get(month, 350)


def _recession(q0: float, n: int, month: int, tau: float = 10.0) -> np.ndarray:
    q_mean = _seasonal_mean(month)
    t = np.arange(1, n + 1, dtype=float)
    return np.maximum(q_mean + (q0 - q_mean) * np.exp(-t / tau), 80.0)


def _precip_response(precip_all: np.ndarray, n_fcast: int) -> np.ndarray:
    """Neerslagimpulsrespons → debiets-bijdrage Kampen (m³/s)."""
    scale  = 0.25 * CATCHMENT_KM2 * 1e6 * 1e-3 / 86400  # ≈ 36 m³/s per mm/dag
    t_uh   = np.arange(15, dtype=float)
    diff   = np.maximum(t_uh - 2, 0.0)
    kernel = np.where(t_uh >= 2, diff ** 1.5 * np.exp(-diff / 2.5), 0.0)
    s = kernel.sum()
    if s > 0:
        kernel /= s

    resp = np.zeros(n_fcast)
    for d in range(n_fcast):
        for k, w in enumerate(kernel):
            src = len(precip_all) - n_fcast + d - k
            if 0 <= src < len(precip_all):
                resp[d] += precip_all[src] * w * scale
    return resp


# ── Hoofd-functie ─────────────────────────────────────────────────────────────

def build_forecast() -> dict:
    if (cached := _cached()) is not None:
        return cached

    from datetime import date as _date, timedelta
    today_dt  = _date.today()
    today_ts  = pd.Timestamp(today_dt)
    start_dt  = today_dt - timedelta(days=35)
    end_dt    = today_dt
    idx       = pd.date_range(start_dt, today_dt, freq="D")
    N_FCAST   = 14

    # ── 1. Westervoort Q (debiet) ─────────────────────────────────────────────
    q_west_raw = _rws_daily("westervoort", "Q", "m3/s", start_dt, end_dt)
    data_ok    = q_west_raw is not None and len(q_west_raw) >= 5

    if data_ok:
        q_west = q_west_raw.reindex(idx).interpolate(limit=5).bfill().fillna(400.0)
    else:
        seasonal = _seasonal_mean(today_dt.month)
        q_west   = pd.Series(float(seasonal), index=idx)

    q_kampen_hist = _route_to_kampen(q_west.values)

    # ── 2. Kampen waterpeil (WATHTE in cm → m+NAP) ───────────────────────────
    h_kampen_raw = _rws_daily("kampen.ijssel", "WATHTE", "cm", start_dt, end_dt)
    if h_kampen_raw is not None and len(h_kampen_raw) >= 3:
        h_kampen_m = (h_kampen_raw / 100.0).reindex(idx).interpolate(limit=5).bfill()
    else:
        h_kampen_m = pd.Series(float("nan"), index=idx)

    # ── 3. RWS officiële waterpeil-verwachting (2–5 dagen) ───────────────────
    fcast_end_dt = today_dt + timedelta(days=14)
    h_rws_fcast_raw = _rws_daily(
        "kampen.ijssel", "WATHTE", "cm",
        today_dt, fcast_end_dt,
        proces_type="verwachting",
    )
    h_rws_fcast: dict = {"dates": [], "values_m": []}
    if h_rws_fcast_raw is not None and len(h_rws_fcast_raw) >= 1:
        for ts, v in h_rws_fcast_raw.items():
            if not pd.isna(v):
                h_rws_fcast["dates"].append(ts.strftime("%Y-%m-%d"))
                h_rws_fcast["values_m"].append(round(float(v) / 100.0, 3))

    # ── 4. Open-Meteo neerslag ────────────────────────────────────────────────
    precip = _openmeteo_precip()
    precip_past_d  = precip["past"]["dates"]     if precip else []
    precip_past_v  = precip["past"]["values"]    if precip else []
    precip_fcast_d = precip["forecast"]["dates"]  if precip else []
    precip_fcast_v = precip["forecast"]["values"] if precip else []

    # ── 5. Statistisch debietmodel (14 d) ─────────────────────────────────────
    q0           = float(q_west.iloc[-1])
    q_west_fcast = _recession(q0, N_FCAST, today_dt.month)
    all_precip   = np.array(precip_past_v + precip_fcast_v, dtype=float)
    precip_resp  = _precip_response(all_precip, N_FCAST)

    q_ext  = np.concatenate([q_kampen_hist, _route_to_kampen(q_west_fcast)])
    q_mid  = q_ext[-N_FCAST:] + precip_resp
    unc    = 0.18 + 0.04 * np.arange(1, N_FCAST + 1, dtype=float)
    q_low  = np.maximum(q_mid * (1 - unc), 50.0)
    q_high = q_mid * (1 + unc)

    fcast_dates = [
        (today_ts + pd.Timedelta(days=i + 1)).strftime("%Y-%m-%d")
        for i in range(N_FCAST)
    ]

    # ── KPI's & alarmering ───────────────────────────────────────────────────
    q_now     = float(q_kampen_hist[-1])
    h_now     = float(h_kampen_m.iloc[-1]) if not h_kampen_m.isnull().all() else None
    peak_idx  = int(np.argmax(q_mid))
    peak_high = float(q_high.max())

    if peak_high >= DISCHARGE_THRESHOLD * 1.5:
        alert = "hoog"
    elif peak_high >= DISCHARGE_THRESHOLD:
        alert = "verhoogd"
    elif q_now > 800:
        alert = "waakzaam"
    else:
        alert = "normaal"

    result = {
        "generated_at":  today_dt.strftime("%Y-%m-%d"),
        "data_available": data_ok,
        "alert":          alert,
        "kpis": {
            "current_q_kampen":      round(q_now, 1),
            "current_q_westervoort": round(q0, 1),
            "current_h_kampen_m":    round(h_now, 2) if h_now is not None else None,
            "peak_forecast_q":       round(float(q_mid[peak_idx]), 1),
            "peak_forecast_date":    fcast_dates[peak_idx],
            "days_above_threshold":  int(np.sum(q_mid > DISCHARGE_THRESHOLD)),
            "total_precip_14d":      round(sum(precip_fcast_v), 1),
        },
        "measured": {
            "dates":         [d.strftime("%Y-%m-%d") for d in idx],
            "q_westervoort": [round(float(v), 1) for v in q_west.values],
            "q_kampen":      [round(float(v), 1) for v in q_kampen_hist],
            "h_kampen_m":    [
                round(float(v), 3) if not pd.isna(v) else None
                for v in h_kampen_m.values
            ],
        },
        "rws_forecast": h_rws_fcast,
        "precip": {
            "past_dates":     precip_past_d,
            "past_values":    precip_past_v,
            "forecast_dates": precip_fcast_d,
            "forecast_values": precip_fcast_v,
        },
        "forecast": {
            "dates": fcast_dates,
            "q_mid":  [round(float(v), 1) for v in q_mid],
            "q_low":  [round(float(v), 1) for v in q_low],
            "q_high": [round(float(v), 1) for v in q_high],
        },
    }
    _cache_set(result)
    return result
