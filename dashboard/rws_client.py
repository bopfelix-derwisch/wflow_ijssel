"""Enige ingang naar RWS Waterinfo.

RWS levert ontbrekende metingen als de sentinelwaarde 999999999, met
`WaarnemingMetadata.Kwaliteitswaardecode == "99"`. Wie die meemiddelt in een
dag-gemiddelde krijgt een dagwaarde van ~6,9 miljoen (999999999 / 144
kwartierwaarden). Gemeten besmetting over 2023-09 … 2026-09: kampen.ijssel
0,03 %, ketelhaven.ketelmeer 0,26 %, olst 0,18 %, westervoort 0,24 %.

Deze module filtert dat weg vóór het resamplen. Alle RWS-verkeer in het
dashboard loopt hier doorheen — voeg geen tweede `rw.get_data`-aanroep toe.

Zie docs/superpowers/specs/2026-09-08-verwachting-v2-wflow-design.md §2.5.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import rws_waterinfo as rw
    _RWS_OK = True
except ImportError:  # pragma: no cover
    rw = None
    _RWS_OK = False
    logger.warning("rws_waterinfo niet geïnstalleerd — RWS-data niet beschikbaar")

QUALITY_MISSING = "99"
SENTINEL_ABS = 1e6

VALUE_COL = "Meetwaarde.Waarde_Numeriek"
QUALITY_COL = "WaarnemingMetadata.Kwaliteitswaardecode"
TIME_COL = "Tijdstip"


def filter_sentinels(df: "pd.DataFrame | None") -> tuple["pd.DataFrame | None", int]:
    """Gooi sentinel- en niet-numerieke rijen weg.

    Retourneert (schone dataframe, aantal verwijderde rijen). Filtert op de
    kwaliteitscode als die kolom er is, en altijd op magnitude — sommige
    responses leveren de kolom niet mee.
    """
    if df is None or len(df) == 0:
        return df, 0

    values = pd.to_numeric(df[VALUE_COL], errors="coerce")
    keep = values.notna() & (values.abs() < SENTINEL_ABS)
    if QUALITY_COL in df.columns:
        keep &= df[QUALITY_COL].astype(str) != QUALITY_MISSING

    return df[keep], int((~keep).sum())


def daily_series(locatie: str, grootheid: str, eenheid: str,
                 start, end, proces_type: str = "meting") -> "pd.Series | None":
    """Daggemiddelde RWS-reeks, sentinelvrij.

    Retourneert None bij uitval, lege respons of als er na filtering niets
    overblijft — nooit een reeks met sentinelwaarden erin.
    """
    if not _RWS_OK:
        return None
    try:
        df = rw.get_data(
            [{
                "locatie_code":      locatie,
                "compartiment_code": "OW",
                "grootheid_code":    grootheid,
                "eenheid_code":      eenheid,
                "start_date":        str(start),
                "end_date":          str(end),
                "proces_type":       proces_type,
            }],
            return_df=True,
            parallel=False,
        )
        if df is None or len(df) == 0:
            return None

        clean, removed = filter_sentinels(df)
        if removed:
            logger.info("RWS %s/%s/%s: %d sentinel-rijen verwijderd",
                        locatie, grootheid, proces_type, removed)
        if clean is None or len(clean) == 0:
            return None

        idx = pd.to_datetime(clean[TIME_COL].str[:19])
        vals = pd.to_numeric(clean[VALUE_COL]).astype(float)
        s = pd.Series(vals.values, index=idx).sort_index()
        daily = s.resample("D").mean().dropna()
        if len(daily) == 0:
            return None
        logger.info("RWS %s/%s/%s: %d dagwaarden", locatie, grootheid, proces_type, len(daily))
        return daily
    except Exception as e:
        logger.warning("RWS %s/%s: %s", locatie, grootheid, e)
        return None
