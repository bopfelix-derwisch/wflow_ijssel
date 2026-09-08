"""Forcing-NetCDF voor de operationele nowcast (fase C)."""
import numpy as np
import pytest
import xarray as xr

from wflow_ijssel.operational.forcing import westervoort_cell, write_forcing
from wflow_ijssel.operational.meteo import MODEL_X, MODEL_Y


def _velden(n_dagen):
    vorm = (n_dagen, len(MODEL_Y), len(MODEL_X))
    return (np.full(vorm, 2.0), np.full(vorm, 0.5), np.full(vorm, 8.0))


def test_westervoort_cel_ligt_in_het_grid():
    rij, kol = westervoort_cell(MODEL_Y, MODEL_X)
    assert 0 <= rij < len(MODEL_Y)
    assert 0 <= kol < len(MODEL_X)
    # 6.154 O, 51.987 N — zuidoostelijke hoek van het domein
    assert MODEL_Y[rij] == pytest.approx(51.987, abs=0.01)
    assert MODEL_X[kol] == pytest.approx(6.154, abs=0.01)


def test_write_forcing_schrijft_het_verwachte_schema(tmp_path):
    dates = ["2026-09-01", "2026-09-02", "2026-09-03"]
    precip, pet, temp = _velden(3)
    pad = write_forcing(tmp_path / "f.nc", dates, precip, pet, temp, [100.0, 110.0, 120.0])

    with xr.open_dataset(pad) as ds:
        assert set(ds.data_vars) == {"precip", "temp", "pet", "inflow"}
        assert ds["precip"].dims == ("time", "y", "x")
        assert ds.sizes == {"time": 3, "y": 240, "x": 300}
        # y moet AFLOPEND zijn — anders spiegelt het stroomgebied stilzwijgend
        assert ds.y.values[0] > ds.y.values[-1]
        assert ds.x.values[0] < ds.x.values[-1]
        np.testing.assert_allclose(ds.x.values, MODEL_X)
        np.testing.assert_allclose(ds.y.values, MODEL_Y)
        assert str(ds.time.dtype).startswith("datetime64")


def test_write_forcing_zet_inflow_alleen_in_de_westervoort_cel(tmp_path):
    dates = ["2026-09-01", "2026-09-02"]
    precip, pet, temp = _velden(2)
    pad = write_forcing(tmp_path / "f.nc", dates, precip, pet, temp, [300.0, 400.0])

    rij, kol = westervoort_cell(MODEL_Y, MODEL_X)
    with xr.open_dataset(pad) as ds:
        inflow = ds["inflow"].values
        assert inflow[0, rij, kol] == pytest.approx(300.0)
        assert inflow[1, rij, kol] == pytest.approx(400.0)
        # alle overige cellen nul
        inflow[:, rij, kol] = 0.0
        assert np.count_nonzero(inflow) == 0


def test_write_forcing_verwerpt_een_verkeerde_inflow_lengte(tmp_path):
    precip, pet, temp = _velden(3)
    with pytest.raises(ValueError):
        write_forcing(tmp_path / "f.nc", ["2026-09-01", "2026-09-02", "2026-09-03"],
                      precip, pet, temp, [100.0])


def test_write_forcing_verwerpt_een_verkeerde_veldvorm(tmp_path):
    precip, pet, temp = _velden(3)
    with pytest.raises(ValueError):
        write_forcing(tmp_path / "f.nc", ["2026-09-01"], precip, pet, temp, [100.0])
