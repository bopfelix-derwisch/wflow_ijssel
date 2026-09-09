"""Peilverwachting Kampen — hybride relatie (fase D)."""
import numpy as np
import pytest

from dashboard.stage import (
    apply_relation, band, fit_stage_relation, lake_series, monthly_climatology,
)


def test_fit_vindt_de_coefficienten_van_een_exacte_relatie():
    """Zonder ruis moet de fit de gebruikte coëfficiënten teruggeven.

    Let op: meerpeil en debiet moeten hier onafhankelijk variëren. Lopen ze
    samen op, dan is de fit nog steeds exact maar zijn b en c niet te scheiden —
    zie test_fit_verwerpt_collineaire_drijvers.
    """
    lake = [-0.30, -0.20, -0.10, 0.00, 0.10, 0.20]
    q = [400.0, 120.0, 550.0, 200.0, 330.0, 90.0]
    h = [-0.09 + 1.01 * l + 0.0005 * qq for l, qq in zip(lake, q)]

    c = fit_stage_relation(h, lake, q)
    assert c["a"] == pytest.approx(-0.09, abs=1e-6)
    assert c["b"] == pytest.approx(1.01, abs=1e-6)
    assert c["c"] == pytest.approx(0.0005, abs=1e-9)
    assert c["r2"] == pytest.approx(1.0, abs=1e-6)
    assert c["resid_std"] == pytest.approx(0.0, abs=1e-9)
    assert c["n"] == 6


def test_fit_verwerpt_ongelijke_reekslengtes():
    with pytest.raises(ValueError):
        fit_stage_relation([1.0, 2.0], [1.0], [1.0, 2.0])


def test_fit_verwerpt_te_weinig_dagen():
    with pytest.raises(ValueError):
        fit_stage_relation([1.0, 2.0], [1.0, 2.0], [1.0, 2.0])


def test_fit_verwerpt_collineaire_drijvers():
    """Lopen meerpeil en debiet samen op, dan is de fit exact (R²≈1) terwijl b
    en c individueel betekenisloos zijn — lstsq kiest dan een willekeurige
    minimum-norm-oplossing. Dat moet luid falen, niet stil een mooi getal geven."""
    lake = [-0.30, -0.20, -0.10, 0.00, 0.10, 0.20]
    q = [100.0, 200.0, 300.0, 400.0, 500.0, 600.0]   # exact evenredig met lake
    h = [-0.09 + 1.01 * l + 0.0005 * qq for l, qq in zip(lake, q)]

    with pytest.raises(ValueError, match="gecorreleerd"):
        fit_stage_relation(h, lake, q)


def test_apply_relation_rekent_per_dag():
    coef = {"a": -0.09, "b": 1.0, "c": 0.0005}
    uit = apply_relation(coef, [-0.20, -0.10], [100.0, 200.0])
    assert uit[0] == pytest.approx(-0.09 - 0.20 + 0.05)
    assert uit[1] == pytest.approx(-0.09 - 0.10 + 0.10)


def test_apply_relation_geeft_none_bij_een_ontbrekende_drijver():
    coef = {"a": 0.0, "b": 1.0, "c": 0.001}
    assert apply_relation(coef, [None, -0.2], [100.0, None]) == [None, None]


def test_klimatologie_per_maand_uit_de_reeks_zelf():
    dates = [f"2026-09-{d:02d}" for d in range(1, 11)] + \
            [f"2026-01-{d:02d}" for d in range(1, 11)]
    values = [-0.28] * 10 + [-0.10] * 10
    clim = monthly_climatology(dates, values)
    assert clim[9][0] == pytest.approx(-0.28)
    assert clim[1][0] == pytest.approx(-0.10)
    assert clim[9][1] == pytest.approx(0.0, abs=1e-9)


def test_klimatologie_negeert_maanden_met_te_weinig_dagen():
    clim = monthly_climatology(["2026-03-01", "2026-03-02"], [-0.1, -0.2])
    assert 3 not in clim


def test_meerpeil_gebruikt_rws_waar_die_er_is():
    dates = ["2026-09-09", "2026-09-10", "2026-09-11"]
    rws = {d: -0.15 for d in dates}
    v, sd, bron = lake_series(dates, rws, {9: (-0.28, 0.07)})
    assert v == [-0.15, -0.15, -0.15]
    assert sd == [0.0, 0.0, 0.0]          # officiële verwachting → geen extra band
    assert bron == ["rws", "rws", "rws"]


def test_meerpeil_valt_terug_op_klimatologie_met_spreiding():
    dates = [f"2026-09-{d:02d}" for d in range(9, 16)]
    rws = {"2026-09-09": -0.15}
    v, sd, bron = lake_series(dates, rws, {9: (-0.28, 0.07)}, blend_days=0)
    assert bron[0] == "rws" and sd[0] == 0.0
    assert all(b == "klimatologie" for b in bron[1:])
    assert all(s == pytest.approx(0.07) for s in sd[1:])
    assert all(x == pytest.approx(-0.28) for x in v[1:])


def test_meerpeil_mengt_de_overgang_zodat_het_niet_springt():
    dates = [f"2026-09-{d:02d}" for d in range(9, 16)]
    rws = {"2026-09-09": -0.10}
    v, sd, bron = lake_series(dates, rws, {9: (-0.30, 0.08)}, blend_days=2)
    assert bron[1] == "overgang" and bron[2] == "overgang"
    assert -0.30 < v[1] < -0.10 and -0.30 < v[2] < v[1]
    assert v[3] == pytest.approx(-0.30)
    # de spreiding loopt mee op met de overgang
    assert 0.0 < sd[1] < sd[2] <= 0.08


def test_meerpeil_verwerpt_een_lege_datumreeks():
    with pytest.raises(ValueError):
        lake_series([], {}, {})


def test_band_telt_residu_en_meerpeil_kwadratisch_op():
    coef = {"resid_std": 0.023, "b": 1.0}
    uit = band(coef, [0.0, 0.07], z=1.0)
    assert uit[0] == pytest.approx(0.023)
    assert uit[1] == pytest.approx(np.sqrt(0.023 ** 2 + 0.07 ** 2))


def test_band_is_breder_in_de_winter_dan_in_de_zomer():
    """De klimatologische spreiding van het meerpeil is in de winter veel groter
    (storm, windopzet); dat hoort in de band te landen."""
    coef = {"resid_std": 0.023, "b": 1.0}
    zomer = band(coef, [0.05])[0]
    winter = band(coef, [0.28])[0]
    assert winter > zomer * 3


def test_band_geeft_none_waar_het_meerpeil_ontbreekt():
    assert band({"resid_std": 0.02, "b": 1.0}, [None]) == [None]
