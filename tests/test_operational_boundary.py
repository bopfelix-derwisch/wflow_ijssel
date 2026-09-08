"""Instroom-randvoorwaarde bij Westervoort (fase C)."""
import datetime

import pytest

from wflow_ijssel.operational.boundary import blend, lobith_ratio


DATES = [f"2026-09-{d:02d}" for d in range(1, 11)]


def test_blend_kiest_meting_boven_alles():
    measured = {"2026-09-01": 100.0, "2026-09-02": 110.0}
    rws = {"2026-09-01": 999.0, "2026-09-02": 999.0}
    recession = {d: 50.0 for d in DATES}
    out = blend(measured, {}, rws, recession, DATES[:2])
    assert out == [100.0, 110.0]


def test_blend_gebruikt_rws_waar_geen_meting_is():
    measured = {"2026-09-01": 100.0}
    rws = {"2026-09-02": 120.0, "2026-09-03": 130.0}
    recession = {d: 50.0 for d in DATES}
    out = blend(measured, {}, rws, recession, DATES[:3], blend_days=0)
    assert out == [100.0, 120.0, 130.0]


def test_blend_valt_terug_op_recessie_voorbij_de_rws_horizon():
    measured = {}
    rws = {"2026-09-01": 120.0}
    recession = {d: 60.0 for d in DATES}
    out = blend(measured, {}, rws, recession, DATES[:4], blend_days=0)
    assert out == [120.0, 60.0, 60.0, 60.0]


def test_blend_mengt_de_overgang_zodat_er_geen_sprong_ontstaat():
    """Zonder menging springt de randvoorwaarde van 120 naar 60 in één dag."""
    measured = {}
    rws = {"2026-09-01": 120.0}
    recession = {d: 60.0 for d in DATES}
    out = blend(measured, {}, rws, recession, DATES[:4], blend_days=2)
    assert out[0] == pytest.approx(120.0)
    # twee tussenstappen, monotoon dalend, eindigend op de recessiewaarde
    assert 60.0 < out[1] < 120.0
    assert 60.0 < out[2] < out[1]
    assert out[3] == pytest.approx(60.0)


def test_blend_verwerpt_een_lege_datumreeks():
    with pytest.raises(ValueError):
        blend({}, {}, {}, {}, [])


def test_blend_kiest_lobith_meting_boven_verwachting_en_recessie():
    """Lobith-meting (geschaald) gaat vóór de Lobith-verwachting en de recessie."""
    measured = {}
    lobith_meting = {"2026-09-01": 111.0, "2026-09-02": 112.0}
    rws = {"2026-09-01": 999.0, "2026-09-03": 130.0}
    recession = {d: 50.0 for d in DATES}
    out = blend(measured, lobith_meting, rws, recession, DATES[:3], blend_days=0)
    assert out == [111.0, 112.0, 130.0]


def test_blend_gebruikt_lobith_meting_om_het_westervoort_gat_te_vullen():
    """Westervoort loopt (in de praktijk tot ~2 weken) achter; Lobith-meting
    (geschaald) vult het gat tot en met vandaag."""
    dates = DATES
    measured = {"2026-09-01": 100.0, "2026-09-02": 101.0}  # meting stopt vroeg
    lobith_meting = {d: 120.0 for d in dates[2:]}  # geschaalde Lobith-meting vult de rest
    rws = {}
    recession = {d: 50.0 for d in dates}
    out = blend(measured, lobith_meting, rws, recession, dates, blend_days=0)
    assert out[:2] == [100.0, 101.0]
    assert out[2:] == [120.0] * 8


def test_lobith_ratio_is_de_mediane_verhouding():
    lob = {"2026-09-01": 900.0, "2026-09-02": 1000.0, "2026-09-03": 800.0}
    wes = {"2026-09-01": 90.0, "2026-09-02": 100.0, "2026-09-03": 80.0}
    # min_overlap expliciet: de standaard is 20 dagen, deze reeks heeft er 3
    assert lobith_ratio(lob, wes, min_overlap=3) == pytest.approx(0.1)


def test_lobith_ratio_eist_standaard_twintig_dagen_overlap():
    """Drie toevallig kloppende dagen mogen geen schaalfactor rechtvaardigen."""
    lob = {"2026-09-01": 900.0, "2026-09-02": 1000.0, "2026-09-03": 800.0}
    wes = {"2026-09-01": 90.0, "2026-09-02": 100.0, "2026-09-03": 80.0}
    assert lobith_ratio(lob, wes) is None


def test_lobith_ratio_negeert_dagen_zonder_paar():
    lob = {"2026-09-01": 900.0, "2026-09-02": 1000.0}
    wes = {"2026-09-01": 90.0, "2026-09-09": 500.0}
    assert lobith_ratio(lob, wes, min_overlap=1) == pytest.approx(0.1)


def test_lobith_ratio_geeft_none_bij_te_weinig_overlap():
    assert lobith_ratio({"2026-09-01": 900.0}, {"2026-09-02": 90.0}) is None


def test_lobith_ratio_negeert_nul_en_negatieve_afvoer():
    lob = {"a": 0.0, "b": 1000.0, "c": -5.0}
    wes = {"a": 50.0, "b": 100.0, "c": 10.0}
    assert lobith_ratio(lob, wes, min_overlap=1) == pytest.approx(0.1)


def test_lobith_ratio_volgt_het_actuele_regime_binnen_het_venster():
    """Oude data met een andere verhouding mag de recente (venster-)ratio niet verdunnen."""
    today = datetime.date(2026, 9, 8)
    lob, wes = {}, {}
    # 25 recente dagen (binnen het venster van 90 dagen) met ratio 0.15 (huidig, lage afvoer)
    for i in range(0, 25):
        d = (today - datetime.timedelta(days=i)).isoformat()
        lob[d], wes[d] = 1000.0, 150.0
    # 30 oude dagen (ver buiten het venster) met een andere ratio 0.20
    for i in range(200, 230):
        d = (today - datetime.timedelta(days=i)).isoformat()
        lob[d], wes[d] = 1000.0, 200.0
    ratio = lobith_ratio(lob, wes, min_overlap=20)
    assert ratio == pytest.approx(0.15)


def test_lobith_ratio_valt_terug_op_volledige_historie_bij_te_weinig_recente_overlap():
    """Minder dan min_overlap dagen binnen het venster -> terugval op de volledige reeks."""
    today = datetime.date(2026, 9, 8)
    lob, wes = {}, {}
    # slechts 5 dagen binnen het venster van 90 dagen (te weinig voor min_overlap=20)
    for i in range(0, 5):
        d = (today - datetime.timedelta(days=i)).isoformat()
        lob[d], wes[d] = 1000.0, 150.0  # ratio 0.15
    # 25 oudere dagen (buiten het venster) met een andere ratio
    for i in range(200, 225):
        d = (today - datetime.timedelta(days=i)).isoformat()
        lob[d], wes[d] = 1000.0, 100.0  # ratio 0.10
    ratio = lobith_ratio(lob, wes, min_overlap=20)
    # binnen het venster is er te weinig overlap (5 < 20); de terugval gebruikt de
    # volledige 30-daagse reeks, waarvan de mediaan bij de 25 oudere dagen (0.10) ligt
    assert ratio == pytest.approx(0.10)
