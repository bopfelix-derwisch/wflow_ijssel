# fews_poc/router.py
from typing import Optional
from fastapi import APIRouter
from fews_poc.pi_types import (
    PiFilter, PiLocation, PiParameter, PiEvent,
    PiTimeSeriesHeader, PiTimeSeries,
    PiFiltersResponse, PiLocationsResponse,
    PiParametersResponse, PiTimeSeriesResponse,
)
from fews_poc.data_adapter import get_wflow_timeseries, get_waterinfo_timeseries

router = APIRouter(prefix="/fews/rest/fewspiservice/v1", tags=["fews"])

_FILTERS = [
    PiFilter(
        id="Waterlab-IJssel",
        name="Waterlab IJssel — wflow SBM + RWS metingen",
        description="IJssel tijdreeksen vanuit wflow SBM simulaties en RWS Waterinfo live data",
    )
]

_LOCATIONS = [
    PiLocation(locationId="KAMPEN",      shortName="Kampen",      lon=5.921, lat=52.555),
    PiLocation(locationId="WESTERVOORT", shortName="Westervoort", lon=5.969, lat=51.964),
    PiLocation(locationId="LOBITH",      shortName="Lobith",      lon=6.115, lat=51.866),
]

_PARAMETERS = [
    PiParameter(id="H.meting", name="Waterhoogte meting",      unit="m NAP", displayUnit="m NAP"),
    PiParameter(id="Q.meting", name="Debiet meting",           unit="m3/s",  displayUnit="m³/s"),
    PiParameter(id="Q.sim",    name="Debiet simulatie wflow",  unit="m3/s",  displayUnit="m³/s"),
]

_UNITS: dict[str, str] = {p.id: p.unit for p in _PARAMETERS}


@router.get("/filters", response_model=PiFiltersResponse)
def pi_filters():
    return PiFiltersResponse(filters=_FILTERS)


@router.get("/locations", response_model=PiLocationsResponse)
def pi_locations(filterId: str = "Waterlab-IJssel"):
    return PiLocationsResponse(locations=_LOCATIONS)


@router.get("/parameters", response_model=PiParametersResponse)
def pi_parameters(filterId: str = "Waterlab-IJssel"):
    return PiParametersResponse(parameters=_PARAMETERS)


@router.get("/timeseries", response_model=PiTimeSeriesResponse)
def pi_timeseries(
    filterId: str = "Waterlab-IJssel",
    locationIds: str = "KAMPEN",
    parameterIds: str = "Q.sim",
    period: str = "1995",
    startTime: Optional[str] = None,
    endTime: Optional[str] = None,
):
    location_list  = [l.strip() for l in locationIds.split(",")]
    parameter_list = [p.strip() for p in parameterIds.split(",")]

    series: list = []
    for loc_id in location_list:
        for par_id in parameter_list:
            if par_id == "Q.sim":
                raw = get_wflow_timeseries(loc_id, par_id, period)
            else:
                raw = get_waterinfo_timeseries(loc_id, par_id)

            events = [PiEvent(**e) for e in raw]
            header = PiTimeSeriesHeader(
                locationId=loc_id,
                parameterId=par_id,
                units=_UNITS.get(par_id, ""),
                startDate={"date": events[0].date,  "time": events[0].time}  if events else {},
                endDate=  {"date": events[-1].date, "time": events[-1].time} if events else {},
            )
            series.append(PiTimeSeries(header=header, events=events))

    return PiTimeSeriesResponse(timeSeries=series)
