"""WL-VAL-1 — skill-metrieken (NSE, KGE, bias) en uitlijning sim/meting."""
import pytest

from dashboard.validation import (
    nse, kge, bias, pbias, rmse, pearson_r, skill_scores, align, horizon_skill,
)


def test_perfect_match():
    s = o = [1.0, 2.0, 3.0, 4.0]
    assert nse(s, o) == pytest.approx(1.0)
    assert kge(s, o) == pytest.approx(1.0)
    assert pearson_r(s, o) == pytest.approx(1.0)
    assert bias(s, o) == pytest.approx(0.0)
    assert pbias(s, o) == pytest.approx(0.0)
    assert rmse(s, o) == pytest.approx(0.0)


def test_pearson_captures_pattern_despite_amplitude_and_offset():
    # zelfde vorm, andere amplitude + offset → r≈1 maar NSE slecht
    o = [1.0, 2.0, 3.0, 4.0, 5.0]
    s = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert pearson_r(s, o) == pytest.approx(1.0)
    assert nse(s, o) < 0


def test_mean_predictor_gives_nse_zero():
    o = [1.0, 2.0, 3.0, 4.0]
    s = [2.5, 2.5, 2.5, 2.5]
    assert nse(s, o) == pytest.approx(0.0)


def test_known_imperfect_case():
    s = [1.0, 2.0, 3.0, 5.0]
    o = [1.0, 2.0, 3.0, 4.0]
    assert nse(s, o) == pytest.approx(0.8)
    assert bias(s, o) == pytest.approx(0.25)
    assert pbias(s, o) == pytest.approx(10.0)
    assert rmse(s, o) == pytest.approx(0.5)


def test_align_drops_nonoverlapping_and_null():
    sim_dates = ["2021-01-01", "2021-01-02", "2021-01-03", "2021-01-04"]
    sim_vals = [10.0, 20.0, 30.0, 40.0]
    obs_dates = ["2021-01-02", "2021-01-03", "2021-01-04", "2021-01-05"]
    obs_vals = [21.0, None, 39.0, 50.0]
    dates, s, o = align(sim_dates, sim_vals, obs_dates, obs_vals)
    # 01-01 + 01-05 geen overlap; 01-03 obs is None → weg
    assert dates == ["2021-01-02", "2021-01-04"]
    assert s == [20.0, 40.0]
    assert o == [21.0, 39.0]


def test_skill_scores_shape_and_nan_to_none():
    sc = skill_scores([1.0], [1.0])  # n<2 → NSE/KGE/r niet definieerbaar → None
    assert sc["n"] == 1
    assert set(sc) == {"n", "r", "nse", "kge", "bias", "pbias", "rmse"}
    assert sc["nse"] is None
    assert sc["r"] is None


def test_horizon_skill_aggregates_per_leadtime():
    preds = [[10.0, 10.0], [20.0, 20.0]]
    obs   = [[12.0,  8.0], [18.0, 25.0]]
    lows  = [[ 8.0,  8.0], [15.0, 15.0]]
    highs = [[12.0, 12.0], [25.0, 25.0]]
    r = horizon_skill(preds, obs, lows, highs)
    assert r["horizon"] == [1, 2]
    assert r["bias"] == [0.0, -1.5]          # (−2,+2)→0 ; (+2,−5)→−1.5
    assert r["mae"] == [2.0, 3.5]
    assert r["rmse"] == [2.0, 3.8]           # sqrt(14.5)≈3.81
    assert r["coverage"] == [100, 100]       # alle realisaties binnen band
    assert r["n"] == [2, 2]
