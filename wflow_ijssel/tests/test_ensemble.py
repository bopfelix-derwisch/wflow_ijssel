"""Unit tests voor ensemble-modules: output_collector, analysis_engine, llm_agent."""
from __future__ import annotations
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_nc(tmp_path: Path, q_values: list[float], h_values: list[float],
             filename: str = "output.nc") -> Path:
    """Maak minimale NetCDF met lon/lat dims, net als echte Wflow output."""
    times = [np.datetime64(f"2024-01-{d:02d}") for d in range(1, len(q_values) + 1)]
    ny, nx = 3, 4
    # Vul spatial grid; station op (xi=1, yi=2) -> lon=6.1, lat=52.4
    lons = np.array([5.9, 6.1, 6.3, 6.5])
    lats = np.array([52.2, 52.4, 52.6])
    # Station lon=6.1 -> lon_idx=1; station lat=52.4 -> lat_idx=1

    q_grid = np.zeros((len(times), ny, nx), dtype=np.float32)
    h_grid = np.zeros((len(times), ny, nx), dtype=np.float32)
    for t_idx, (qv, hv) in enumerate(zip(q_values, h_values)):
        q_grid[t_idx, :, :] = 100.0
        q_grid[t_idx, 1, 1] = qv   # station pixel: lat_idx=1, lon_idx=1
        h_grid[t_idx, 1, 1] = hv

    ds = xr.Dataset(
        {
            "q_river": (["time", "lat", "lon"], q_grid),
            "h_river": (["time", "lat", "lon"], h_grid),
        },
        coords={"time": times, "lon": lons, "lat": lats},
    )
    path = tmp_path / filename
    ds.to_netcdf(str(path))
    return path


# ---------------------------------------------------------------------------
# output_collector tests
# ---------------------------------------------------------------------------

import sys, os
sys.path.insert(0, str(Path(__file__).parent.parent / "ensemble"))

from output_collector import collect


STATION_LON = 6.1
STATION_LAT = 52.4
THRESHOLD   = 1500.0

Q_VALUES = [1200.0, 1800.0, 2100.0, 900.0, 1600.0]
H_VALUES = [1.5,    2.2,    2.6,    1.1,   2.0]


def test_collect_required_keys(tmp_path):
    nc = _make_nc(tmp_path, Q_VALUES, H_VALUES)
    result = collect(nc, STATION_LON, STATION_LAT, THRESHOLD, delete_nc=False)
    for key in ("dates", "q", "h", "peak_q", "peak_date", "days_above_threshold"):
        assert key in result, f"Ontbrekende sleutel: {key}"


def test_collect_dates_length(tmp_path):
    nc = _make_nc(tmp_path, Q_VALUES, H_VALUES)
    result = collect(nc, STATION_LON, STATION_LAT, THRESHOLD, delete_nc=False)
    assert len(result["dates"]) == len(Q_VALUES)
    assert all(isinstance(d, str) for d in result["dates"])


def test_collect_peak_q_correct(tmp_path):
    nc = _make_nc(tmp_path, Q_VALUES, H_VALUES)
    result = collect(nc, STATION_LON, STATION_LAT, THRESHOLD, delete_nc=False)
    assert result["peak_q"] == pytest.approx(2100.0, abs=0.2)


def test_collect_peak_date_correct(tmp_path):
    nc = _make_nc(tmp_path, Q_VALUES, H_VALUES)
    result = collect(nc, STATION_LON, STATION_LAT, THRESHOLD, delete_nc=False)
    # Peak is at index 2 -> 2024-01-03
    assert result["peak_date"] == "2024-01-03"


def test_collect_days_above_threshold(tmp_path):
    nc = _make_nc(tmp_path, Q_VALUES, H_VALUES)
    result = collect(nc, STATION_LON, STATION_LAT, THRESHOLD, delete_nc=False)
    # Q_VALUES > 1500: 1800, 2100, 1600 -> 3 days
    assert result["days_above_threshold"] == 3


def test_collect_delete_nc(tmp_path):
    nc = _make_nc(tmp_path, Q_VALUES, H_VALUES)
    assert nc.exists()
    collect(nc, STATION_LON, STATION_LAT, THRESHOLD, delete_nc=True)
    assert not nc.exists()


def test_collect_no_delete_nc(tmp_path):
    nc = _make_nc(tmp_path, Q_VALUES, H_VALUES)
    collect(nc, STATION_LON, STATION_LAT, THRESHOLD, delete_nc=False)
    assert nc.exists()


# ---------------------------------------------------------------------------
# analysis_engine tests
# ---------------------------------------------------------------------------

from analysis_engine import compute_ensemble_stats


def _make_results(scenario_data: dict) -> list[dict]:
    """Bouw een lijst van collect()-achtige dicts voor compute_ensemble_stats."""
    results = []
    for name, q_vals in scenario_data.items():
        q_arr = np.array(q_vals, dtype=float)
        peak_idx = int(np.argmax(q_arr))
        dates = [f"2024-01-{d+1:02d}" for d in range(len(q_vals))]
        results.append({
            "name":                 name,
            "dates":                dates,
            "q":                    [round(float(v), 2) for v in q_vals],
            "h":                    [round(float(v) / 1000, 3) for v in q_vals],
            "peak_q":               round(float(q_arr[peak_idx]), 1),
            "peak_date":            dates[peak_idx],
            "days_above_threshold": int(np.sum(q_arr > THRESHOLD)),
        })
    return results


SCENARIO_DATA = {
    "droog":    [800.0,  1000.0, 1200.0],
    "gemiddeld":[1200.0, 1800.0, 2000.0],
    "nat":      [1600.0, 2400.0, 3000.0],
}


def test_stats_required_keys():
    results = _make_results(SCENARIO_DATA)
    stats = compute_ensemble_stats(results)
    for key in ("q_mean", "q_p10", "q_p90", "hotspot_date", "peak_per_scenario"):
        assert key in stats, f"Ontbrekende sleutel: {key}"


def test_stats_q_mean_first_value():
    results = _make_results(SCENARIO_DATA)
    stats = compute_ensemble_stats(results)
    # Kolom 0: [800, 1200, 1600] -> mean = 1200.0
    expected_mean = (800.0 + 1200.0 + 1600.0) / 3
    assert stats["q_mean"][0] == pytest.approx(expected_mean, abs=0.2)


def test_stats_p10_le_p90():
    results = _make_results(SCENARIO_DATA)
    stats = compute_ensemble_stats(results)
    for p10, p90 in zip(stats["q_p10"], stats["q_p90"]):
        assert p10 <= p90, f"p10 ({p10}) > p90 ({p90})"


def test_stats_peak_per_scenario_keys():
    results = _make_results(SCENARIO_DATA)
    stats = compute_ensemble_stats(results)
    assert set(stats["peak_per_scenario"].keys()) == set(SCENARIO_DATA.keys())


def test_stats_hotspot_date_in_dates():
    results = _make_results(SCENARIO_DATA)
    stats = compute_ensemble_stats(results)
    assert stats["hotspot_date"] in stats["dates"]


def test_stats_scenario_names():
    results = _make_results(SCENARIO_DATA)
    stats = compute_ensemble_stats(results)
    assert set(stats["scenario_names"]) == set(SCENARIO_DATA.keys())


# ---------------------------------------------------------------------------
# llm_agent tests  (geen echte LLM-aanroep)
# ---------------------------------------------------------------------------

from llm_agent import build_user_message


def _make_stats() -> dict:
    results = _make_results(SCENARIO_DATA)
    return compute_ensemble_stats(results)


def test_build_user_message_contains_scenario_names():
    stats = _make_stats()
    msg = build_user_message(stats, threshold=THRESHOLD)
    for name in SCENARIO_DATA:
        assert name in msg, f"Scenario '{name}' ontbreekt in bericht"


def test_build_user_message_contains_threshold():
    stats = _make_stats()
    msg = build_user_message(stats, threshold=THRESHOLD)
    assert str(int(THRESHOLD)) in msg or str(THRESHOLD) in msg


def test_build_user_message_is_string():
    stats = _make_stats()
    msg = build_user_message(stats, threshold=THRESHOLD)
    assert isinstance(msg, str)
    assert len(msg) > 20
