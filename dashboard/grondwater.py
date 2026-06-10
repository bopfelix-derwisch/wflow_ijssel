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


# ── IJssel-signaal (bestaande wflow-reeks op schijf) ─────────────────────────

def _river_signal(period: str, start: str, end: str) -> dict:
    """IJssel Kampen reeks uit wflow output: {dates, h (m+NAP), q (m³/s)}, geclipt."""
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
        f"IJssel-peil daalde van {summary['river_h_first']} naar {summary['river_h_last']} m+NAP.",
        "Grondwater-monitoringputten (BRO GLD), met lag-correlatie rivierpeil → grondwater:",
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
