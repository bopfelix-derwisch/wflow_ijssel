"""WL-GQL-1 — Read-only GraphQL-façade (PoC).

Eén query-laag over de bestaande WaterLab-bronnen. De resolvers DELEGEREN naar
bestaande bronfuncties — geen tweede datapad, geen gedupliceerde datalogica:

  - forecast   → dashboard.forecast.build_forecast()      (live RWS + Open-Meteo)
  - measured   → fews_poc.data_adapter.get_waterinfo_timeseries()  (live RWS)
  - simulated  → fews_poc.data_adapter.get_wflow_timeseries()      (wflow output op schijf)
  - intervention → dashboard.server._build_intervention()  (lazy import i.v.m. cykel)

WL-GQL-2: station → nearbyGroundwaterWells koppelt de façade aan de BRO-connector
(dashboard.bro_gld) — de merge-node tussen spoor A (GraphQL) en spoor B (grondwater).

Mount: server.py doet  app.include_router(graphql_app, prefix="/graphql").
GraphiQL staat aan (PoC, LAN/Tailscale only — geen auth in deze fase).
"""
from __future__ import annotations

import enum
from typing import List, Optional

import strawberry

from dashboard import bro_gld
from dashboard.forecast import build_forecast
from fews_poc.data_adapter import get_wflow_timeseries, get_waterinfo_timeseries

# ── Stationmetadata (single source = PI REST locatielijst) ───────────────────
from fews_poc.router import _LOCATIONS as _PI_LOCATIONS

_STATION_NAMES = {loc.locationId: loc.shortName for loc in _PI_LOCATIONS}
_STATION_LOCS  = {loc.locationId: (loc.lat, loc.lon) for loc in _PI_LOCATIONS}

# Regimebanden — spiegelt dashboard.server._classify_regime() (m+NAP, Kampen).
_REGIME_BANDS = [
    ("extreem_laag",  None,  0.0),
    ("laag",           0.0,  0.5),
    ("benedennormaal", 0.5,  1.2),
    ("normaal",        1.2,  3.0),
    ("waakzaam",       3.0,  4.2),
    ("verhoogd",       4.2,  5.4),
    ("hoog",           5.4,  6.4),
    ("extreem_hoog",   6.4,  None),
]


# ── Enums ────────────────────────────────────────────────────────────────────

@strawberry.enum
class Parameter(enum.Enum):
    Q = "Q"   # debiet
    H = "H"   # waterhoogte


@strawberry.enum
class Model(enum.Enum):
    WFLOW_SBM = "wflow_sbm"


@strawberry.enum
class Inflow(enum.Enum):
    MEASURED = "measured"
    SYNTHETIC = "synthetic"


# ── Types ────────────────────────────────────────────────────────────────────

@strawberry.type
class ThresholdBand:
    regime: str
    peil_from: Optional[float] = strawberry.field(name="peilFrom")
    peil_to: Optional[float] = strawberry.field(name="peilTo")


@strawberry.type
class Event:
    date: str
    value: float


@strawberry.type
class Measured:
    events: List[Event]


@strawberry.type
class Peak:
    value: Optional[float]
    date: Optional[str]


@strawberry.type
class Simulated:
    peak: Peak
    events: List[Event]


@strawberry.type
class ForecastBandPoint:
    date: str
    p10: float
    mean: float
    p90: float


@strawberry.type
class Intervention:
    regime: str
    text: str
    source: str


@strawberry.type
class Forecast:
    band: List[ForecastBandPoint]
    intervention: Optional[Intervention]


# ── Period helper ────────────────────────────────────────────────────────────

def _in_period(date_str: str, period: Optional[str]) -> bool:
    """period = 'YYYY-MM-DD/YYYY-MM-DD' (ISO-interval) of None (alles)."""
    if not period or "/" not in period:
        return True
    start, _, end = period.partition("/")
    return start.strip() <= date_str <= end.strip()


def _events_to_gql(raw: List[dict], period: Optional[str]) -> List[Event]:
    out: List[Event] = []
    for e in raw:
        d = e.get("date", "")
        if _in_period(d, period):
            out.append(Event(date=d, value=float(e.get("value", 0.0))))
    return out


# ── Grondwater (WL-GQL-2 — koppelt de platform-laag aan de BRO-connector) ────

@strawberry.type
class GroundwaterWell:
    bro_id: str = strawberry.field(name="broId")
    lat: float
    lon: float
    distance_km: float = strawberry.field(name="distanceKm")
    n_obs: int = strawberry.field(name="nObs")
    first: str
    last: str

    @strawberry.field
    def series(self, period: Optional[str] = None) -> Measured:
        """Daggemiddelde grondwaterreeks (BRO GLD), optioneel geclipt op period
        ('start/end'). Wordt alleen opgehaald als dit veld wordt opgevraagd."""
        start = end = None
        if period and "/" in period:
            s, _, e = period.partition("/")
            start, end = s.strip(), e.strip()
        raw = bro_gld.fetch_series(self.bro_id, start, end)
        return Measured(events=_events_to_gql(raw, None))


# ── Station type ─────────────────────────────────────────────────────────────

@strawberry.type
class Station:
    id: strawberry.Private[str]

    @strawberry.field
    def name(self) -> str:
        return _STATION_NAMES.get(self.id.upper(), self.id)

    @strawberry.field
    def thresholds(self) -> List[ThresholdBand]:
        return [
            ThresholdBand(regime=r, peil_from=lo, peil_to=hi)
            for (r, lo, hi) in _REGIME_BANDS
        ]

    @strawberry.field
    def measured(
        self,
        parameter: Parameter = Parameter.Q,
        period: Optional[str] = None,
    ) -> Measured:
        # Live RWS: Q.meting bij Westervoort, H.meting bij Kampen.
        if parameter == Parameter.H:
            raw = get_waterinfo_timeseries("KAMPEN", "H.meting")
        else:
            raw = get_waterinfo_timeseries("WESTERVOORT", "Q.meting")
        return Measured(events=_events_to_gql(raw, period))

    @strawberry.field
    def simulated(
        self,
        model: Model = Model.WFLOW_SBM,
        event: str = "jul2021",
        inflow: Inflow = Inflow.MEASURED,
    ) -> Simulated:
        period = {"jan1995": "1995", "zomer2018": "2018", "jul2021": "2021"}.get(event, event)
        raw = get_wflow_timeseries(self.id.upper(), "Q.sim", period)
        events = _events_to_gql(raw, None)
        if events:
            top = max(events, key=lambda e: e.value)
            peak = Peak(value=top.value, date=top.date)
        else:
            peak = Peak(value=None, date=None)
        return Simulated(peak=peak, events=events)

    @strawberry.field
    def forecast(self, days: int = 14) -> Forecast:
        fc = build_forecast()
        f = fc.get("forecast", {})
        dates = f.get("dates", [])[:days]
        lo = f.get("q_low", [])
        mid = f.get("q_mid", [])
        hi = f.get("q_high", [])
        band = [
            ForecastBandPoint(date=d, p10=float(lo[i]), mean=float(mid[i]), p90=float(hi[i]))
            for i, d in enumerate(dates)
            if i < len(lo) and i < len(mid) and i < len(hi)
        ]

        intervention: Optional[Intervention] = None
        try:
            # Lazy import: server.py importeert dit module → vermijd circulaire import.
            from dashboard.server import _build_intervention, _classify_regime
            h_now = fc.get("kpis", {}).get("current_h_kampen_m")
            text = _build_intervention(fc)
            intervention = Intervention(
                regime=_classify_regime(h_now),
                text=text,
                source="claude-haiku-4-5",
            )
        except Exception:
            intervention = None  # graceful fallback bij LLM-/keyuitval

        return Forecast(band=band, intervention=intervention)

    @strawberry.field
    def nearby_groundwater_wells(
        self,
        radius_km: float = 15.0,
        limit: int = 5,
        covers_from: str = "2018-06-01",
        covers_to: str = "2018-08-31",
    ) -> List[GroundwaterWell]:
        """BRO GLD-grondwaterputten nabij dit station — de merge-node die de
        GraphQL-façade (WL-GQL-1) aan de BRO-connector (WL-BRO-1) koppelt.
        Metadata is goedkoop; de reeks per put volgt alleen bij `series`."""
        loc = _STATION_LOCS.get(self.id.upper())
        if not loc or loc[0] is None or loc[1] is None:
            return []
        lat, lon = loc
        wells = bro_gld.wells_near(lat, lon, radius_km, limit, covers_from, covers_to)
        return [
            GroundwaterWell(
                bro_id=w["bro_id"], lat=w["lat"], lon=w["lon"],
                distance_km=w["distance_km"], n_obs=w["n_obs"],
                first=w["first"], last=w["last"],
            )
            for w in wells
        ]


# ── Query root ───────────────────────────────────────────────────────────────

@strawberry.type
class Query:
    @strawberry.field
    def station(self, id: str) -> Station:
        return Station(id=id)


schema = strawberry.Schema(query=Query)

# GraphiQL aan (PoC). Wordt gemount in server.py.
from strawberry.fastapi import GraphQLRouter  # noqa: E402

graphql_app = GraphQLRouter(schema, graphql_ide="graphiql")
