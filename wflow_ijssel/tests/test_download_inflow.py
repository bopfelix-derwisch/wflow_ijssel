import numpy as np
import pandas as pd
import pytest

from download_inflow import parse_rws_response, inflow_to_netcdf


def test_parse_rws_response_returns_series():
    """parse_rws_response geeft een pd.Series terug met DatetimeIndex."""
    fake_response = {
        "WaarnemingenLijst": [{
            "MetingenLijst": [
                {"Tijdstip": "1995-01-15T00:00:00.000+01:00", "Meetwaarde": {"Waarde_Numeriek": 2100.0}},
                {"Tijdstip": "1995-01-16T00:00:00.000+01:00", "Meetwaarde": {"Waarde_Numeriek": 2800.0}},
                {"Tijdstip": "1995-01-17T00:00:00.000+01:00", "Meetwaarde": {"Waarde_Numeriek": 3100.0}},
            ]
        }]
    }
    result = parse_rws_response(fake_response)
    assert isinstance(result, pd.Series)
    assert len(result) == 3
    assert result.iloc[1] == pytest.approx(2800.0)
    assert result.index.dtype == "datetime64[ns]"


def test_inflow_to_netcdf_shape(tmp_path):
    """inflow_to_netcdf schrijft een NetCDF met de juiste dimensies."""
    import xarray as xr

    dates = pd.date_range("1994-12-01", "1995-01-31", freq="D")
    discharge = pd.Series(np.random.uniform(500, 3000, len(dates)), index=dates)
    out = tmp_path / "inflow.nc"

    inflow_to_netcdf(discharge, x_idx=42, y_idx=18, shape=(50, 60), out_path=out)

    ds = xr.open_dataset(out)
    assert "inflow" in ds
    assert ds["inflow"].dims == ("time", "y", "x")
    assert ds.dims["time"] == len(dates)
    assert float(ds["inflow"].isel(time=0, y=18, x=42)) > 0
    assert float(ds["inflow"].isel(time=0, y=0, x=0)) == pytest.approx(0.0)
