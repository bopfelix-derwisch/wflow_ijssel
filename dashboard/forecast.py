"""Live IJssel-verwachting: RWS Waterinfo metingen + Open-Meteo neerslag + routeringsmodel.

Databronnen:
  - Westervoort Q (m³/s, 30 dagen) — rws_waterinfo, station 'westervoort'
  - Kampen waterpeil WATHTE (cm→m NAP, 30 dagen) — rws_waterinfo, station 'kampen.ijssel'
  - RWS officiële verwachting waterpeil Kampen (2–5 dagen) — procestype 'verwachting'
  - Neerslagneerslagneerslag IJssel-stroomgebied (30 d hist + 14 d forecast) — Open-Meteo
  - Statistisch debietmodel (14 dagen): recessie + neerslagimpulsrespons

Resultaat is indicatief — voor operationele beslissingen: zie waterinfo.rws.nl.
"""
import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

from dashboard import rws_client

OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"

# Nachtelijke wflow-nowcast; geschreven door wflow_ijssel/operational/nowcast.py.
WFLOW_LATEST = (Path(__file__).resolve().parent.parent
                / "wflow_ijssel" / "data" / "forecast" / "latest.json")

# Ouder dan dit → de lijn vervalt en de tab valt terug op het statistische model.
MAX_AGE_DAYS = 2

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
    """Dunne alias op rws_client.daily_series.

    Blijft bestaan omdat assimilation.py en validation.py deze naam importeren.
    Alle fetch- en filterlogica zit in dashboard/rws_client.py.
    """
    return rws_client.daily_series(locatie, grootheid, eenheid, start, end, proces_type)


WESTERVOORT_FALLBACK = 400.0   # laatste redmiddel; zie fill_westervoort_gap


def _lobith_metingen(start, end) -> dict:
    """Lobith-dagafvoer als {datum: m³/s}. Leeg bij uitval."""
    s = rws_client.daily_series("lobith.bovenrijn.tolkamer", "Q", "m3/s", start, end)
    if s is None:
        return {}
    return {ts.strftime("%Y-%m-%d"): float(v) for ts, v in s.items()}


def _lobith_ratio(lobith: dict, westervoort: dict):
    """Verhouding Westervoort/Lobith; None bij te weinig overlap."""
    from wflow_ijssel.operational.boundary import lobith_ratio
    return lobith_ratio(lobith, westervoort)


def fill_westervoort_gap(q_west_raw, idx):
    """Vul het gat in de Westervoort-reeks, bij voorkeur uit Lobith.

    De RWS-reeks voor Westervoort loopt structureel ongeveer twee weken achter
    (gemeten 2026-09-09: 21 van 36 dagen, laatste 25 augustus), terwijl Lobith
    compleet en actueel is. Hier stond `fillna(WESTERVOORT_FALLBACK)`, waardoor
    het startpunt van het recessiemodel exact op die constante uitkwam in plaats
    van op data — en `data_available` toch op `true`. De verwachting daalde
    daardoor van 390 naar 317 m³/s waar hij had moeten stijgen van 134 naar 248.

    Retourneert (reeks zonder NaN, info-dict met `q0_bron` en `gat_dagen`).
    `q0_bron` is `meting`, `lobith` of `terugvalconstante` — die laatste is een
    noodgreep en hoort zichtbaar te zijn in het antwoord, niet stil.
    """
    heeft_meting = (q_west_raw is not None and len(q_west_raw))
    # `gat_dagen` telt de dagen zónder meting, niet de dagen die na interpolatie
    # nog leeg zijn: die eerste vijf zijn immers ook geen waarneming.
    gat = (len(idx) if not heeft_meting
           else int(len(idx) - q_west_raw.reindex(idx).notna().sum()))

    basis = (q_west_raw.reindex(idx).interpolate(limit=5).bfill()
             if heeft_meting else pd.Series(float("nan"), index=idx))
    if gat == 0:
        return basis, {"q0_bron": "meting", "gat_dagen": 0}
    if not basis.isna().any():
        # Kort gat, volledig overbrugd door interpolatie — geen Lobith nodig.
        return basis, {"q0_bron": "meting", "gat_dagen": gat}

    start, end = idx[0].date(), idx[-1].date()
    try:
        lobith = _lobith_metingen(start, end)
        gemeten = {ts.strftime("%Y-%m-%d"): float(v)
                   for ts, v in basis.dropna().items()}
        ratio = _lobith_ratio(lobith, gemeten) if lobith else None
    except Exception as e:                                   # pragma: no cover
        logger.warning("Lobith-terugval faalde: %s", e)
        lobith, ratio = {}, None

    if ratio:
        afgeleid = pd.Series(
            [lobith.get(d.strftime("%Y-%m-%d"), float("nan")) * ratio for d in idx],
            index=idx)
        gevuld = basis.fillna(afgeleid)
        if not gevuld.isna().any():
            logger.info("Westervoort-gat van %d dagen gevuld uit Lobith (ratio %.4f)",
                        gat, ratio)
            return gevuld, {"q0_bron": "lobith", "gat_dagen": gat,
                            "lobith_ratio": round(float(ratio), 4)}
        basis = gevuld

    logger.warning("Westervoort-gat van %d dagen: geen bruikbare Lobith-terugval, "
                   "val terug op de constante %.0f m³/s", gat, WESTERVOORT_FALLBACK)
    return basis.fillna(WESTERVOORT_FALLBACK), {
        "q0_bron": "terugvalconstante", "gat_dagen": gat}


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
        q_west, gap_info = fill_westervoort_gap(q_west_raw, idx)
    else:
        seasonal = _seasonal_mean(today_dt.month)
        q_west   = pd.Series(float(seasonal), index=idx)
        gap_info = {"q0_bron": "seizoensgemiddelde", "gat_dagen": len(idx)}

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
    wflow_blok = read_wflow_forecast()
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
        # Waar het startpunt van het recessiemodel vandaan komt. `terugvalconstante`
        # betekent dat de verwachting níét datagedreven is — dat hoort zichtbaar te
        # zijn, niet stil in de code te blijven zitten.
        "q0_source": gap_info,
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
        # Nachtelijke wflow SBM-nowcast, gelezen uit latest.json. Het statistische
        # model hierboven blijft staan: als vergelijkingsbasis én als terugval.
        "wflow": wflow_blok,
        # Toetspunt Olst: het enige punt op de IJssel waar RWS én meet én een
        # officiële debietverwachting publiceert.
        "olst": build_olst_comparison(wflow_blok, start_dt, end_dt, today_dt),
        # Peilverwachting Kampen: hybride, want wflow's eigen h is rivierdiepte
        # zonder opstuwing. Zie dashboard/stage.py.
        "stage": _build_stage(wflow_blok, today_dt),
    }
    _cache_set(result)
    return result


def _build_stage(wflow_blok: dict, today) -> dict:
    """Peilverwachting; faalt nooit hard — de tab moet zonder blijven werken."""
    try:
        from dashboard.stage import build_stage_forecast
        return build_stage_forecast(wflow_blok, today)
    except Exception as e:
        logger.warning("peilverwachting faalde: %s", e)
        return {"available": False,
                "method": "hybride — wflow-debiet + empirische afvoerrelatie",
                "note": f"Peilverwachting niet beschikbaar: {e}"}


def build_olst_comparison(d_wflow: dict, start, end, today) -> dict:
    """Toetspunt Olst: model tegen meting én officiële RWS-verwachting.

    Olst is het enige punt op de IJssel waar RWS zowel een debietmeting als een
    officiële debietverwachting publiceert. Bij Kampen is er alleen een
    waterstandsverwachting, en bij Westervoort niets. Dit is dus de enige plek
    waar de wflow-lijn eerlijk naast een officiële verwachting te leggen is.

    De RWS-verwachting reikt maar ~3 dagen; dat is geen tekortkoming van dit
    lab maar de horizon die RWS publiceert.

    NB dit is géén FEWS-koppeling. De FEWS PI REST in dit project (`fews_poc/`)
    is een emulatie die onze eigen data uitgeeft; hij haalt niets op. Deze
    cijfers komen rechtstreeks uit RWS Waterinfo.
    """
    from datetime import timedelta

    out = {"available": False, "station": "olst",
           "note": "Toetspunt Olst — RWS meet en voorspelt hier het debiet."}

    meting = _rws_daily("olst", "Q", "m3/s", start, end)
    verwacht = _rws_daily("olst", "Q", "m3/s", today, today + timedelta(days=14),
                          proces_type="verwachting")

    if meting is not None and len(meting):
        out["measured_dates"] = [ts.strftime("%Y-%m-%d") for ts in meting.index]
        out["measured_q"] = [round(float(v), 1) for v in meting.values]
    if verwacht is not None and len(verwacht):
        out["rws_dates"] = [ts.strftime("%Y-%m-%d") for ts in verwacht.index]
        out["rws_q"] = [round(float(v), 1) for v in verwacht.values]

    if d_wflow.get("available") and d_wflow.get("q_olst"):
        out["wflow_dates"] = d_wflow["dates"]
        out["wflow_q"] = [round(float(v), 1) for v in d_wflow["q_olst"]]

    out["available"] = bool(out.get("wflow_q") and
                            (out.get("measured_q") or out.get("rws_q")))

    # Vergelijk model en officiële verwachting op de dagen die ze delen.
    if out.get("wflow_q") and out.get("rws_q"):
        wmap = dict(zip(out["wflow_dates"], out["wflow_q"]))
        paren = [(d, wmap[d], q) for d, q in zip(out["rws_dates"], out["rws_q"])
                 if d in wmap]
        if paren:
            verschillen = [w - r for _, w, r in paren]
            out["overlap_dagen"] = len(paren)
            out["gem_verschil"] = round(sum(verschillen) / len(verschillen), 1)
            ref = sum(r for _, _, r in paren) / len(paren)
            out["gem_verschil_pct"] = round(100.0 * out["gem_verschil"] / ref, 0) if ref else None
    return out


def read_wflow_forecast(path=None, today=None) -> dict:
    """Lees de nachtelijke wflow-nowcast uit latest.json.

    Het dashboard rekent niets: het leest wat de nachtrun heeft weggeschreven.
    Iedere degradatie is zichtbaar via `status` — stil terugvallen zou hier het
    ergste zijn wat we konden doen, want dit lab gaat over navolgbaarheid.

    Statussen: `vers` (0-1 dagen oud), `verouderd` (2 dagen), `vervallen`
    (ouder), `ontbreekt`, `onleesbaar`, `leeg` (status "ok" maar een lege
    reeks), `mislukt`. Alleen bij `vers` en `verouderd` is `available` waar.

    Een mislukte nachtrun overschrijft de laatste goede reeks niet: `run_nightly`
    schrijft dan een `last_attempt`-veld bij in de bestaande `latest.json`. Die
    poging wordt hier altijd in de `note` verwerkt, ook als de getoonde reeks
    zelf nog `vers` of `verouderd` is — anders zou een mislukte nacht onzichtbaar
    blijven zolang de vorige goede reeks nog binnen de leeftijdsgrens valt.
    """
    from datetime import date as _date

    path = Path(path) if path is not None else WFLOW_LATEST
    today = today or _date.today()
    leeg = {"available": False, "age_days": None, "dates": [], "q_kampen": [],
            "q_westervoort": [], "gauge": None, "model": None}

    if not path.exists():
        return {**leeg, "status": "ontbreekt",
                "note": "Er is nog geen wflow-nowcast gedraaid; de verwachting toont "
                        "alleen het statistische model."}
    try:
        data = json.loads(path.read_text())
    except Exception as e:
        logger.warning("latest.json onleesbaar: %s", e)
        return {**leeg, "status": "onleesbaar",
                "note": "De wflow-nowcast kon niet gelezen worden; de verwachting "
                        "valt terug op het statistische model."}

    if data.get("status") != "ok":
        attempt = data.get("last_attempt") or {}
        extra = (f" (exitcode {attempt['exit_code']}, fase '{attempt.get('fase')}')"
                 if attempt.get("exit_code") is not None
                 else f" (fase '{attempt['fase']}')" if attempt.get("fase") else "")
        return {**leeg, "status": "mislukt",
                "note": f"De laatste nachtelijke wflow-run is mislukt{extra}; er is nog "
                        "geen bruikbare verwachting. De verwachting valt terug op het "
                        "statistische model."}

    try:
        issue = _date.fromisoformat(str(data["issue_date"]))
    except Exception:
        return {**leeg, "status": "onleesbaar",
                "note": "De wflow-nowcast heeft geen geldige uitgiftedatum; de "
                        "verwachting valt terug op het statistische model."}

    # Een negatieve leeftijd (klokverschil) mag geen lijn laten vervallen.
    age = max((today - issue).days, 0)
    if age > MAX_AGE_DAYS:
        return {**leeg, "status": "vervallen", "age_days": age,
                "note": f"De wflow-nowcast is van {issue.isoformat()} en daarmee "
                        f"{age} dagen oud; hij wordt niet meer getoond en de "
                        "verwachting valt terug op het statistische model."}

    series = data.get("series") or {}
    if not series.get("dates"):
        # Verdediging in de leesfunctie zelf, ook al zou run_nightly() een lege
        # reeks nooit als status "ok" mogen wegschrijven: een "beschikbare"
        # nowcast zonder data is precies de stille degradatie die deze functie
        # moet uitsluiten.
        return {**leeg, "status": "leeg", "age_days": age,
                "note": f"De wflow-nowcast van {issue.isoformat()} bevat een lege "
                        "reeks; de verwachting valt terug op het statistische model."}

    status = "vers" if age <= 1 else "verouderd"
    note = ("Nachtelijke wflow SBM-nowcast."
            if status == "vers"
            else f"De wflow-nowcast is van {issue.isoformat()} ({age} dagen oud) — "
                 "de nachtrun van vannacht is niet doorgekomen.")

    # Een mislukte poging ná deze goede run mag niet onzichtbaar blijven, ook
    # al is de getoonde reeks zelf nog jong (zie Critical-2-bevinding,
    # .superpowers/sdd/2026-09-08-verwachting-v2-fase-c/).
    attempt = data.get("last_attempt")
    if attempt and attempt.get("outcome") != "ok":
        note += (f" Let op: de nachtrun van {attempt.get('date')} is mislukt"
                  + (f" (exitcode {attempt['exit_code']})"
                     if attempt.get("exit_code") is not None else "")
                  + f"; de getoonde reeks is nog van {issue.isoformat()}.")

    return {
        "available": True,
        "status": status,
        "age_days": age,
        "issue_date": data["issue_date"],
        "generated_at": data.get("generated_at"),
        "dates": series.get("dates", []),
        "q_kampen": series.get("q_kampen", []),
        "q_westervoort": series.get("q_westervoort", []),
        "q_olst": series.get("q_olst", []),
        "model": data.get("model"),
        "gauge": data.get("gauge"),
        "boundary_sources": data.get("boundary_sources"),
        "lobith_ratio": data.get("lobith_ratio"),
        "note": note,
    }
