import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from export_output import (
    extract_timeseries,
    build_river_geojson_day,
    compute_kpis,
)


@pytest.fixture
def mock_output(tmp_path) -> xr.Dataset:
    """Minimale nep-output die de echte Wflow output nabootst."""
    times = [np.datetime64(f"1995-01-{d:02d}") for d in range(1, 6)]
    ny, nx = 10, 12
    q = np.random.uniform(500, 3000, (len(times), ny, nx)).astype(np.float32)
    h = (q / 800).astype(np.float32)
    lon = np.linspace(5.5, 7.5, nx)
    lat = np.linspace(52.8, 51.5, ny)

    ds = xr.Dataset(
        {
            "q_river": (["time", "y", "x"], q),
            "h_river": (["time", "y", "x"], h),
        },
        coords={"time": times, "lon": (["x"], lon), "lat": (["y"], lat)},
    )
    path = tmp_path / "output_ijssel.nc"
    ds.to_netcdf(path)
    return ds


def test_extract_timeseries_has_required_keys(mock_output):
    result = extract_timeseries(mock_output, lon=6.1, lat=52.5)
    assert "dates" in result
    assert "q" in result
    assert "h_nap" in result
    assert len(result["dates"]) == 5
    assert all(isinstance(d, str) for d in result["dates"])


def test_build_river_geojson_day_valid_geojson(mock_output):
    river_mask = np.zeros((10, 12), dtype=bool)
    river_mask[5, 6] = True
    river_mask[5, 7] = True
    result = build_river_geojson_day(mock_output, day_idx=0, river_mask=river_mask)
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 2
    feat = result["features"][0]
    assert feat["geometry"]["type"] == "Point"
    assert "q" in feat["properties"]
    assert "h" in feat["properties"]


def test_compute_kpis(mock_output):
    kpis = compute_kpis(mock_output, lon=6.1, lat=52.5, threshold=1500.0)
    assert "peak_q" in kpis
    assert "peak_date" in kpis
    assert "days_above_threshold" in kpis
    assert isinstance(kpis["peak_q"], float)
    assert kpis["peak_q"] > 0
