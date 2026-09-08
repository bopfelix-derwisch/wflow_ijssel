"""POC E — ensemble-assimilatie op het recessiemodel."""
import numpy as np
import pandas as pd

from dashboard import assimilation as assimilation_mod, forecast
from dashboard.assimilation import recession_traj, ensemble_assimilate, build_assimilation
from dashboard.forecast import _recession


def _rmse(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.sqrt(np.mean((a - b) ** 2)))


def test_recession_matches_forecast_formula():
    # recession_traj met doel = seizoensgemiddelde(juli)=240 moet exact forecast._recession evenaren
    y = recession_traj(1000.0, 5, tau=10.0, target=240.0)
    assert np.allclose(y, _recession(1000.0, 5, month=7, tau=10.0))


def test_assimilation_reduces_error_on_overshoot_case():
    """De echte afvoer zakt sneller (tau=5) dan de prior (tau0=10) → de vrije verwachting
    overschat. Na assimilatie van het recente verloop moet de forecast dichter bij de ware
    voortzetting liggen."""
    tau_true, target_true, anchor = 5.0, 200.0, 1000.0
    M, horizon = 10, 14
    # recente meting: ware snelle recessie vanaf 'anchor', met wat ruis
    rng = np.random.default_rng(1)
    obs = recession_traj(anchor, M, tau_true, target_true) + rng.normal(0, 4, M)
    q0 = float(obs[-1])
    truth = recession_traj(q0, horizon, tau_true, target_true)

    res = ensemble_assimilate(anchor=anchor, obs=obs, q0=q0, horizon=horizon,
                              tau0=10.0, target0=target_true, N=80, seed=0)

    rmse_free  = _rmse(res["free"], truth)
    rmse_assim = _rmse(res["mean"], truth)
    assert rmse_assim < rmse_free                 # assimilatie verbetert
    assert res["tau_post"] < res["tau_prior"]     # posterior herkent de snellere decay
    # band moet de waarheid grotendeels omvatten
    inside = np.mean((truth >= res["p10"]) & (truth <= res["p90"]))
    assert inside >= 0.5


def test_assimilate_output_shape():
    obs = recession_traj(800.0, 8, 7.0, 220.0)
    res = ensemble_assimilate(anchor=800.0, obs=obs, q0=float(obs[-1]), horizon=14,
                              tau0=10.0, target0=240.0, N=50, seed=3)
    for k in ("free", "mean", "p10", "p90"):
        assert len(res[k]) == 14
    assert np.all(np.asarray(res["p90"]) >= np.asarray(res["p10"]))


def _leeg_series_cache():
    # _fetch_series cachet op (t, days, data); zonder resetten ziet een volgende
    # test een "warme" cache staan van een vorige run in dit proces.
    assimilation_mod._SERIES_CACHE.update(t=0.0, days=-1, data=None)


def test_fetch_series_te_kort_geeft_none(monkeypatch):
    """Sinds de rws_client-refactor telt len(s) op de dropna'd reeks het aantal
    dagen mét echte meting, niet het aantal kalenderdagen in het venster (zie
    rws_client.daily_series). Een kortere-dan-drempel reeks (zoals na een
    meerdaagse RWS-gap) moet _fetch_series netjes None laten teruggeven i.p.v.
    een te korte/gevulde reeks door te laten sluipen.

    _fetch_series haalt _rws_daily op via een lokale 'from dashboard.forecast
    import _rws_daily' — patchen moet dus op dashboard.forecast, niet op
    dashboard.assimilation (dat heeft geen eigen referentie naar de functie)."""
    _leeg_series_cache()

    te_kort = pd.Series(
        [100.0] * 10, index=pd.date_range("2026-01-01", periods=10, freq="D"))
    monkeypatch.setattr(forecast, "_rws_daily", lambda *a, **k: te_kort)

    assert assimilation_mod._fetch_series(80) is None


def test_build_assimilation_bij_rws_gap_geeft_nette_unavailable(monkeypatch):
    """Faalscenario uit de review: een RWS-outage van meerdere dagen bij
    Westervoort levert (via _fetch_series -> None) geen crash op, maar een
    leesbare 'available: False' met reden."""
    _leeg_series_cache()
    assimilation_mod._CACHE.update(t=0.0, data=None)

    monkeypatch.setattr(forecast, "_rws_daily", lambda *a, **k: None)

    out = build_assimilation(days_back=80, force=True)

    assert out["available"] is False
    assert isinstance(out["reason"], str) and out["reason"]
