# WL-PROV-2 · Herkomst van schematisatie en randvoorwaarden

**Status:** canoniek · **Datum:** 2026-06-18 · **Backlog:** `docs/BACKLOG_WaterLab_review.md` (WL-PROV-2)
**Gelinkt vanaf:** WL-PROV-1 (de herkomst-keten per POC op de POC's-tab) · **Build-stappen:** `DRAAIBOEK.md`

> Het scherpste inhoudelijke gat uit de review: *"waar komt die schematisatie vandaan?"*
> Een wflow-model zonder herleidbare schematisatie en randvoorwaarden is voor RWS/WMCN per
> definitie niet serieus te nemen. Deze pagina legt per run vast: de bron van het netwerk, de
> herkomst van de schematisatie, en het instroompunt mét randdebiet.

## Kernpunt — wflow rekent op een randvoorwaarde, het is geen 1-D-float

wflow SBM is een **gedistribueerd neerslag-afvoermodel** op een raster, géén 1-D-doorrekening
van een vaste hydrograaf. Twee onafhankelijke invoeren sturen elke run:

1. **Meteo-forcing over het hele grid** — neerslag, potentiële verdamping en temperatuur per
   cel (ERA5-Land). Hieruit berekent SBM de lokale afvoervorming.
2. **Een bovenstroomse instroom-randvoorwaarde** — het debiet waarmee de Rijn via de IJssel-tak
   het modelgebied binnenkomt, opgelegd op de gridcel bij **Westervoort** (lon 6.154, lat 51.987)
   via de wflow-variabele `river_water__external_inflow_volume_flow_rate` (`inflow`, in
   `inflow-westervoort.nc`).

Zonder die randvoorwaarde zou het model alleen de lokaal-gevormde IJssel-afvoer kennen en de
Rijn-bijdrage missen. **Waar dat randdebiet vandaan komt, verschilt per run — zie de tabel.**

> **Westervoort, niet Lobith.** Het instroompunt is Westervoort: de IJssel-tak ná de Pannerdense
> Kop (~13% van de Rijn bij normaal water, ~25% bij hoogwater). Lobith is de Rijn-totaal en wordt
> alleen als *gemeten referentie* getoond, niet als modelrandvoorwaarde.

## Herkomst van het netwerk en de schematisatie

| Onderdeel | Bron / methode |
|-----------|----------------|
| Hoogtemodel (DEM) | **Copernicus DEM** (AWS-tegels, ~180 MB), hersampeld naar 0.008333° (~1 km). Alt.: MERIT Hydro via HydroMT (`build_staticmaps.py`). |
| Afvoernetwerk (LDD) | D8 afgeleid met **pyflwdir**; uitlaat gesnapped op lon 5.496 / lat 53.221, bovenstrooms areaal **10 231 km²**; **19 490** stroomgebiedscellen, **1 517** riviercellen. |
| LDD-correctie Zwolle→Kampen | **PDOK NWB**-centerline ingebrand (`fix_staticmaps.py`): junctie lat 52.47/lon 6.17 omgeleid NE→W, terminus lat 52.579/lon 5.838 (Ketelmeer-pit). Zonder deze stap loopt de IJssel na Zwolle ten onrechte naar het NO. |
| Bodem-/landparameters | Statische lagen in `staticmaps-ijssel.nc` (thetaS/thetaR, KsatVer, Manning N, RootingDepth, …); bodemlaagdikten **[100, 300, 800] mm**. |
| Rivierrouting | **Kinematic wave** (`river_routing = "kinematic_wave"`). Geen 2-D-inundatie, geen stuw-/peilregulering. |
| Modelversie | wflow **SBM** (Julia, Wflow.jl). Build-recept: `DRAAIBOEK.md`; config: `ijssel_config*.toml`. |

**Bekende beperking van de schematisatie:** Copernicus DEM bevat geen poldercorrecties — het
stroomgebied is iets ruimer dan de echte IJssel-grens. Grondwateronttrekking (landbouw/Vitens)
en laagwater-stuwregulering zitten niet in het schema (relevant bij droogte, Proef 5).

## Randvoorwaarden per run

Alle runs delen dezelfde schematisatie (`staticmaps-ijssel.nc`) en ERA5-Land-forcing
(bbox N53.5 / W5.0 / S51.0 / E8.0). Ze verschillen in periode en in de **instroom bij Westervoort**:

| Run (POC) | Periode | Meteo-forcing | Instroom Westervoort | Herkomst randdebiet |
|-----------|---------|---------------|----------------------|---------------------|
| Hoogwater 1995 (P4) | 1994-12-01 → 1995-01-31 | ERA5-Land | **gesynthetiseerd**, piek ~3 120 m³/s | RIZA/RWS-archief — Lobith ~12 600 m³/s, IJssel-aandeel ~25%. RWS Waterinfo heeft geen data vóór ~2000. |
| Droogte 2018 (P5) | mei – aug 2018 | ERA5-Land | neerslag-afvoer (geen hoogwater-instroom) | Droogte gedomineerd door bovenstroomse Rijn-recessie; signaal zit in het neerslagdeficiet. |
| Hoogwater 2021 — run (a) (P6) | 2021-05-01 → 2021-08-31 | ERA5-Land | **gesynthetiseerd**, piek ~2 200 m³/s | RWS-waterstandsberichten jul 2021 — Lobith ~8 900 m³/s, IJssel ~25%. |
| Hoogwater 2021 — run (b) "real" (P6) | idem | ERA5-Land | **gemeten** RWS-debiet | RWS Waterinfo, station `westervoort.ijsselkop` (`build_inflow_2021_real.py`, rws-waterinfo 1.0.1). |
| Ensemble (P2) | mei – aug 2018 | ERA5-Land **×0.70–×1.30** | als 2018 | Synthetische neerslag-perturbatie — geen echte meteo-onzekerheid. |

Run (b) van 2021 is de enige met een *gemeten* instroom-randvoorwaarde; de Nash-Sutcliffe vs de
gemeten afvoer bij Kampen is daardoor merkbaar hoger dan run (a). Dit is meteen het zichtbare
bewijs dat de randvoorwaarde — niet alleen de forcing — de uitkomst stuurt.

## Output-meetpunten (gauges)

Vastgelegd in `[[output.csv.column]]` van de config:

| Gauge | Coördinaat (lon, lat) | Grootheid |
|-------|-----------------------|-----------|
| Kampen | 5.496, 53.221 | debiet `q_river` + waterpeil `h_river` |
| Westervoort | 6.154, 51.987 | debiet `q_river` (= instroompunt) |

## Reproduceerbaarheid

De volledige keten staat in de repo: `build_staticmaps_copernicus.py` (DEM→netwerk) →
`fix_staticmaps.py` (PDOK LDD-fix) → `download_forcing*.py` (ERA5-Land) →
`download_inflow*.py` / `build_inflow_2021_real.py` (randvoorwaarde) →
`run_ijssel*.jl` (Wflow.jl) → output in `wflow_ijssel/data/output*/`. Stap-voor-stap: `DRAAIBOEK.md`.
