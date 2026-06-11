# Waterlab

**Persoonlijk micro-innovatielab voor hydrologische modellering en AI-integratie in waterbeheer**

🌐 **Live:** [waterlab.felixisfelix.com](https://waterlab.felixisfelix.com)

> **Experimenteel — 1 persoon.** Doel: leren van modellen, het vakgebied en AI-innovaties,
> en verkennen hoe een modern kennisinstrumentarium voor waterbeheer eruit zou kunnen zien.
> Simulaties zijn indicatief. Dit is geen operationeel systeem.

---

## Doelen

Drie leerdoelen sturen de experimenten:

1. **Modellen begrijpen** — wflow SBM, Ribasim, ensemble-methoden, data-assimilatie: hoe werken ze, wat geven ze, waar zitten de grenzen?
2. **Vakgebied verkennen** — RWS-processen, waterschappen, het Deltares-ecosysteem en FEWS: hoe ziet het huidige kennisinstrumentarium eruit?
3. **AI-innovaties testen** — LLM-orkestratie, expert-agents, tool use, real-time integratie: wat voegt AI concreet toe aan hydrologische analyse?

Achterliggende vraag: hoe zou een modern kennisinstrumentarium voor waterbeheer eruitzien
als je het vandaag opnieuw ontwerpt — API-first, AI-ondersteund, zonder legacy GUI-afhankelijkheden?

---

## Platform

Waterlab draait volledig op een **NVIDIA Jetson AGX Orin** (ARM64 edge device) en
combineert een hydrologisch model, een hydraulisch netwerkmodel, twee LLM-integraties
en live datafeeds. Het project test hoe ver je kunt gaan met modelkoppelingen en AI-assistentie
op één edge computer.

---

## Negen proeven

| Proef | Tab | Kern | AI-component |
|-------|-----|------|-------------|
| 1 | **Verwachting** | Statistisch debietmodel + RWS Waterinfo live + Open-Meteo 14d | Claude — **integrale** interventie: peil/scheepvaart én grondwater-domeinen (Vitens, landbouw, kwel) via de IJssel→grondwater-koppeling |
| 2 | **Ensemble AI** | wflow SBM ×5 neerslag-scenario's (×0.70–×1.30) | Qwen2.5-32B lokaal — spread-interpretatie |
| 3 | **Multimodel** | Ribasim netwerk → LLM-orchestrator → wflow ensemble | Qwen2.5-32B lokaal — kritieke-knoop-selectie |
| 4 | **Jan 1995** | wflow SBM hoogwater, ERA5-Land forcing | — |
| 5 | **Zomer 2018** | wflow SBM droogte, laagwaterperiode | — |
| 6 | **Jul 2021** | wflow SBM hoogwater, gemeten vs. synthetische inflow | — |
| 7 | **FEWS** | Waterlab als Deltares PI REST 1.25-service | — |
| 8 | **GraphQL-façade** | Read-only query-laag over de domeingraaf (`/graphql`) | — |
| 9 | **Grondwater** | BRO grondwater ↔ IJssel-peil: lag-correlatie (zomer 2018) + voorspellende projectie | Qwen2.5-32B lokaal — hydrologische duiding |

---

## API's & platform-laag

API-first: dashboard, FEWS, GraphQL en webhooks zijn verwisselbare clients op dezelfde data.

### GraphQL-façade — `/graphql` (GraphiQL aan)
Eén read-only query stitcht de domeingraaf; resolvers delegeren naar bestaande bronfuncties (geen tweede datapad).

```graphql
{ station(id: "kampen") {
    name
    forecast(days: 14) { band { date mean } intervention { regime } }
    nearbyGroundwaterWells(radiusKm: 20, limit: 3) {     # merge-node: platform ↔ BRO
      broId distanceKm
      series(period: "2018-06-01/2018-08-31") { events { date value } }
    }
} }
```

Limieten: query-diepte ≤ 10, ≤ 2000 tokens, ≤ 15 aliassen, en 60 verzoeken/min per IP (HTTP 429).

### FEWS PI REST 1.25 — `/fews/rest/fewspiservice/v1/`
Deltares-compatibel: `filters` · `locations` · `parameters` · `timeseries` (PI JSON). De niet-standaard `period`-parameter selecteert een historische wflow-run (1995/2018/2021).

### REST data-endpoints
- `GET /api/forecast` · `/api/forecast/intervention` — live verwachting + integrale AI-interventie
- `GET /api/grondwater` · `/api/grondwater/interpretation` · `/api/grondwater/projection` — Proef 9 (overlay, AI-duiding, vooruitblik)
- `GET /api/ensemble` · `/api/multimodel` · `/api/{1995|2018|2021}/...`

### Databron grondwater (Proef 9)
Gemeten grondwaterstanden uit het **BRO Grondwaterstandendossier (GLD)**. Ruimtelijke discovery + GMW↔GLD-koppeling via de **PDOK OGC API** (`gm_gld`, bbox); reeksen via broservices `seriesAsCsv`. Server-side opgehaald (CORS omzeild), gecached. De IJssel→grondwater-koppeling is gekalibreerd op zomer 2018 (lag 6–28 d, r tot 0.94) en data-gedreven — geen fysisch kwelmodel. Feasibility: `docs/WL-BRO-0_feasibility.md`.

---

## Dashboard & rondleiding

- **Tabs** zijn deelbaar via deep-link (hash), bv. `…/#grondwater`, `…/#forecast`.
- **Handleiding-tab** — navigatie, de drie API's met voorbeeldquery, databronnen en beperkingen.
- **▶ Rondleiding** — knop rechtsonder start een geleide auto-tour langs de kerntabs.
- **`DEMO.md`** — korte demo-flow / video-script (~3–4 min) met talking points.

---

## Architectuur

```
RWS Waterinfo (live)          Open-Meteo (live)
      │                              │
      └──────────────┬───────────────┘
                     ▼
             Statistisch recessiemodel
             + neerslaginpulsrespons
                     │
                     ▼
          Claude Haiku (Anthropic API)
          Expert-hydroloog persona:
          waterpeil-regime → interventie
                     │
                     ▼
              Dashboard Verwachting
                     
─────────────────────────────────────────────────────

ERA5-Land forcing (historisch)
      │
      ▼
 wflow SBM ×1          ─── Proeven 4, 5, 6 (historische events)
 (ARM64, Julia)
      │
      ▼
 wflow SBM ×5          ─── Proef 2 (Ensemble AI)
 neerslag-perturbaties         │
                               ▼
                        Qwen2.5-32B (lokaal)
                        spread-interpretatie

─────────────────────────────────────────────────────

Ribasim netwerk
(3 takken: IJssel / Neder-Rijn / Lek)
  Python 3.13 bouwt model → Julia solver
      │
      ▼
Qwen2.5-32B (lokaal)   ─── Proef 3 (Multimodel)
  kritieke knoop selectie
      │
      ▼
 wflow SBM ×5
  deelstroomgebied
      │
      ▼
FastAPI dashboard (poort 8000)
  MapLibre GL · Plotly · deck.gl
  Cloudflare Tunnel → waterlab.felixisfelix.com
```

---

## AI-interventie (Proef 1)

De forecast-tab genereert een waterbeheer-interventie via de **Anthropic API** (Claude Haiku).
De keuze voor de Anthropic API in plaats van de lokale LLM is bewust: de interventie is
een advies met potentiële operationele impact, waarvoor hogere modelkwaliteit gewenst is.

**Expert-persona:** de prompt modelleert een senior hydroloog bij RWS WNL met 25 jaar
IJssel-ervaring. De systeemprompt bevat:

- ASCII-gebiedsschematisatie (Lobith → Pannerdense Kop → Westervoort → Kampen → Ketelmeer)
- Nautische drempelwaarden (BICS-codes, klasse IV/V ondiepgang-limieten bij Roggebotsluis)
- Stakeholders (HHNK, Vitens, Waterschap Vallei en Veluwe, Waterschap Rijn en IJssel)
- Ecologische minimumafvoer (50 m³/s KRW, Veluwe-kwelzone)
- Historische referenties (droogte 2018: −0.45 m+NAP, droogte 2022: −0.38 m+NAP)

**Integraal (Proef 9-koppeling):** de prompt krijgt live de recente Veluwe-grondwaterstand (BRO GLD)
en de gekalibreerde IJssel→grondwater-koppeling (lag ~18 d, r≈0.9) mee. Bij laagwater/droogte
adresseert de interventie daardoor óók de grondwaterafhankelijke domeinen — drinkwaterwinning
(Vitens), landbouw/beregening en natuur/kweldruk — niet alleen peil en scheepvaart.

**Regime-classificatie** stuurt het type interventie:

| Regime | Peil Kampen | Interventie-focus |
|--------|-------------|-------------------|
| Extreem laag | < 0.0 m+NAP | ICPR-afstemming, laagwaterprotocol, scheepvaartstop klasse V |
| Laag | 0.0–0.5 m+NAP | BICS-waarschuwing, Veluwemeer-inlaatbeheer |
| Normaal | 1.2–3.0 m+NAP | Reguliere monitoring |
| Waakzaam | 3.0–4.2 m+NAP | Dijkbewaking, waterstandsberichten |
| Hoog | > 4.2 m+NAP | Crisisoverleg, evacuatieplannen |

---

## Tech stack

| Laag | Component | Technologie |
|------|-----------|-------------|
| Hydrologisch model | wflow SBM 1.0.2 | Julia 1.12.5 · ARM64 (JIT ~2:20u cold start) |
| Hydraulisch netwerk | Ribasim 2026.1.1 | Python 3.13 (build) + Julia (solver) |
| Lokale LLM | Qwen2.5-32B-Instruct-Q4 | llama.cpp · localhost:8080 |
| Cloud LLM | Claude Haiku | Anthropic API · `.env` voor API-key |
| Live data | RWS Waterinfo + Open-Meteo | 15-min cache · graceful fallback |
| Grondwater | BRO GLD via PDOK OGC API + broservices | server-side (`requests`) · gecached |
| API / server | FastAPI + uvicorn | Python 3.10 · poort 8000 |
| Query-laag | GraphQL | `strawberry-graphql[fastapi]` · `/graphql` · depth/rate-limited |
| Interop | FEWS PI REST 1.25 | `/fews/rest/fewspiservice/v1/` |
| Frontend | Dashboard | MapLibre GL · Plotly · deck.gl · vanilla JS |
| Tunneling | Cloudflare Tunnel | IPv4 (`edge-ip-version: 4`) — IPv6 uitgezet wegens adresrotatie |
| Hardware | NVIDIA Jetson AGX Orin | aarch64 · 64 GB · Ubuntu 22.04 |

---

## Ribasim op ARM64

De officiële Ribasim Linux binary is x86-64 en werkt niet op aarch64. Werkende aanpak:

```bash
# 1. Python 3.13 venv voor model bouwen
python3.13 -m venv .venv313 && .venv313/bin/pip install ribasim

# 2. Julia Ribasim package (solver)
julia -e 'using Pkg; Pkg.add(url="https://github.com/Deltares/Ribasim", subdir="core")'
# Precompilatie ~295s (eenmalig)

# 3. Pipeline
python3 multimodel/build_ribasim_model.py <tmp_dir> <settings_json>
julia -e 'using Ribasim; Ribasim.run("<tmp_dir>/ribasim.toml")'
```

Eerste run duurt ~32 s door Julia JIT-compilatie.

---

## Cloudflare Tunnel

Één tunnel serveert twee domeinen:

```yaml
# ~/.cloudflared/config.yml
protocol: http2
edge-ip-version: "4"   # IPv6 uitgezet: adresrotatie elke ~24u veroorzaakte reconnects
ingress:
  - hostname: waterlab.felixisfelix.com
    service: http://localhost:8000
  - hostname: geluid.felixisfelix.com
    service: http://localhost:8792
  - service: http_status:404
```

---

## Draaien

```bash
# Vereisten: Python 3.10, Python 3.13, Julia 1.12.5
cd /home/bob/waterlab/wflow_ijssel

# Dashboard (inclusief live forecast + AI-interventie)
python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8000

# Ensemble AI (éénmalig uitvoeren voor Proef 2)
cd /home/bob/waterlab && python run_ensemble.py

# Multimodel pipeline (éénmalig uitvoeren voor Proef 3)
cd /home/bob/waterlab && python run_multimodel.py
```

Publiek bereikbaar: **[https://waterlab.felixisfelix.com](https://waterlab.felixisfelix.com)**

---

## Licentie

Persoonlijk onderzoeksproject — geen licentie van toepassing.
