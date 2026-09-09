"""Meteo-ophalen en regridden voor de operationele nowcast (fase C)."""
import numpy as np
import pytest

from wflow_ijssel.operational.meteo import (
    MODEL_X, MODEL_Y, grid_points, to_model_grid,
)


def test_modelgrid_heeft_de_exacte_vorm_en_richting():
    assert len(MODEL_X) == 300
    assert len(MODEL_Y) == 240
    assert MODEL_X[0] == pytest.approx(5.004166666666666)
    assert MODEL_X[-1] == pytest.approx(7.495833333333334)
    # y loopt AFLOPEND (noord -> zuid); een oplopende as spiegelt het stroomgebied
    assert MODEL_Y[0] == pytest.approx(53.49583333333333)
    assert MODEL_Y[-1] == pytest.approx(51.50416666666667)
    assert np.all(np.diff(MODEL_Y) < 0)
    assert np.all(np.diff(MODEL_X) > 0)


def test_grid_points_dekt_het_modelgrid():
    lats, lons = grid_points(step=0.25)
    assert len(lats) == len(lons)
    assert len(lats) > 50
    # het bevragingsraster moet het modelgrid omsluiten, anders extrapoleren we
    assert min(lats) <= MODEL_Y.min()
    assert max(lats) >= MODEL_Y.max()
    assert min(lons) <= MODEL_X.min()
    assert max(lons) >= MODEL_X.max()


def test_to_model_grid_reproduceert_een_constant_veld():
    lats = [la for la in (51.0, 52.0, 53.0, 54.0) for _ in range(4)]
    lons = [lo for _ in range(4) for lo in (5.0, 6.0, 7.0, 8.0)]
    values = np.full((16, 2), 3.5)          # 16 punten, 2 dagen
    out = to_model_grid(values, lats, lons, MODEL_Y, MODEL_X)
    assert out.shape == (2, 240, 300)
    assert np.allclose(out, 3.5)


def test_to_model_grid_interpoleert_een_lineaire_helling():
    """Veld dat lineair met de lengtegraad oploopt moet lineair blijven."""
    lats = [la for la in (51.0, 52.0, 53.0, 54.0) for _ in range(4)]
    lons = [lo for _ in range(4) for lo in (5.0, 6.0, 7.0, 8.0)]
    values = np.array([[lo] for lo in lons], dtype=float)   # 16 punten, 1 dag
    out = to_model_grid(values, lats, lons, MODEL_Y, MODEL_X)
    assert out.shape == (1, 240, 300)
    # elke rij moet de x-as volgen
    np.testing.assert_allclose(out[0, 0, :], MODEL_X, atol=1e-6)
    np.testing.assert_allclose(out[0, -1, :], MODEL_X, atol=1e-6)


def test_to_model_grid_verwerpt_verkeerde_vorm():
    lats = [51.0, 52.0]
    lons = [5.0, 6.0]
    with pytest.raises(ValueError):
        to_model_grid(np.zeros((3, 2)), lats, lons, MODEL_Y, MODEL_X)


def test_to_model_grid_verwerpt_dubbele_coordinaat_met_ontbrekende_cel():
    """Regressietest (code review): het aantal punten klopt met een 2x2-raster,
    maar (1,1) komt tweemaal voor en (1,2) ontbreekt nooit. De oude check op
    alleen aantallen liet dit door, waarna de niet-ingevulde cel in `field`
    ongeïnitialiseerd geheugen bevatte — geen fout, gewoon stille rommel."""
    lats = [1.0, 1.0, 2.0, 2.0]
    lons = [1.0, 1.0, 1.0, 2.0]
    values = np.zeros((4, 1))
    with pytest.raises(ValueError):
        to_model_grid(values, lats, lons, MODEL_Y, MODEL_X)


def test_fetch_daily_leest_een_lijstrespons(monkeypatch):
    """Open-Meteo geeft bij meerdere punten een LIJST terug, bij één punt een object."""
    from wflow_ijssel.operational import meteo

    nep = [
        {"latitude": 52.0, "longitude": 6.0, "daily": {
            "time": ["2026-01-01", "2026-01-02"],
            "precipitation_sum": [1.0, 2.0],
            "et0_fao_evapotranspiration": [0.5, 0.6],
            "temperature_2m_mean": [4.0, 5.0]}},
        {"latitude": 52.0, "longitude": 6.25, "daily": {
            "time": ["2026-01-01", "2026-01-02"],
            "precipitation_sum": [3.0, 4.0],
            "et0_fao_evapotranspiration": [0.7, 0.8],
            "temperature_2m_mean": [6.0, 7.0]}},
    ]
    monkeypatch.setattr(meteo, "_get_json", lambda url, params: nep)

    out = meteo.fetch_daily([52.0, 52.0], [6.0, 6.25], "2026-01-01", "2026-01-02")
    assert out["dates"] == ["2026-01-01", "2026-01-02"]
    assert out["precip"].shape == (2, 2)
    np.testing.assert_allclose(out["precip"][:, 0], [1.0, 3.0])
    np.testing.assert_allclose(out["temp"][:, 1], [5.0, 7.0])


def test_fetch_daily_vult_ontbrekende_waarden_met_nul(monkeypatch):
    """Open-Meteo levert soms null; neerslag/verdamping mogen geen NaN de forcing in."""
    from wflow_ijssel.operational import meteo

    nep = {"latitude": 52.0, "longitude": 6.0, "daily": {
        "time": ["2026-01-01"], "precipitation_sum": [None],
        "et0_fao_evapotranspiration": [None], "temperature_2m_mean": [None]}}
    monkeypatch.setattr(meteo, "_get_json", lambda url, params: nep)

    out = meteo.fetch_daily([52.0], [6.0], "2026-01-01", "2026-01-01")
    assert out["precip"][0, 0] == 0.0
    assert out["pet"][0, 0] == 0.0
    assert out["temp"][0, 0] == 0.0


def test_fetch_daily_herstelt_een_verwisselde_respons_volgorde(monkeypatch):
    """Een omgedraaide respons wordt op coördinaat teruggekoppeld, niet afgekeurd.

    Eerder gooide dit een ValueError. Dat is bij taak 4 herzien: de archief-API
    snapt tot 0,131° — méér dan de halve bevragingsstap — zodat een pure
    afstandstoets daar "gesnapt" niet van "verwisseld" kan onderscheiden. Sinds
    die herziening leiden we de volgorde af uit de meegestuurde coördinaten en
    eisen we een bijectie. Een verwisseling wordt dus hersteld in plaats van
    alleen gemeld, wat strikt beter is: de waarden komen bij het juiste punt.
    """
    from wflow_ijssel.operational import meteo

    # opgevraagd: (52.0, 6.0) dan (53.0, 7.0); respons komt omgedraaid terug
    nep = [
        {"latitude": 53.0, "longitude": 7.0, "daily": {
            "time": ["2026-01-01"],
            "precipitation_sum": [3.0],
            "et0_fao_evapotranspiration": [0.7],
            "temperature_2m_mean": [6.0]}},
        {"latitude": 52.0, "longitude": 6.0, "daily": {
            "time": ["2026-01-01"],
            "precipitation_sum": [1.0],
            "et0_fao_evapotranspiration": [0.5],
            "temperature_2m_mean": [4.0]}},
    ]
    monkeypatch.setattr(meteo, "_get_json", lambda url, params: nep)

    out = meteo.fetch_daily([52.0, 53.0], [6.0, 7.0], "2026-01-01", "2026-01-01")
    # punt 0 is (52.0, 6.0) en hoort dus 1.0 te krijgen, niet 3.0
    np.testing.assert_allclose(out["precip"][:, 0], [1.0, 3.0])
    np.testing.assert_allclose(out["temp"][:, 0], [4.0, 6.0])


def test_fetch_daily_verwerpt_een_respons_die_nergens_bij_hoort(monkeypatch):
    """Een object dat van élk opgevraagd punt te ver ligt, is geen snap maar een
    fout — dan moet het luid falen in plaats van bij het minst slechte punt te
    worden ingedeeld."""
    from wflow_ijssel.operational import meteo

    nep = [
        {"latitude": 48.0, "longitude": 2.0, "daily": {
            "time": ["2026-01-01"], "precipitation_sum": [1.0],
            "et0_fao_evapotranspiration": [0.5], "temperature_2m_mean": [4.0]}},
    ]
    monkeypatch.setattr(meteo, "_get_json", lambda url, params: nep)

    with pytest.raises(ValueError, match="tolerantie"):
        meteo.fetch_daily([52.0], [6.0], "2026-01-01", "2026-01-01")


def test_fetch_daily_staat_een_grover_bronrooster_toe(monkeypatch):
    """Twee opgevraagde punten mogen op dezelfde bron-cel uitkomen.

    Het archiefrooster is grover dan ons bevragingsraster van 0,25°, dus dat
    gebeurt in de praktijk (gemeten bij de spin-up: opgevraagde punten 57 en 58
    kwamen allebei op 52,75/5,75 uit). Dat is de resolutie van de bron, geen
    fout — beide punten krijgen dan dezelfde waarde.
    """
    from wflow_ijssel.operational import meteo

    nep = [
        {"latitude": 52.0, "longitude": 6.0, "daily": {
            "time": ["2026-01-01"], "precipitation_sum": [1.0],
            "et0_fao_evapotranspiration": [0.5], "temperature_2m_mean": [4.0]}},
        {"latitude": 52.0, "longitude": 6.0, "daily": {
            "time": ["2026-01-01"], "precipitation_sum": [1.0],
            "et0_fao_evapotranspiration": [0.5], "temperature_2m_mean": [4.0]}},
    ]
    monkeypatch.setattr(meteo, "_get_json", lambda url, params: nep)

    out = meteo.fetch_daily([52.0, 52.05], [6.0, 6.05], "2026-01-01", "2026-01-01",
                            archive=True)
    np.testing.assert_allclose(out["precip"][:, 0], [1.0, 1.0])


def test_fetch_daily_herstelt_een_verwisseling_met_een_aangrenzend_punt(monkeypatch):
    """Ook een verwisseling met het DICHTSTBIJZIJNDE buurpunt komt goed terecht.

    Dit was eerder de zwaarste eis aan de afstandstoets: diagonale buren liggen
    op het bevragingsraster maar 0,25° uit elkaar. Sinds we op coördinaat
    koppelen in plaats van op volgorde is de afstand tot het eigen punt (0)
    altijd kleiner dan die tot de buur (0,354), dus komt elke waarde bij het
    juiste punt terecht — ongeacht hoe grof de bron snapt.
    """
    from wflow_ijssel.operational import meteo

    # opgevraagd: (52.0, 6.0) dan (52.25, 6.25) — diagonale buren op het
    # bevragingsraster (grid_points met step=0.25); respons komt omgedraaid terug
    nep = [
        {"latitude": 52.25, "longitude": 6.25, "daily": {
            "time": ["2026-01-01"],
            "precipitation_sum": [3.0],
            "et0_fao_evapotranspiration": [0.7],
            "temperature_2m_mean": [6.0]}},
        {"latitude": 52.0, "longitude": 6.0, "daily": {
            "time": ["2026-01-01"],
            "precipitation_sum": [1.0],
            "et0_fao_evapotranspiration": [0.5],
            "temperature_2m_mean": [4.0]}},
    ]
    monkeypatch.setattr(meteo, "_get_json", lambda url, params: nep)

    out = meteo.fetch_daily([52.0, 52.25], [6.0, 6.25], "2026-01-01", "2026-01-01")
    np.testing.assert_allclose(out["precip"][:, 0], [1.0, 3.0])


def test_fetch_daily_accepteert_kleine_snap_naar_roosterpunt_afwijking(monkeypatch):
    """Een kleine afwijking (hier 0,05°) zoals Open-Meteo's snap naar zijn eigen
    roosterpunt is legitiem en mag geen ValueError geven — anders slaat de
    volgorde-toets te ver door de andere kant op."""
    from wflow_ijssel.operational import meteo

    nep = {"latitude": 52.05, "longitude": 6.0, "daily": {
        "time": ["2026-01-01"], "precipitation_sum": [1.0],
        "et0_fao_evapotranspiration": [0.5], "temperature_2m_mean": [4.0]}}
    monkeypatch.setattr(meteo, "_get_json", lambda url, params: nep)

    out = meteo.fetch_daily([52.0], [6.0], "2026-01-01", "2026-01-01")
    assert out["precip"][0, 0] == 1.0
