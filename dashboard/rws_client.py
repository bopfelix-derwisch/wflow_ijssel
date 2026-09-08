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
