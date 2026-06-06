# fews_poc/pi_client.py
from __future__ import annotations
import requests


class PiRestClient:
    """Thin client voor FEWS PI REST v1 endpoints."""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self._prefix = "/fews/rest/fewspiservice/v1"

    def _get(self, path: str, **params) -> dict:
        url = f"{self.base}{self._prefix}{path}"
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_filters(self) -> list[dict]:
        return self._get("/filters").get("filters", [])

    def get_locations(self, filter_id: str = "Waterlab-IJssel") -> list[dict]:
        return self._get("/locations", filterId=filter_id).get("locations", [])

    def get_parameters(self, filter_id: str = "Waterlab-IJssel") -> list[dict]:
        return self._get("/parameters", filterId=filter_id).get("parameters", [])

    def get_timeseries(
        self,
        filter_id: str = "Waterlab-IJssel",
        location_ids: list[str] | None = None,
        parameter_ids: list[str] | None = None,
        period: str = "1995",
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[dict]:
        params: dict = {
            "filterId":     filter_id,
            "locationIds":  ",".join(location_ids or ["KAMPEN"]),
            "parameterIds": ",".join(parameter_ids or ["Q.sim"]),
            "period":       period,
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return self._get("/timeseries", **params).get("timeSeries", [])
