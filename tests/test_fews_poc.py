import json
import pytest
from pathlib import Path
from fews_poc.pi_types import (
    PiFilter, PiLocation, PiParameter,
    PiEvent, PiTimeSeriesHeader, PiTimeSeries,
    PiFiltersResponse, PiLocationsResponse,
    PiParametersResponse, PiTimeSeriesResponse,
)


def test_pi_filter_serializes():
    f = PiFilter(id="Waterlab-IJssel", name="Test", description="desc")
    d = f.model_dump()
    assert d["id"] == "Waterlab-IJssel"
    assert d["name"] == "Test"


def test_pi_timeseries_response_structure():
    event = PiEvent(date="1995-01-01", time="12:00:00", value="850.000")
    header = PiTimeSeriesHeader(
        locationId="KAMPEN",
        parameterId="Q.sim",
        units="m3/s",
        startDate={"date": "1995-01-01", "time": "12:00:00"},
        endDate={"date": "1995-01-31", "time": "12:00:00"},
    )
    ts = PiTimeSeries(header=header, events=[event])
    resp = PiTimeSeriesResponse(timeSeries=[ts])
    d = resp.model_dump()
    assert d["version"] == "1.25"
    assert d["timeZone"] == "1.0"
    assert d["timeSeries"][0]["header"]["locationId"] == "KAMPEN"
    assert d["timeSeries"][0]["events"][0]["value"] == "850.000"


@pytest.fixture
def fake_output_dir(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "timeseries_kampen.json").write_text(json.dumps({
        "dates": ["1995-01-01", "1995-01-02", "1995-01-03"],
        "q":     [850.0, 1200.0, 2100.0],
        "h_nap": [1.1, 1.4, 2.1],
    }))
    (output / "timeseries_westervoort.json").write_text(json.dumps({
        "dates": ["1995-01-01", "1995-01-02", "1995-01-03"],
        "q":     [900.0, 1300.0, 2200.0],
        "h_nap": [1.0, 1.3, 2.0],
    }))
    return output


def test_get_wflow_timeseries_kampen(fake_output_dir, monkeypatch):
    import fews_poc.data_adapter as da
    monkeypatch.setitem(da.PERIOD_DIRS, "1995", fake_output_dir)

    events = da.get_wflow_timeseries("KAMPEN", "Q.sim", "1995")
    assert len(events) == 3
    assert events[0]["date"] == "1995-01-01"
    assert events[0]["value"] == "850.000"
    assert events[0]["flag"] == "0"


def test_get_wflow_timeseries_unknown_combo_returns_empty(fake_output_dir, monkeypatch):
    import fews_poc.data_adapter as da
    monkeypatch.setitem(da.PERIOD_DIRS, "1995", fake_output_dir)

    events = da.get_wflow_timeseries("LOBITH", "Q.sim", "1995")
    assert events == []


def test_get_waterinfo_timeseries_returns_empty_on_import_error(monkeypatch):
    import fews_poc.data_adapter as da
    monkeypatch.setattr("builtins.__import__", lambda name, *a, **kw: (_ for _ in ()).throw(
        ImportError("no rws_waterinfo")
    ) if name == "rws_waterinfo" else __import__(name, *a, **kw))

    events = da.get_waterinfo_timeseries("KAMPEN", "H.meting")
    assert events == []


def test_get_waterinfo_timeseries_returns_empty_on_api_error(monkeypatch):
    import sys
    import unittest.mock as mock
    import fews_poc.data_adapter as da

    fake_rw = mock.MagicMock()
    fake_rw.get_data.side_effect = RuntimeError("timeout")
    monkeypatch.setitem(sys.modules, "rws_waterinfo", fake_rw)

    events = da.get_waterinfo_timeseries("KAMPEN", "H.meting")
    assert events == []
