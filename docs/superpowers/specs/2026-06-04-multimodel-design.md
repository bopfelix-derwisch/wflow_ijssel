# AI-Orchestrated Multimodel Water System — Design Spec

**Goal:** End-to-end pipeline: Ribasim Rijn/IJssel netwerk → AI detecteert kritieke knoop → wflow IJssel droogte-ensemble → Multimodel dashboard-tab met Leaflet-kaart.

**Architecture:** Vier sequentiële lagen — Ribasim (landelijk netwerk), AI Orchestrator (beslissingslogica), wflow (lokaal ensemble), Dashboard (visualisatie). Elke laag is een onafhankelijke Python-module met een helder interface.

**Tech Stack:** `ribasim` Python package, Qwen2.5-32B via llama.cpp (port 8080), bestaande wflow Julia pipeline, FastAPI + Leaflet.js dashboard.

---

## 1. Dataflow

```
[Ribasim] Rijn/IJssel netwerk (~12 knopen)
    ↓  basin waterstanden + Westervoort-afvoer (SQLite)
[AI Orchestrator] scoort knopen op deficit, kiest wflow-run
    ↓  selected_catchment + precip_multipliers + llm_explanation
[wflow IJssel] ensemble 5 droogte-scenario's (ERA5 zomer 2018)
    ↓  peak_q P10/mean/P90 tijdreeks
[Dashboard] Multimodel tab: Leaflet-kaart + AI-blok + ensemble-grafiek
```

---

## 2. Ribasim netwerk

**Knopen (~12 totaal):**

| Knoop | Type | Coördinaten (lon, lat) |
|-------|------|------------------------|
| Lobith | FlowBoundary | 6.112, 51.862 |
| Pannerdensch Kanaal | Basin | 6.000, 51.850 |
| IJssel-splitsing | Basin | 5.970, 51.960 |
| IJssel-Deventer | Basin | 6.157, 52.252 |
| IJssel-Kampen | Basin | 5.921, 52.555 |
| Neder-Rijn | Basin | 5.800, 51.960 |
| Lek | Basin | 5.000, 51.900 |
| Noord | Basin | 4.600, 51.850 |
| Nieuwe Maas | Basin | 4.400, 51.900 |
| Waddenzee | LevelBoundary | 5.300, 53.100 |

**Droogtescenario:** Lobith-inflow als sinusvorm: `600 + 150 * sin(2π t / 90)` m³/s over jun–aug 2018 (representatief voor het droogtejaar 2018, normaal ~2000 m³/s).

**Drempelwaarden per Basin** (in `config/settings.yaml`): waterstand waarbij het gebied als kritiek wordt beschouwd (bijv. IJssel-Kampen: 0.5 m NAP).

**Run:** `ribasim.run_ribasim(toml_path)` — output in `multimodel_data/ribasim/results/` als SQLite.

---

## 3. AI Orchestrator

**Input:** Ribasim SQLite (`Basin/results/level` tabel), drempelwaarden uit settings.

**Verwerking:**
1. Lees gemiddelde waterstand per Basin over de simulatieperiode
2. Bereken deficit per knoop: `deficit_pct = max(0, (threshold - mean_level) / threshold * 100)`
3. Selecteer kritieke knoop: hoogste `deficit_pct`
4. Map knoop → wflow-catchment (hardcoded tabel: `"ijssel" → wflow_ijssel`)
5. Roep Qwen aan voor motivatietekst (NL, max 300 tokens)

**Output:**
```python
{
  "selected_catchment": "ijssel",
  "critical_node":      "IJssel-Kampen",
  "deficit_pct":        47.3,
  "trigger_reason":     "IJssel-Kampen 47% onder drempelstand van 0.5 m NAP",
  "llm_explanation":    "...",
  "wflow_params": {
    "precip_multipliers": [0.3, 0.5, 0.7, 0.9, 1.1],
    "scenario_names":     ["extreem_droog", "droog", "normaal", "nat", "extreem_nat"]
  }
}
```

---

## 4. wflow Koppeling

**Forcing:** ERA5 zomer 2018 (`2018-05-01 → 2018-08-31`), opgeslagen als `data/input/forcing-ijssel-2018.nc`. Download via bestaand `download_forcing.py` met aangepaste periode.

**Config:** `ijssel_config_2018.toml` — kopie van `ijssel_config.toml`, starttime/endtime aangepast naar 2018.

**Inflow-randvoorwaarde:** Ribasim's Westervoort-uitstroom (IJssel-splitsing node) wordt uitgelezen en als `inflow`-variabele in de forcing NC gezet, zodat wflow de juiste bovenstroomse aanvoer krijgt.

**Ensemble:** Hergebruikt `ensemble/scenario_generator.py` en `ensemble/wflow_runner.py`. De 5 `precip_multipliers` komen van de orchestrator (droogte: 0.3–1.1 in plaats van neerslag-verhoging).

**Output:** `multimodel_data/ensemble/outputs/ensemble_stats.json` — zelfde formaat als het bestaande ensemble.

---

## 5. Analyse & output

`analysis.py` combineert beide resultaten in `multimodel_data/outputs/multimodel_stats.json`:

```json
{
  "ribasim": {
    "nodes": [
      {"name": "IJssel-Kampen", "mean_level": 0.27, "threshold": 0.5, "deficit_pct": 46}
    ],
    "critical_node": "IJssel-Kampen",
    "run_date": "2026-06-04"
  },
  "orchestrator": {
    "trigger_reason": "IJssel-Kampen 47% onder drempelstand",
    "llm_explanation": "..."
  },
  "ensemble": {
    "scenarios": [...],
    "timeseries": {"dates": [...], "q_p10": [...], "q_mean": [...], "q_p90": [...]}
  }
}
```

---

## 6. Bestandsstructuur

```
waterlab/
  multimodel/
    __init__.py
    ribasim_runner.py        # bouwt Ribasim netwerk + draait simulatie
    orchestrator.py           # AI beslissingslogica
    wflow_trigger.py          # triggert wflow ensemble met orchestrator-params
    analysis.py               # combineert Ribasim + wflow → multimodel_stats.json
    main.py                   # pipeline entry point (run_pipeline + CLI)
    config/
      settings.yaml           # netwerk-drempelwaarden, llm-config, paden
    tests/
      test_multimodel.py      # 4 unit tests
  run_multimodel.py           # top-level CLI wrapper
  multimodel_data/            # runtime data (gitignored)
    ribasim/
    ensemble/
    outputs/
  wflow_ijssel/
    data/input/
      forcing-ijssel-2018.nc  # ERA5 zomer 2018 (download stap)
    ijssel_config_2018.toml   # wflow config voor 2018-periode
    dashboard/
      server.py               # + /api/multimodel endpoint
      index.html              # + Multimodel tab
      app.js                  # + loadMultimodel(), renderMultimodelMap()
```

---

## 7. Dashboard — Multimodel tab

**Tab:** `<button data-year="multimodel">Multimodel</button>` (na Ensemble AI tab), lichtblauw kleurschema (`#1565c0`).

**Layout (van boven naar beneden):**

1. **Leaflet-kaart** (hoogte 350px): OpenStreetMap achtergrond, rivierassen als blauwe polylijnen, Basin-knopen als cirkels gekleurd naar deficit (groen 0–20% / geel 20–50% / rood >50%), kritieke knoop pulserende rode rand, popup met naam + waterstand + deficit%.

2. **AI-beslissingsblok** (zelfde stijl als ensemble LLM-blok): toont `trigger_reason` + `llm_explanation`.

3. **Ensemble P10/mean/P90 grafiek** (Plotly, hergebruikt `renderEnsembleChart()`).

4. **Scenario-tabel** (hergebruikt `renderEnsembleScenarios()`).

**`/api/multimodel` endpoint:** leest `multimodel_stats.json`, retourneert `{"available": false}` als bestand ontbreekt.

---

## 8. Tests

`multimodel/tests/test_multimodel.py`:

- `test_ribasim_network_has_correct_nodes`: bouw netwerk, controleer dat alle 10 knopen aanwezig zijn
- `test_orchestrator_selects_critical_node`: mock Ribasim-output met bekende niveaus → orchestrator selecteert knoop met hoogste deficit
- `test_analysis_output_format`: mock Ribasim + mock ensemble-output → `multimodel_stats.json` heeft vereiste sleutels
- `test_api_returns_unavailable_when_no_data`: `/api/multimodel` retourneert `{"available": false}` zonder databestand

---

## 9. Implementatievolgorde

1. ERA5 2018 forcing downloaden + `ijssel_config_2018.toml`
2. `ribasim_runner.py` — netwerk bouwen + draaien
3. `orchestrator.py` — deficit scoring + LLM
4. `wflow_trigger.py` — ensemble koppeling
5. `analysis.py` + `multimodel_stats.json`
6. Tests
7. `main.py` + `run_multimodel.py` CLI
8. Dashboard: `/api/multimodel` + Multimodel tab (Leaflet + grafiek)
