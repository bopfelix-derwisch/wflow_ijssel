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
