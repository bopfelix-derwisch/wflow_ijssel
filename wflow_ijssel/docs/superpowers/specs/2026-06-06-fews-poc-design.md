# FEWS POC — PI REST integratie

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Waterlab implementeert een volledige FEWS PI REST service die eigen wflow SBM output en RWS Waterinfo metingen publiceert, en een PI REST client die die data leest — zodat het PI REST datamodel van binnenuit geleerd wordt.

**Architecture:** Nieuwe FastAPI router (`fews_poc/router.py`) implementeert vier PI REST endpoints. Een data adapter converteert bestaande wflow JSON output en live Waterinfo data naar PI JSON format. Een thin client (`fews_poc/pi_client.py`) consumeert de eigen server. Het dashboard krijgt een nieuwe FEWS tab met een API Explorer en een Plotly vergelijkingsgrafiek.

**Constraint:** Publieke FEWS PI REST endpoints (fews.rws.nl, waterboard-instanties) zijn niet bereikbaar vanaf de Jetson. Waterlab dient zowel als PI REST producer als consumer.

**Tech Stack:** Python 3.10, FastAPI, fewspy 0.6.3, pydantic v2, requests, rws_waterinfo, Plotly, vanilla JS

---

## PI REST datamodel (kernconcepten)

De FEWS PI REST hiërarchie:

```
Filter
  └── Location  (meetpunt, bv. KAMPEN)
        └── Parameter  (variabele, bv. H.meting)
              └── TimeSeriesKey  (combinatie locatie+parameter)
                    └── TimeSeries  (header + events[])
```

**PI JSON timeseries response (vereenvoudigd):**
```json
{
  "version": "1.25",
  "timeZone": "1.0",
  "timeSeries": [{
    "header": {
      "type": "instantaneous",
      "moduleInstanceId": "WaterLab",
      "locationId": "KAMPEN",
      "parameterId": "H.meting",
      "timeStep": {"unit": "nonequidistant"},
      "startDate": {"date": "2024-01-01", "time": "00:00:00"},
      "endDate":   {"date": "2024-01-31", "time": "00:00:00"},
      "units": "m NAP"
    },
    "events": [
      {"date": "2024-01-01", "time": "12:00:00", "value": "1.23", "flag": "0"}
    ]
  }]
}
```

---

## Bestanden

| Actie | Pad | Verantwoordelijkheid |
|-------|-----|----------------------|
| Aanmaken | `fews_poc/__init__.py` | Package marker |
| Aanmaken | `fews_poc/pi_types.py` | Pydantic modellen voor PI REST format (Filter, Location, Parameter, TimeSeries, TimeSeriesHeader, Event) |
| Aanmaken | `fews_poc/data_adapter.py` | Converteert wflow JSON + Waterinfo naar PI JSON; cache 15 min |
| Aanmaken | `fews_poc/router.py` | FastAPI router met vier PI REST endpoints |
| Aanmaken | `fews_poc/pi_client.py` | Thin requests-client die de vier endpoints aanroept |
| Aanpassen | `dashboard/server.py` | Monteert `fews_poc.router` op `/fews` |
| Aanpassen | `dashboard/index.html` | Nieuwe FEWS tab knop + panel HTML |
| Aanpassen | `dashboard/app.js` | switchYear case "fews" + fetchFewsData() |
| Aanpassen | `requirements.txt` | fewspy==0.6.3 toevoegen |

---

## Vier PI REST endpoints

### 1. `GET /fews/rest/fewspiservice/v1/filters`

Geeft één filter terug:

```json
{
  "filters": [{
    "id": "Waterlab-IJssel",
    "name": "Waterlab IJssel — wflow SBM + RWS metingen",
    "description": "IJssel tijdreeksen vanuit wflow SBM simulaties en RWS Waterinfo live data"
  }]
}
```

### 2. `GET /fews/rest/fewspiservice/v1/locations?filterId=Waterlab-IJssel`

Vaste lijst van drie locaties (geen live call nodig):

```json
{
  "locations": [
    {"locationId": "KAMPEN",      "shortName": "Kampen",      "lon": 5.921, "lat": 52.555},
    {"locationId": "WESTERVOORT", "shortName": "Westervoort", "lon": 6.003, "lat": 51.971},
    {"locationId": "LOBITH",      "shortName": "Lobith",      "lon": 6.115, "lat": 51.866}
  ]
}
```

### 3. `GET /fews/rest/fewspiservice/v1/parameters?filterId=Waterlab-IJssel`

```json
{
  "parameters": [
    {"id": "H.meting", "name": "Waterhoogte meting",    "unit": "m NAP",   "displayUnit": "m NAP"},
    {"id": "Q.meting", "name": "Debiet meting",         "unit": "m3/s",    "displayUnit": "m³/s"},
    {"id": "Q.sim",    "name": "Debiet simulatie wflow","unit": "m3/s",    "displayUnit": "m³/s"}
  ]
}
```

### 4. `GET /fews/rest/fewspiservice/v1/timeseries`

Query params: `filterId`, `locationIds` (kommagescheiden), `parameterIds`, `startTime` (ISO), `endTime` (ISO)

Data per parameter/locatie combinatie:
- `H.meting` @ KAMPEN → RWS Waterinfo (`rws_waterinfo`, `WATHTE`, `meting`)
- `Q.meting` @ WESTERVOORT → RWS Waterinfo (`rws_waterinfo`, `Q`, `meting`)
- `Q.sim` @ KAMPEN of WESTERVOORT → bestaande `timeseries_kampen.json` / `timeseries_westervoort.json` uit `data/output` (1995 simulatie als default)

Onbeschikbare combinaties (bv. `H.meting` @ WESTERVOORT) geven een lege `timeSeries: []` terug, geen 404.

Cache: 15 minuten via `_cache` dict (zelfde patroon als bestaande server.py).

---

## Dashboard FEWS tab

### Layout

```
[ Verwachting | Ensemble AI | Multimodel | Jan 1995 | Zomer 2018 | Jul 2021 | FEWS | Roadmap | Platform Visie ]

┌─ FEWS — PI REST Explorer ────────────────────────────────────────────┐
│  Waterlab als FEWS PI REST server · fewspiservice/v1 · localhost     │
│                                                                       │
│  [Filters ▼]  [Locations ▼]  [Parameters ▼]                         │
│  ┌──────────────────────────────────┐                                │
│  │  ruwe PI JSON response           │                                │
│  └──────────────────────────────────┘                                │
│                                                                       │
│  ─── Tijdreeksvergelijking ──────────────────────────────────────── │
│  locatie: [KAMPEN ▼]   periode: [Jan 1995 ▼]                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  Plotly: Q.sim (wflow) vs Q.meting (RWS) — twee y-assen        │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  PI REST hiërarchie uitleg (kleine infobox)                          │
└───────────────────────────────────────────────────────────────────────┘
```

### JavaScript gedrag

- `switchYear("fews")` → toont `#fews-panel`, laadt initiele data
- Drie knoppen (Filters / Locations / Parameters) → fetch naar eigen PI REST endpoint, toon JSON in `<pre>`
- Dropdown locatie + periode → fetch `/fews/rest/.../timeseries` → Plotly update
- Periodes: "Jan 1995", "Zomer 2018", "Jul 2021" → mappen op bestaande `data/output*` directories

### `/api/fews/data` endpoint

Wrapper in `server.py` die de `pi_client.py` aanroept en een vereenvoudigd object teruggeeft voor de grafiek:

```json
{
  "location": "KAMPEN",
  "period": "1995",
  "sim":  {"dates": [...], "values": [...]},
  "obs":  {"dates": [...], "values": [...]}
}
```

---

## Data adapter detail

`data_adapter.py` bevat twee functies:

### `get_wflow_timeseries(location_id, parameter_id, period)`

- Leest `data/output{suffix}/timeseries_{station}.json`
- Veld mapping: `dates` → event dates, `q_sim` of `h_sim` → event values
- `period` → suffix map: `{"1995": "", "2018": "_2018", "2021": "_2021_real"}`

### `get_waterinfo_timeseries(location_id, parameter_id, days=30)`

- Roept `rws_waterinfo` aan (zelfde als forecast.py)
- `H.meting` @ KAMPEN → locatie `"kampen.ijssel"`, grootheid `"WATHTE"`, eenheid `"cm"` (→ /100 voor m NAP)
- `Q.meting` @ WESTERVOORT → locatie `"westervoort"`, grootheid `"Q"`, eenheid `"m3/s"`
- Graceful fallback: als Waterinfo niet beschikbaar, geeft lege lijst terug

---

## Tests

`tests/test_fews_poc.py`:
1. `test_filters_response` — GET /fews/.../filters → bevat "Waterlab-IJssel"
2. `test_locations_response` — bevat KAMPEN, WESTERVOORT, LOBITH
3. `test_parameters_response` — bevat H.meting, Q.meting, Q.sim
4. `test_timeseries_pi_format` — response heeft `timeSeries[0].header.locationId == "KAMPEN"`
5. `test_timeseries_empty_for_unknown_combo` — H.meting @ WESTERVOORT → `timeSeries: []`, geen 404
6. `test_pi_client_get_filters` — pi_client verbindt met test-server en parset filters correct

Tests gebruiken `TestClient` van FastAPI (geen echte Waterinfo-calls; adapter is mockbaar via fixture).

---

## Opmerkingen

- **Geen fewspy als afhankelijkheid voor de server** — fewspy 0.6.3 wordt alleen in `pi_client.py` gebruikt als optionele demonstratie; de server spreekt puur requests/FastAPI.
- **PI REST versie**: v1 (meest gangbaar bij RWS/waterschappen); geen authenticatie vereist.
- **Cache patroon**: zelfde `_cache` dict met `time.monotonic()` als in server.py.
- **Waterinfo graceful fallback**: als `rws_waterinfo` niet beschikbaar, levert de endpoint lege `events: []` met een `comment` veld in de header.
