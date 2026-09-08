"""Instroom-randvoorwaarde bij Westervoort voor de operationele wflow-run.

wflow krijgt de Rijn-instroom als randvoorwaarde bij Westervoort (6.154 O,
51.987 N). Per dag, in aflopende prioriteit:

  1. Westervoort-meting                       — waar aanwezig
  2. Lobith-meting × ratio                     — vult het gat in de
                                                  Westervoort-reeks tot en
                                                  met vandaag
  3. Lobith-verwachting × ratio                — D+1 … D+3
  4. recessiemodel, gemengd over `blend_days`  — D+4 en verder

Westervoort-metingen lopen bij RWS structureel achter — in de praktijk tot
ruim twee weken (geverifieerd 2026-09-08: laatste Westervoort-dagwaarde
14 dagen oud, terwijl Lobith en Olst tot en met vandaag compleet zijn). Zonder
laag 2 zou de randvoorwaarde voor de nowcast-dag zelf al op het recessiemodel
terugvallen — een extrapolatie in plaats van een waarneming, precies wat fase
C moest oplossen. Laag 2 vult dat gat met de (geschaalde) Lobith-meting, die
wél actueel is, zodat de randvoorwaarde tot en met vandaag op een echte
waarneming rust.

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
from datetime import date, timedelta

logger = logging.getLogger(__name__)

LOBITH = "lobith.bovenrijn.tolkamer"
WESTERVOORT = "westervoort"
MIN_OVERLAP = 20
RATIO_WINDOW_DAYS = 90


def lobith_ratio(q_lobith: dict, q_westervoort: dict,
                 min_overlap: int = MIN_OVERLAP,
                 window_days: "int | None" = RATIO_WINDOW_DAYS) -> "float | None":
    """Mediane verhouding Westervoort/Lobith over de overlappende dagen.

    Deze ratio is regime-afhankelijk, geen constante: de verdeling van de
    Rijnafvoer over de Rijntakken wordt bij de stuw bij Driel geregeld, en het
    IJssel-aandeel loopt op bij lage afvoer en zakt bij hoogwater. "De IJssel
    is ruwweg een negende van de Rijn" is dus een langjarig gemiddelde, geen
    huidige waarde — een vaste 1/9 zou de randvoorwaarde bij het actuele
    afvoerregime stelselmatig verkeerd zetten. Daarom kalibreert deze functie
    standaard op de meest recente `window_days` dagen, zodat de ratio het
    regime van dit moment volgt in plaats van jaren aan hoog- en laagwater tot
    één getal glad te strijken. **Verander de standaard niet terug naar een
    vaste breuk** — dat is precies de fout die dit venster voorkomt.

    Is er binnen dat venster te weinig overlap (minder dan `min_overlap`
    dagen met een geldig paar), dan valt de functie terug op de volledige
    aangeleverde historie in plaats van meteen `None` te geven — een iets
    verouderde ratio is bruikbaarder dan geen ratio. Alleen als ook de
    volledige historie te weinig overlap heeft, is het resultaat `None`.
    `window_days=None` schakelt het venster uit en kalibreert direct op de
    volledige historie.
    """
    def ratios_since(cutoff):
        out = []
        for d, lob in q_lobith.items():
            if cutoff is not None and d < cutoff:
                continue
            wes = q_westervoort.get(d)
            if wes is None or lob is None or lob <= 0 or wes <= 0:
                continue
            out.append(wes / lob)
        return out

    if window_days is not None:
        anchor = max(q_lobith, default=None)
        cutoff = None
        if anchor is not None:
            try:
                cutoff = (date.fromisoformat(anchor) - timedelta(days=window_days)).isoformat()
            except ValueError:
                cutoff = None  # sleutels zijn geen ISO-datums (bv. in tests) -> geen venster
        if cutoff is not None:
            recent = ratios_since(cutoff)
            if len(recent) >= min_overlap:
                return float(statistics.median(recent))

    ratios = ratios_since(None)
    if len(ratios) < min_overlap:
        return None
    return float(statistics.median(ratios))


def blend(measured: dict, lobith_meting: dict, rws: dict, recession: dict,
          dates: list, blend_days: int = 2) -> list:
    """Stel de randvoorwaarde samen.

    Bronprioriteit per dag: Westervoort-meting > Lobith-meting (geschaald)
    > Lobith-verwachting (geschaald) > recessie. Over `blend_days` na de
    laatste dag met een Lobith-verwachting wordt lineair naar de recessie
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
        if d in lobith_meting:
            out.append(float(lobith_meting[d]))
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

    # Laag 2: Lobith-meting geschaald, vult het (structurele) gat in de
    # Westervoort-reeks tot en met vandaag.
    lob_meting = {}
    if ratio is not None:
        lob_meting = {d: v * ratio for d, v in lob.items() if d not in wes}

    lob_fc = as_map(rws_client.daily_series(
        LOBITH, "Q", "m3/s", today, today + timedelta(days=14), proces_type="verwachting"))
    rws_fc = {}
    if ratio is not None:
        rws_fc = {d: v * ratio for d, v in lob_fc.items()
                  if d not in wes and d not in lob_meting}

    q0 = wes[max(wes)] if wes else float(_seasonal_mean(today.month))
    rec_vals = _recession(q0, len(dates), today.month)
    recession = {d: float(v) for d, v in zip(dates, np.asarray(rec_vals, dtype=float))}

    values = blend(wes, lob_meting, rws_fc, recession, dates)
    sources = [
        "meting" if d in wes else
        ("lobith-meting" if d in lob_meting else
         ("lobith-verwachting" if d in rws_fc else "recessie"))
        for d in dates
    ]
    logger.info("randvoorwaarde: ratio=%s, bronnen=%s",
                round(ratio, 4) if ratio else None,
                {s: sources.count(s) for s in set(sources)})
    return {"values": values, "sources": sources, "ratio": ratio}
