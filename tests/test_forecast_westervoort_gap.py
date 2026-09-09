"""Het gat in de Westervoort-reeks mag niet met een magische constante gevuld worden.

De RWS-reeks voor Westervoort loopt structureel ~2 weken achter (gemeten
2026-09-09: 21 van 36 dagen, laatste 25 augustus). `build_forecast` vulde de
resterende dagen met `fillna(400.0)`, waardoor het startpunt van het
recessiemodel exact op die constante uitkwam in plaats van op data. Gevolg:
de verwachting daalde van 390 naar 317 m³/s waar hij had moeten stijgen van
134 naar 248 — tegengestelde richting, 68% verschil op dag 7.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from dashboard.forecast import fill_westervoort_gap


IDX = pd.date_range("2026-08-05", "2026-09-09", freq="D")


def _reeks(laatste_dag: str, waarde: float = 71.0) -> pd.Series:
    """Westervoort-reeks die op `laatste_dag` ophoudt."""
    idx = pd.date_range("2026-08-05", laatste_dag, freq="D")
    return pd.Series(float(waarde), index=idx)


def test_gat_wordt_uit_lobith_gevuld(monkeypatch):
    from dashboard import forecast as fc

    lobith = {d.strftime("%Y-%m-%d"): 700.0 for d in IDX}
    monkeypatch.setattr(fc, "_lobith_metingen", lambda *a, **k: lobith)
    monkeypatch.setattr(fc, "_lobith_ratio", lambda *a, **k: 0.16)

    q, info = fill_westervoort_gap(_reeks("2026-08-25"), IDX)
    assert not q.isna().any()
    # de laatste dag komt uit Lobith, niet uit de constante
    assert q.iloc[-1] == pytest.approx(700.0 * 0.16)
    assert info["q0_bron"] == "lobith"
    assert info["gat_dagen"] == 15


def test_zonder_gat_verandert_er_niets(monkeypatch):
    from dashboard import forecast as fc

    monkeypatch.setattr(fc, "_lobith_metingen", lambda *a, **k: {})
    monkeypatch.setattr(fc, "_lobith_ratio", lambda *a, **k: None)

    vol = pd.Series(120.0, index=IDX)
    q, info = fill_westervoort_gap(vol, IDX)
    assert q.iloc[-1] == pytest.approx(120.0)
    assert info["q0_bron"] == "meting"
    assert info["gat_dagen"] == 0


def test_zonder_lobith_valt_het_terug_op_de_constante_maar_zegt_dat(monkeypatch):
    """Terugvallen mag, stil terugvallen niet."""
    from dashboard import forecast as fc

    monkeypatch.setattr(fc, "_lobith_metingen", lambda *a, **k: {})
    monkeypatch.setattr(fc, "_lobith_ratio", lambda *a, **k: None)

    q, info = fill_westervoort_gap(_reeks("2026-08-25"), IDX)
    assert not q.isna().any()
    assert info["q0_bron"] == "terugvalconstante"
    assert info["gat_dagen"] == 15


def test_het_startpunt_is_nooit_meer_stilzwijgend_de_constante(monkeypatch):
    """De kern van de bug: q0 mocht niet exact 400.0 uit de code zijn."""
    from dashboard import forecast as fc

    lobith = {d.strftime("%Y-%m-%d"): 700.0 for d in IDX}
    monkeypatch.setattr(fc, "_lobith_metingen", lambda *a, **k: lobith)
    monkeypatch.setattr(fc, "_lobith_ratio", lambda *a, **k: 0.16)

    q, _ = fill_westervoort_gap(_reeks("2026-08-25"), IDX)
    assert abs(float(q.iloc[-1]) - 400.0) > 1.0


def test_lege_reeks_valt_netjes_terug(monkeypatch):
    from dashboard import forecast as fc

    monkeypatch.setattr(fc, "_lobith_metingen", lambda *a, **k: {})
    monkeypatch.setattr(fc, "_lobith_ratio", lambda *a, **k: None)

    q, info = fill_westervoort_gap(None, IDX)
    assert not q.isna().any()
    assert info["q0_bron"] == "terugvalconstante"


def test_lobith_zonder_bruikbare_ratio_valt_terug(monkeypatch):
    """Wel Lobith-data maar geen ratio (te weinig overlap) → geen stille schaalfout."""
    from dashboard import forecast as fc

    lobith = {d.strftime("%Y-%m-%d"): 700.0 for d in IDX}
    monkeypatch.setattr(fc, "_lobith_metingen", lambda *a, **k: lobith)
    monkeypatch.setattr(fc, "_lobith_ratio", lambda *a, **k: None)

    q, info = fill_westervoort_gap(_reeks("2026-08-25"), IDX)
    assert info["q0_bron"] == "terugvalconstante"
