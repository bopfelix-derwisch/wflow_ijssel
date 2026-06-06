import json
import pytest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
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


@pytest.fixture
def fews_client(monkeypatch):
    fake_events = [
        {"date": "1995-01-01", "time": "12:00:00", "value": "850.000", "flag": "0"},
        {"date": "1995-01-31", "time": "12:00:00", "value": "3200.000", "flag": "0"},
    ]
    monkeypatch.setattr("fews_poc.router.get_wflow_timeseries",
                        lambda *a, **kw: fake_events)
    monkeypatch.setattr("fews_poc.router.get_waterinfo_timeseries",
                        lambda *a, **kw: [])

    from fews_poc.router import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_filters_response(fews_client):
    resp = fews_client.get("/fews/rest/fewspiservice/v1/filters")
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["filters"]]
    assert "Waterlab-IJssel" in ids


def test_locations_response(fews_client):
    resp = fews_client.get("/fews/rest/fewspiservice/v1/locations?filterId=Waterlab-IJssel")
    assert resp.status_code == 200
    ids = [l["locationId"] for l in resp.json()["locations"]]
    assert "KAMPEN" in ids
    assert "WESTERVOORT" in ids
    assert "LOBITH" in ids


def test_parameters_response(fews_client):
    resp = fews_client.get("/fews/rest/fewspiservice/v1/parameters?filterId=Waterlab-IJssel")
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["parameters"]]
    assert "H.meting" in ids
    assert "Q.meting" in ids
    assert "Q.sim" in ids


def test_timeseries_pi_format(fews_client):
    resp = fews_client.get(
        "/fews/rest/fewspiservice/v1/timeseries"
        "?filterId=Waterlab-IJssel&locationIds=KAMPEN&parameterIds=Q.sim&period=1995"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "1.25"
    assert data["timeZone"] == "1.0"
    assert len(data["timeSeries"]) == 1
    ts = data["timeSeries"][0]
    assert ts["header"]["locationId"] == "KAMPEN"
    assert ts["header"]["parameterId"] == "Q.sim"
    assert ts["events"][0]["value"] == "850.000"


def test_timeseries_empty_for_unknown_combo(fews_client):
    resp = fews_client.get(
        "/fews/rest/fewspiservice/v1/timeseries"
        "?filterId=Waterlab-IJssel&locationIds=LOBITH&parameterIds=H.meting"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["timeSeries"][0]["events"] == []


def test_pi_client_get_filters(fews_client, monkeypatch):
    """pi_client verbindt met test-server en parset filters correct."""
    import requests
    from fews_poc.pi_client import PiRestClient

    def fake_get(url, **kwargs):
        path = url.replace("http://testserver", "")
        resp_data = fews_client.get(path)
        class FakeResp:
            status_code = resp_data.status_code
            def json(self): return resp_data.json()
            def raise_for_status(self): pass
        return FakeResp()

    monkeypatch.setattr(requests, "get", fake_get)

    client = PiRestClient("http://testserver")
    filters = client.get_filters()
    assert any(f["id"] == "Waterlab-IJssel" for f in filters)


def test_pi_client_get_timeseries(fews_client, monkeypatch):
    import requests
    from fews_poc.pi_client import PiRestClient

    def fake_get(url, **kwargs):
        path = url.replace("http://testserver", "")
        resp_data = fews_client.get(path)
        class FakeResp:
            status_code = resp_data.status_code
            def json(self): return resp_data.json()
            def raise_for_status(self): pass
        return FakeResp()

    monkeypatch.setattr(requests, "get", fake_get)

    client = PiRestClient("http://testserver")
    ts = client.get_timeseries(
        filter_id="Waterlab-IJssel",
        location_ids=["KAMPEN"],
        parameter_ids=["Q.sim"],
        period="1995",
    )
    assert len(ts) == 1
    assert ts[0]["header"]["locationId"] == "KAMPEN"
    assert len(ts[0]["events"]) > 0
