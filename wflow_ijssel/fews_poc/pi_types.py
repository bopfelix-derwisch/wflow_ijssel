from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class PiFilter(BaseModel):
    id: str
    name: str
    description: str = ""


class PiLocation(BaseModel):
    locationId: str
    shortName: str
    lon: float
    lat: float


class PiParameter(BaseModel):
    id: str
    name: str
    unit: str
    displayUnit: str


class PiEvent(BaseModel):
    date: str
    time: str
    value: str
    flag: str = "0"


class PiTimeSeriesHeader(BaseModel):
    type: str = "instantaneous"
    moduleInstanceId: str = "Waterlab"
    locationId: str
    parameterId: str
    timeStep: dict[str, Any] = Field(default_factory=lambda: {"unit": "nonequidistant"})
    startDate: dict[str, Any] = Field(default_factory=dict)
    endDate: dict[str, Any] = Field(default_factory=dict)
    units: str
    comment: str = ""


class PiTimeSeries(BaseModel):
    header: PiTimeSeriesHeader
    events: list[PiEvent]


class PiFiltersResponse(BaseModel):
    filters: list[PiFilter]


class PiLocationsResponse(BaseModel):
    locations: list[PiLocation]


class PiParametersResponse(BaseModel):
    parameters: list[PiParameter]


class PiTimeSeriesResponse(BaseModel):
    version: str = "1.25"
    timeZone: str = "1.0"
    timeSeries: list[PiTimeSeries]
