"""WL-BRO-1 / Proef 9 — grondwater↔IJssel koppeling (analyse + AI-duiding).

Bouwt de overlay grondwaterstand (BRO GLD) vs IJssel-peil bij Kampen voor een
droogte-event (zomer 2018), berekent de lag-correlatie (rivierpeil →
grondwaterrespons) en laat Qwen2.5-32B lokaal een hydrologische duiding geven.

Hergebruikt de bestaande IJssel-reeks op schijf (wflow output) — geen refetch.
"""
from __future__ import annotations

import json
import logging
import time

import numpy as np
import requests

from dashboard import bro_gld
from dashboard.forecast import build_forecast
from fews_poc.data_adapter import PERIOD_DIRS

logger = logging.getLogger(__name__)

# event → (period-key voor de IJssel-reeks, vensterstart, venstereind)
EVENTS = {
    "zomer2018": ("2018", "2018-05-02", "2018-08-31"),
}

LLM_BASE_URL = "http://127.0.0.1:8080"
LLM_MODEL    = "qwen2.5-32b-instruct-q4_k_m-00001-of-00005.gguf"

_cache: dict = {}
_TTL = 900  # 15 min

# Gekalibreerde koppeling rivierpeil → Veluwe-grondwater (mediaan uit de zomer-2018
# analyse: lags 6–28 d, r 0.77–0.94). Gebruikt om de live IJssel-verwachting door te
# vertalen naar verwachte grondwaterrespons in de integrale interventie (Proef 1).
CALIBRATED_LAG_DAYS = 18
CALIBRATED_R = 0.9
# Datadichte putten met recente metingen langs de Veluwe-oostflank (zuid → flank).
CONTEXT_WELLS = ["GLD000000008239", "GLD000000008262"]
_ctx_cache: dict = {}


# ── IJssel-signaal (bestaande wflow-reeks op schijf) ─────────────────────────

def _river_signal(period: str, start: str, end: str) -> dict:
    """IJssel Kampen reeks uit wflow output: {dates, h, q (m³/s)}, geclipt.

    LET OP: h = wflow river_water__depth (rivierwaterdiepte in m boven de bedding),
    GÉÉN waterpeil in m+NAP. De lag-correlatie is schaal-invariant, dus dit verandert
    de r-waarden niet; alleen de eenheid-labels moeten 'rivierdiepte (m)' zijn.
    """
    path = PERIOD_DIRS.get(period, PERIOD_DIRS.get("2018")) / "timeseries_kampen.json"
    d = json.loads(path.read_text())
    dates, h, q = d.get("dates", []), d.get("h", []), d.get("q", [])
    out = {"dates": [], "h": [], "q": []}
    for i, dt in enumerate(dates):
        ds = str(dt)[:10]
        if start <= ds <= end:
            out["dates"].append(ds)
            out["h"].append(float(h[i]) if i < len(h) and h[i] is not None else None)
            out["q"].append(float(q[i]) if i < len(q) and q[i] is not None else None)
    return out


# ── lag-correlatie ───────────────────────────────────────────────────────────

def _lag_correlation(river_dates, river_vals, gw_dates, gw_vals, max_lag=30) -> dict:
    """Pearson r tussen rivierpeil[t] en grondwater[t+lag]; lag in dagen 0..max_lag.

    Positieve lag = grondwater reageert ná de rivier. Retourneert beste lag + r.
    """
    from datetime import date, timedelta

    rv = {d: v for d, v in zip(river_dates, river_vals) if v is not None}
    gw = {d: v for d, v in zip(gw_dates, gw_vals) if v is not None}
    if len(rv) < 10 or len(gw) < 10:
        return {"lag_days": None, "r": None}

    def shift(d, k):
        return (date.fromisoformat(d) + timedelta(days=k)).isoformat()

    best = {"lag_days": None, "r": None}
    for lag in range(0, max_lag + 1):
        xs, ys = [], []
        for d, rval in rv.items():
            gd = shift(d, lag)
            if gd in gw:
                xs.append(rval); ys.append(gw[gd])
        if len(xs) >= 10:
            r = float(np.corrcoef(xs, ys)[0, 1])
            if not np.isnan(r) and (best["r"] is None or abs(r) > abs(best["r"])):
                best = {"lag_days": lag, "r": round(r, 3)}
    return best


# ── AI-duiding (Qwen lokaal, graceful fallback) ──────────────────────────────

_SYSTEM = """Je bent een hydroloog gespecialiseerd in oppervlaktewater–grondwater-interactie \
langs de IJssel en de Veluwe. Geef een beknopte, feitelijke duiding in het Nederlands \
(maximaal 180 woorden, doorlopende tekst, geen opsomming). Leg de gevonden lag-correlatie \
uit in termen van kweldruk, drooglegging en de Veluwe-flank, en benoem de belangrijkste \
onzekerheid van een puur data-gedreven toets."""


def _interpret(summary: dict) -> str:
    lines = [
        f"Droogte-event: {summary['event']} (IJssel bij Kampen, {summary['window']}).",
        f"IJssel-stand (wflow rivierdiepte) daalde van {summary['river_h_first']} naar {summary['river_h_last']} m.",
        "Grondwater-monitoringputten (BRO GLD), met lag-correlatie IJssel-stand → grondwater:",
    ]
    for w in summary["wells"]:
        if w.get("r") is not None:
            lines.append(
                f"  - {w['bro_id']} ({w['lat']},{w['lon']}): "
                f"grondwater {w['gw_first']}→{w['gw_last']} m, "
                f"beste lag {w['lag_days']} d, r={w['r']}"
            )
    lines.append("Duid deze koppeling hydrologisch voor een waterbeheerder.")
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": "\n".join(lines)},
        ],
        "max_tokens": 500,
        "temperature": 0.3,
    }
    resp = requests.post(f"{LLM_BASE_URL}/v1/chat/completions", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


# ── hoofd-functie ────────────────────────────────────────────────────────────

def build_grondwater(event: str = "zomer2018", max_wells: int = 5) -> dict:
    cached = _cache.get(event)
    if cached and time.monotonic() - cached[0] < _TTL:
        return cached[1]

    if event not in EVENTS:
        return {"available": False, "error": f"onbekend event: {event}"}
    period, start, end = EVENTS[event]

    river = _river_signal(period, start, end)
    h = [v for v in river["h"] if v is not None]
    if not river["dates"] or not h:
        return {"available": False, "error": "IJssel-reeks ontbreekt op schijf"}

    # Putten: gecureerde set (gespreid, datadicht) — discovery beschikbaar als fallback/refresh.
    candidates = bro_gld.CURATED_WELLS[:max_wells] or bro_gld.discover_wells()[:max_wells]

    wells = []
    for c in candidates:
        series = bro_gld.fetch_series(c["bro_id"], start, end)
        if not series:
            continue
        gw_dates = [e["date"] for e in series]
        gw_vals  = [e["value"] for e in series]
        corr = _lag_correlation(river["dates"], river["h"], gw_dates, gw_vals)
        wells.append({
            **c,
            "series": {"dates": gw_dates, "values": gw_vals},
            "gw_first": gw_vals[0], "gw_last": gw_vals[-1],
            "lag_days": corr["lag_days"], "r": corr["r"],
        })

    result = {
        "available": True,
        "event": event,
        "window": {"start": start, "end": end},
        "river": river,
        "wells": wells,
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    _cache[event] = (time.monotonic(), result)
    return result


# Aparte cache voor de (trage) LLM-duiding — zelfde patroon als /api/forecast/intervention.
_interp_cache: dict = {}


def build_interpretation(event: str = "zomer2018") -> dict:
    """Qwen-duiding op de (snelle) overlay-data. Apart endpoint zodat de grafiek
    direct rendert en de AI-tekst async volgt. Graceful fallback bij LLM-uitval."""
    cached = _interp_cache.get(event)
    if cached and time.monotonic() - cached[0] < _TTL:
        return cached[1]
    data = build_grondwater(event)
    if not data.get("available"):
        return {"available": False}
    h = [v for v in data["river"]["h"] if v is not None]
    summary = {
        "event": event,
        "window": f'{data["window"]["start"]} – {data["window"]["end"]}',
        "river_h_first": round(h[0], 2) if h else None,
        "river_h_last": round(h[-1], 2) if h else None,
        "wells": data["wells"],
    }
    try:
        out = {"available": True, "interpretation": _interpret(summary), "llm_available": True}
    except Exception as e:
        logger.warning("Qwen-duiding niet beschikbaar: %s", e)
        out = {"available": True, "interpretation": "", "llm_available": False}
    _interp_cache[event] = (time.monotonic(), out)
    return out


# ── Integrale forecast-context: actuele Veluwe-grondwaterstand + koppeling ────

def forecast_groundwater_context() -> dict:
    """Recente gemeten Veluwe-grondwaterstand + 90-daagse trend, plus de
    gekalibreerde rivier→grondwater-koppeling. Voedt de integrale interventie
    (Proef 1). Gecached; graceful (lege wells-lijst bij bron-uitval)."""
    hit = _ctx_cache.get("ctx")
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    wells = []
    for bid in CONTEXT_WELLS:
        s = bro_gld.fetch_series(bid)
        if not s:
            continue
        recent = s[-90:]
        trend = round(recent[-1]["value"] - recent[0]["value"], 2) if len(recent) >= 2 else None
        wells.append({
            "bro_id": bid,
            "last_date": s[-1]["date"],
            "last_value": s[-1]["value"],
            "trend_90d": trend,
        })
    ctx = {"wells": wells, "lag_days": CALIBRATED_LAG_DAYS, "r": CALIBRATED_R}
    _ctx_cache["ctx"] = (time.monotonic(), ctx)
    return ctx


# ── Vooruitblik: verwachte grondwaterrespons o.b.v. de live IJssel-verwachting ─

_proj_cache: dict = {}


def _calibrate_q(river_dates, river_q, gw_dates, gw_vals, max_lag=30) -> dict:
    """Kalibreer op het droogte-event: beste lag + lineaire helling (dGW/dQ)
    tussen IJssel-afvoer[t] en grondwater[t+lag]. Afvoer (q) is de driver want die
    is in zowel het event als de live verwachting betrouwbaar beschikbaar."""
    from datetime import date, timedelta
    rv = {d: v for d, v in zip(river_dates, river_q) if v is not None}
    gw = {d: v for d, v in zip(gw_dates, gw_vals) if v is not None}
    best = {"lag_days": None, "r": None, "slope": None}
    for lag in range(0, max_lag + 1):
        xs, ys = [], []
        for d, rval in rv.items():
            gd = (date.fromisoformat(d) + timedelta(days=lag)).isoformat()
            if gd in gw:
                xs.append(rval); ys.append(gw[gd])
        if len(xs) >= 10:
            r = float(np.corrcoef(xs, ys)[0, 1])
            if not np.isnan(r) and (best["r"] is None or abs(r) > abs(best["r"])):
                best = {"lag_days": lag, "r": round(r, 3), "slope": float(np.polyfit(xs, ys, 1)[0])}
    return best


def project_groundwater(event_calib: str = "zomer2018", max_wells: int = 5) -> dict:
    """Projecteer de verwachte grondwater-RESPONS (Δm t.o.v. vandaag) per put over
    de komende dagen, gedreven door de live 14-daagse IJssel-afvoerverwachting via de
    op het event gekalibreerde lag+helling. De eerste ~lag dagen zijn al 'vastgelegd'
    door reeds-waargenomen afvoer; daarna telt de forecast. Indicatief, relatief."""
    cached = _proj_cache.get(event_calib)
    if cached and time.monotonic() - cached[0] < _TTL:
        return cached[1]

    base = build_grondwater(event_calib, max_wells)
    if not base.get("available"):
        return {"available": False, "error": "kalibratie-event niet beschikbaar"}
    try:
        fc = build_forecast()
    except Exception as e:
        return {"available": False, "error": f"verwachting niet beschikbaar: {e}"}

    from datetime import date, timedelta
    addd = lambda d, k: (date.fromisoformat(d) + timedelta(days=k)).isoformat()

    # Live IJssel-afvoer driver: gemeten (~35 d) + verwacht (14 d)
    m, f = fc.get("measured", {}), fc.get("forecast", {})
    river_q: dict = {}
    for d, q in zip(m.get("dates", []), m.get("q_kampen", [])):
        if q is not None:
            river_q[str(d)[:10]] = float(q)
    fcast_dates = [str(d)[:10] for d in f.get("dates", [])]
    for d, q in zip(fcast_dates, f.get("q_mid", [])):
        if q is not None:
            river_q[d] = float(q)
    today = str(fc.get("generated_at"))[:10]
    river18 = base["river"]

    wells_out, horizon = [], 14
    for w in base["wells"]:
        cal = _calibrate_q(river18["dates"], river18["q"], w["series"]["dates"], w["series"]["values"])
        if cal["slope"] is None:
            continue
        L, slope = cal["lag_days"], cal["slope"]
        q_ref = river_q.get(addd(today, -L))
        if q_ref is None:
            continue
        wh = L + 14
        horizon = max(horizon, wh)
        dates_p, delta_p, src_p = [], [], []
        for dd in range(0, wh + 1):
            qd = river_q.get(addd(today, dd - L))
            if qd is None:
                continue
            dates_p.append(addd(today, dd))
            delta_p.append(round(slope * (qd - q_ref), 3))
            src_p.append("forecast" if (dd - L) > 0 else "vastgelegd")
        if not dates_p:
            continue
        end = delta_p[-1]
        full = bro_gld.fetch_series(w["bro_id"])  # volledige reeks → laatste echte meting (anker)
        last_value = full[-1]["value"] if full else None
        last_date = full[-1]["date"] if full else None
        wells_out.append({
            "bro_id": w["bro_id"], "lat": w["lat"], "lon": w["lon"],
            "lag_days": L, "r": cal["r"], "slope": round(slope, 6),
            "committed_days": L,
            "last_value": last_value, "last_date": last_date,
            "projection": {"dates": dates_p, "delta_m": delta_p, "source": src_p},
            "expected_change_m": end,
            "direction": "stijgend" if end > 0.02 else ("dalend" if end < -0.02 else "stabiel"),
        })

    sd = sorted(river_q)
    result = {
        "available": True,
        "today": today,
        "horizon_days": horizon,
        "calibrated_on": event_calib,
        "river": {"dates": sd, "q": [river_q[d] for d in sd],
                  "forecast_from": fcast_dates[0] if fcast_dates else None},
        "wells": wells_out,
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    _proj_cache[event_calib] = (time.monotonic(), result)
    return result
