# IJssel Wflow Dashboard — Design Spec
**Datum:** 2026-05-27  
**Status:** Goedgekeurd

---

## Doel

Modelleer het IJssel-stroomgebied (Westervoort → Kampen) met Wflow SBM voor de extreme hoogwatergebeurtenis van januari 1995. Presenteer de modeluitvoer in een interactief web-dashboard met een 3D geo-kaart en tijdreeksgrafiek.

---

## Scope

- **Ruimtelijk:** Nederlands IJssel-stroomgebied, Westervoort (splitsing Rijn) tot Kampen (monding IJsselmeer), ~12.000 km²
- **Temporeel:** januari 1995 (extreme hoogwatergebeurtenis)
- **Doel:** piekafvoeranalyse — hoe reageert de IJssel op de extreme neerslag en Rijn-instroom van jan 1995?
- **Buiten scope:** kalibratie, klimaatscenario's, het IJsselmeer zelf

---

## Architectuur

### Projectstructuur

```
wflow_ijssel/
├── run_ijssel.jl              # Wflow SBM simulatie (Julia)
├── ijssel_config.toml         # Modelconfiguratie
├── build_staticmaps.py        # Eenmalig: HydroMT → staticmaps (Python)
├── download_forcing.py        # ERA5 jan 1995 via Copernicus CDS API
├── download_inflow.py         # Westervoort debiet via GRDC
├── export_output.py           # NetCDF → JSON/GeoJSON voor dashboard
├── Project.toml               # Julia dependencies
├── requirements.txt           # Python dependencies
├── dashboard/
│   ├── index.html             # Dashboard frontend
│   ├── app.js                 # deck.gl + Plotly logica
│   └── server.py              # FastAPI dataserver
└── data/
    ├── input/                 # staticmaps, forcing, instates, inflow
    └── output/                # Wflow NetCDF output
```

---

## Data pipeline

### Inputs

| Input | Bron | Formaat | Script |
|---|---|---|---|
| Statische kaarten | HydroMT-Wflow (MERIT DEM, SoilGrids, OpenStreetMap) | NetCDF | `build_staticmaps.py` — eenmalig |
| Forcing (neerslag, temp, ET) | ERA5 reanalyse via Copernicus CDS API | NetCDF | `download_forcing.py` |
| Bovenstrooms randvoorwaarde | Rijkswaterstaat waterinfo.rws.nl (station Westervoort, dagdebiet) | CSV → NetCDF | `download_inflow.py` |
| Begintoestand | Spin-up run dec 1994 vanuit HydroMT-defaultwaarden | NetCDF | eerste run van `run_ijssel.jl` met `reinit=true` |

### Wflow simulatie

- Model: SBM (Simple Bucket Model), zelfde type als Moselle-setup
- Tijdstap: dagelijks (86400 s)
- Simulatieperiode: 1994-12-01 t/m 1995-01-31 (dec als spin-up, jan als analyseperiode)
- Bovenstrooms randvoorwaarde: gemeten dagdebiet Westervoort als `inflow`-forcing in Wflow

### Outputs → dashboard

`export_output.py` converteert Wflow NetCDF naar:
- **`river_network.geojson`** — riviernetwerk met `q` (debiet) en `h` (waterdiepte) per tijdstap
- **`timeseries_kampen.json`** — dagelijkse tijdreeks debiet (m³/s) + waterpeil (m+NAP) bij Kampen
- **`timeseries_westervoort.json`** — instroom-tijdreeks als referentie

---

## Dashboard

### Layout (goedgekeurd: optie C)

```
┌─────────────────────────────────────────────────┐
│  Header: IJssel Hoogwater Dashboard | jan 1995  │
├──────────┬──────────┬──────────┬────────────────┤
│ Piek Q   │ Instroom │ Neerslag │ Duur > drempel │
│ Kampen   │ W'voort  │ anomalie │                │
├──────────┴──────────┴──────────┴────────────────┤
│                                                 │
│    deck.gl 3D ColumnLayer                       │
│    (hoogte = debiet, kleur = debietklasse)      │
│    [▶ tijdslider  1 jan ————●———— 31 jan]       │
│                                                 │
├─────────────────────────────────────────────────┤
│  Plotly: debiet (rood, links) +                 │
│          waterpeil m+NAP (groen gestippeld,     │
│          rechts) + drempelwaarde (oranje)       │
└─────────────────────────────────────────────────┘
```

### Componenten

**KPI-blokken (4x)**
- Piekafvoer Kampen (m³/s) — rood
- Maximale instroom Westervoort (m³/s) — oranje
- Neerslag-anomalie t.o.v. klimatologisch gemiddelde (%) — blauw
- Duur boven drempel 1500 m³/s (dagen) — groen

**3D Kaart (deck.gl ColumnLayer)**
- Riviernetwerk als GeoJSON, geprojecteerd op kaart
- Kolomhoogte per riviercel = gesimuleerd debiet op geselecteerde tijdstap
- Kleurschaal: blauw (laag) → oranje → rood (piek)
- Meetstations Westervoort en Kampen als klikbare markers
- Tijdslider om door jan 1995 te scrubben (dag-resolutie)
- Achtergrondkaart: donkere Carto-basemap via MapLibre GL JS (integreert standaard met deck.gl)

**Tijdreeksgrafiek (Plotly.js)**
- Dubbele Y-as: debiet m³/s (links, rood) + waterpeil m+NAP (rechts, groen gestippeld)
- Horizontale referentielijn op 1500 m³/s (drempelwaarde hoogwater)
- Verticale cursor gekoppeld aan tijdslider van de kaart

### Tech stack

| Laag | Technologie |
|---|---|
| Hydrologie model | Wflow.jl (Julia) |
| Statische kaarten opbouwen | HydroMT-Wflow (Python) |
| Web server | FastAPI (Python) |
| 3D kaart | deck.gl (JavaScript, ColumnLayer) |
| Tijdreeksgrafiek | Plotly.js (JavaScript) |
| Basemap | Carto Dark Matter (via tiles) |

---

## Vereisten

- Julia ≥ 1.9 met Wflow.jl
- Python ≥ 3.10 met: hydromt-wflow, cdsapi, xarray, fastapi, uvicorn
- Copernicus CDS-account (gratis) voor ERA5-download
- Rijkswaterstaat waterinfo.rws.nl voor Westervoort debietdata (gratis, geen aanvraag nodig)

---

## Opmerkingen

- De IJssel is een distributaire van de Rijn: de bovenstrooms randvoorwaarde bij Westervoort is cruciaal voor realistische piekafvoeren. Zonder deze randvoorwaarde onderschat het model de piek sterk.
- HydroMT-stap is eenmalig en duurt ~10-30 minuten; daarna is de Julia-pipeline zelfstandig herhaalbaar.
- Waterpeil (m+NAP) wordt afgeleid uit Wflow-uitvoer `h_river` (waterdiepte) + `bankfull_elevation` uit de statische kaarten.
