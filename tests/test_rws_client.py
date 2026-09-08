"""Sentinel-filtering op RWS-ruwdata (fase A)."""
import pandas as pd
import pytest

from dashboard.rws_client import (
    QUALITY_COL, QUALITY_MISSING, TIME_COL, VALUE_COL, filter_sentinels,
)


def _df(rows):
    """rows = [(tijdstip, waarde, kwaliteitscode)]"""
    return pd.DataFrame({
        TIME_COL: [r[0] for r in rows],
        VALUE_COL: [r[1] for r in rows],
        QUALITY_COL: [r[2] for r in rows],
    })


def test_verwijdert_sentinel_op_kwaliteitscode():
    df = _df([
        ("2026-01-01T00:00:00.000+01:00", -30.0, "00"),
        ("2026-01-01T00:15:00.000+01:00", 999999999.0, QUALITY_MISSING),
        ("2026-01-01T00:30:00.000+01:00", -28.0, "00"),
    ])
    clean, removed = filter_sentinels(df)
    assert removed == 1
    assert list(clean[VALUE_COL]) == [-30.0, -28.0]


def test_verwijdert_sentinel_ook_zonder_kwaliteitskolom():
    # Sommige responses missen de kwaliteitskolom; de magnitude-drempel vangt het dan.
    df = pd.DataFrame({
        TIME_COL: ["2026-01-01T00:00:00.000+01:00", "2026-01-01T00:15:00.000+01:00"],
        VALUE_COL: [-30.0, 999999999.0],
    })
    clean, removed = filter_sentinels(df)
    assert removed == 1
    assert list(clean[VALUE_COL]) == [-30.0]


def test_behoudt_kwaliteitscode_25():
    # '25' is een geldige, afwijkende code — geen sentinel.
    df = _df([("2026-01-01T00:00:00.000+01:00", -27.0, "25")])
    clean, removed = filter_sentinels(df)
    assert removed == 0
    assert len(clean) == 1


def test_verwijdert_niet_numerieke_waarden():
    df = _df([
        ("2026-01-01T00:00:00.000+01:00", "geen getal", "00"),
        ("2026-01-01T00:15:00.000+01:00", -29.0, "00"),
    ])
    clean, removed = filter_sentinels(df)
    assert removed == 1
    assert list(clean[VALUE_COL]) == [-29.0]


def test_negatieve_waarden_blijven_staan():
    # Waterstanden bij Ketelhaven zijn structureel negatief (m NAP); die mogen
    # niet als sentinel wegvallen.
    df = _df([("2026-01-01T00:00:00.000+01:00", -55.4, "00")])
    clean, removed = filter_sentinels(df)
    assert removed == 0
    assert clean[VALUE_COL].iloc[0] == pytest.approx(-55.4)


def test_leeg_dataframe():
    clean, removed = filter_sentinels(pd.DataFrame())
    assert removed == 0
    assert len(clean) == 0


def test_none_dataframe():
    clean, removed = filter_sentinels(None)
    assert clean is None
    assert removed == 0
