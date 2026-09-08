"""Instroom-randvoorwaarde bij Westervoort voor de operationele wflow-run.

wflow krijgt de Rijn-instroom als randvoorwaarde bij Westervoort (6.154 O,
51.987 N). Per dag:

  D-n … D    RWS-meting Westervoort
  D+1 … D+3  RWS-verwachting Lobith, geschaald naar Westervoort
  D+4 … D+14 recessiemodel

RWS-verwachtingen reiken maar ~3 dagen (geverifieerd 2026-09-08), vandaar de
recessie voor de rest. De overgang wordt over enkele dagen gemengd zodat er
geen sprong in de randvoorwaarde ontstaat.

Olst wordt hier bewust NIET gebruikt: dat ligt bínnen het modeldomein,
benedenstrooms van de instroomrand, en zou het gebied tussen Westervoort en
Olst dubbeltellen. Olst is het validatiepunt, niet de randvoorwaarde.
"""
from __future__ import annotations

import logging
import statistics

logger = logging.getLogger(__name__)

LOBITH = "lobith.bovenrijn.tolkamer"
WESTERVOORT = "westervoort"
MIN_OVERLAP = 20


def lobith_ratio(q_lobith: dict, q_westervoort: dict,
                 min_overlap: int = MIN_OVERLAP) -> "float | None":
    """Mediane verhouding Westervoort/Lobith over de overlappende dagen.

    De IJssel is ruwweg een negende van de Rijnafvoer, maar die verhouding
    varieert met het afvoerregime — we meten hem dus, en nemen hem niet aan.
    """
    ratios = []
    for d, lob in q_lobith.items():
        wes = q_westervoort.get(d)
        if wes is None or lob is None or lob <= 0 or wes <= 0:
            continue
        ratios.append(wes / lob)
    if len(ratios) < min_overlap:
        return None
    return float(statistics.median(ratios))


def blend(measured: dict, rws: dict, recession: dict,
          dates: list, blend_days: int = 2) -> list:
    """Stel de randvoorwaarde samen; meting > RWS-verwachting > recessie.

    Over `blend_days` na de laatste RWS-dag wordt lineair naar de recessie
    gemengd, zodat de randvoorwaarde niet springt.
    """
    if not dates:
        raise ValueError("dates mag niet leeg zijn")

    last_rws = max((d for d in dates if d in rws), default=None)
    out = []
    for d in dates:
        if d in measured:
            out.append(float(measured[d]))
            continue
        if d in rws:
            out.append(float(rws[d]))
            continue

        rec = float(recession[d])
        if last_rws is not None and blend_days > 0 and d > last_rws:
            steps_after = sum(1 for x in dates if last_rws < x <= d)
            if steps_after <= blend_days:
                w = steps_after / (blend_days + 1)
                out.append(float(rws[last_rws]) * (1 - w) + rec * w)
                continue
        out.append(rec)
    return out


def build_boundary(dates: list) -> dict:
    """Haal de bronnen op en stel de randvoorwaarde samen voor `dates`."""
    from datetime import date, timedelta

    import numpy as np

    from dashboard import rws_client
    from dashboard.forecast import _recession, _seasonal_mean

    today = date.today()
    hist_start = today - timedelta(days=400)

    def as_map(series):
        if series is None:
            return {}
        return {ts.strftime("%Y-%m-%d"): float(v) for ts, v in series.items()}

    wes = as_map(rws_client.daily_series(WESTERVOORT, "Q", "m3/s", hist_start, today))
    lob = as_map(rws_client.daily_series(LOBITH, "Q", "m3/s", hist_start, today))
    ratio = lobith_ratio(lob, wes)

    lob_fc = as_map(rws_client.daily_series(
        LOBITH, "Q", "m3/s", today, today + timedelta(days=14), proces_type="verwachting"))
    rws_fc = {}
    if ratio is not None:
        rws_fc = {d: v * ratio for d, v in lob_fc.items() if d not in wes}

    q0 = wes[max(wes)] if wes else float(_seasonal_mean(today.month))
    rec_vals = _recession(q0, len(dates), today.month)
    recession = {d: float(v) for d, v in zip(dates, np.asarray(rec_vals, dtype=float))}

    values = blend(wes, rws_fc, recession, dates)
    sources = [
        "meting" if d in wes else ("rws" if d in rws_fc else "recessie")
        for d in dates
    ]
    logger.info("randvoorwaarde: ratio=%s, bronnen=%s",
                round(ratio, 4) if ratio else None,
                {s: sources.count(s) for s in set(sources)})
    return {"values": values, "sources": sources, "ratio": ratio}
