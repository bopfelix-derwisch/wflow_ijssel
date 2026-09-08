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


def test_daily_series_middelt_per_dag_zonder_sentinels(monkeypatch):
    """Twee dagen, met op dag 1 een sentinel die het gemiddelde zou verzieken."""
    from dashboard import rws_client

    raw = pd.DataFrame({
        TIME_COL: [
            "2026-01-01T00:00:00.000+01:00",
            "2026-01-01T00:15:00.000+01:00",
            "2026-01-02T00:00:00.000+01:00",
        ],
        VALUE_COL: [10.0, 999999999.0, 30.0],
        QUALITY_COL: ["00", QUALITY_MISSING, "00"],
    })
    monkeypatch.setattr(rws_client, "_RWS_OK", True)
    monkeypatch.setattr(rws_client, "rw", type("F", (), {
        "get_data": staticmethod(lambda *a, **k: raw)})())

    s = rws_client.daily_series("x", "WATHTE", "cm", "2026-01-01", "2026-01-02")
    assert list(s.values) == [10.0, 30.0]
    assert [str(d.date()) for d in s.index] == ["2026-01-01", "2026-01-02"]


def test_daily_series_geeft_none_bij_lege_respons(monkeypatch):
    from dashboard import rws_client

    monkeypatch.setattr(rws_client, "_RWS_OK", True)
    monkeypatch.setattr(rws_client, "rw", type("F", (), {
        "get_data": staticmethod(lambda *a, **k: pd.DataFrame())})())
    assert rws_client.daily_series("x", "Q", "m3/s", "2026-01-01", "2026-01-02") is None


def test_daily_series_geeft_none_als_alles_sentinel_is(monkeypatch):
    from dashboard import rws_client

    raw = pd.DataFrame({
        TIME_COL: ["2026-01-01T00:00:00.000+01:00"],
        VALUE_COL: [999999999.0],
        QUALITY_COL: [QUALITY_MISSING],
    })
    monkeypatch.setattr(rws_client, "_RWS_OK", True)
    monkeypatch.setattr(rws_client, "rw", type("F", (), {
        "get_data": staticmethod(lambda *a, **k: raw)})())
    assert rws_client.daily_series("x", "Q", "m3/s", "2026-01-01", "2026-01-02") is None


def test_daily_series_slikt_uitzonderingen(monkeypatch):
    from dashboard import rws_client

    def boom(*a, **k):
        raise RuntimeError("netwerk stuk")

    monkeypatch.setattr(rws_client, "_RWS_OK", True)
    monkeypatch.setattr(rws_client, "rw", type("F", (), {
        "get_data": staticmethod(boom)})())
    assert rws_client.daily_series("x", "Q", "m3/s", "2026-01-01", "2026-01-02") is None


def test_daily_series_geeft_none_als_rws_waterinfo_niet_geinstalleerd_is(monkeypatch):
    """_RWS_OK=False (ontbrekende dependency) — geen fetch-poging, gewoon None."""
    from dashboard import rws_client

    def boom(*a, **k):
        raise AssertionError("get_data mag niet aangeroepen worden als _RWS_OK=False")

    monkeypatch.setattr(rws_client, "_RWS_OK", False)
    monkeypatch.setattr(rws_client, "rw", type("F", (), {
        "get_data": staticmethod(boom)})())
    assert rws_client.daily_series("x", "Q", "m3/s", "2026-01-01", "2026-01-02") is None


def test_daily_series_slaat_dag_zonder_echte_data_over(monkeypatch):
    """Drie kalenderdagen, dag 2 bestaat alleen uit sentinelrijen.

    `daily_series` telt dagen mét echte data (dropna na resample), dus de
    reeks heeft lengte 2, niet 3 — dag 2 ontbreekt in de index. Wie de volle
    periode nodig heeft (zoals forecast.py's reindex/interpolate/bfill-pad)
    herindexeert zelf op de volledige datumreeks; die dag komt dan terug als
    NaN. Dat is precies de eigenschap die dit vastlegt.
    """
    from dashboard import rws_client

    raw = pd.DataFrame({
        TIME_COL: [
            "2026-01-01T00:00:00.000+01:00",
            "2026-01-02T00:00:00.000+01:00",
            "2026-01-02T00:15:00.000+01:00",
            "2026-01-03T00:00:00.000+01:00",
        ],
        VALUE_COL: [10.0, 999999999.0, 999999999.0, 30.0],
        QUALITY_COL: ["00", QUALITY_MISSING, QUALITY_MISSING, "00"],
    })
    monkeypatch.setattr(rws_client, "_RWS_OK", True)
    monkeypatch.setattr(rws_client, "rw", type("F", (), {
        "get_data": staticmethod(lambda *a, **k: raw)})())

    s = rws_client.daily_series("x", "WATHTE", "cm", "2026-01-01", "2026-01-03")
    assert len(s) == 2
    assert [str(d.date()) for d in s.index] == ["2026-01-01", "2026-01-03"]

    volledig = s.reindex(pd.date_range("2026-01-01", "2026-01-03", freq="D"))
    assert volledig.isna().tolist() == [False, True, False]


def test_forecast_rws_daily_delegeert_naar_client(monkeypatch):
    """forecast._rws_daily blijft bestaan (assimilation.py en validation.py
    importeren die naam) maar mag geen eigen fetch-logica meer hebben."""
    from dashboard import forecast, rws_client

    gezien = {}

    def nep(locatie, grootheid, eenheid, start, end, proces_type="meting"):
        gezien.update(locatie=locatie, proces_type=proces_type)
        return pd.Series([1.0], index=pd.to_datetime(["2026-01-01"]))

    monkeypatch.setattr(rws_client, "daily_series", nep)
    out = forecast._rws_daily("westervoort", "Q", "m3/s", "2026-01-01", "2026-01-02")
    assert gezien == {"locatie": "westervoort", "proces_type": "meting"}
    assert list(out.values) == [1.0]
