# IJssel Waterlab

**Experimentele onderzoeksomgeving voor hydrologische modellering op de IJssel**

🌐 **Live demo:** [waterlab.felixisfelix.com](https://waterlab.felixisfelix.com)

---

## Overzicht

IJssel Waterlab is een interactief dashboard dat historische overstromingen, droogteperiodes en toekomstvoorspellingen simuleert voor het IJssel-stroomgebied. Het systeem combineert een gedistribueerd hydrologisch model, een hydraulisch netwerkmodel en een AI-orchestrator, en draait volledig op een NVIDIA Jetson AGX Orin (ARM64) aan de rand van het netwerk.

Het project is nadrukkelijk **experimenteel**: het dient als testomgeving voor het koppelen van verschillende modeltypen en AI-systemen in een realistisch waterbeheersscenario.

---

## Experimenten

| Tab | Beschrijving |
|-----|-------------|
| **Jan 1995 – Hoogwater** | Extreme afvoerpiek op de IJssel, gesimuleerd met ERA5-Land forcing |
| **Zomer 2018 – Droogte** | Langdurige laagwatersituatie, drempelwaarden per knooppunt |
| **Jul 2021 – Overstroming** | Meuse-gelinkte piekaanvoer na extreme neerslag |
| **14-daagse voorspelling** | Operationele run met recente ERA5 forcing |
| **Ensemble AI** | Wflow ensemble ×5 met stochastische perturbaties, onzekerheidsbanden |
| **Multimodel pipeline** | Ribasim → LLM-orchestrator → wflow ensemble → analyse |

---

## Architectuur

```
ERA5-Land forcing
       │
       ▼
  wflow SBM                 ← gedistribueerd neerslagoverschot-model (Julia)
  (afvoer per cel)
       │
       ▼
  Ribasim netwerk           ← hydraulisch routeringsmodel (Python + Julia)
  (3 parallel takken:
   IJssel / Neder-Rijn / Lek)
       │
       ▼
  LLM orchestrator          ← Qwen2.5-32B, beslist ensemble-parameters
       │
       ▼
  wflow ensemble ×5         ← parallelle runs met gestoorde parameters
       │
       ▼
  Dashboard (FastAPI)       ← MapLibre GL · Plotly · deck.gl
```

---

## Tech stack

| Laag | Technologie |
|------|-------------|
| Hydrologisch model | [wflow SBM](https://deltares.github.io/Wflow.jl/) (Julia) |
| Hydraulisch netwerk | [Ribasim](https://deltares.github.io/Ribasim/) (Python 3.13 + Julia) |
| Simulatie runtime | Julia 1.12.5 op ARM64 (JIT, geen binary release) |
| Klimaatdata | ERA5-Land (0.1° grid, hourly, ~248 MB NetCDF) |
| AI orchestrator | Qwen2.5-32B (lokaal via vLLM) |
| API / server | FastAPI + uvicorn (poort 8000) |
| Frontend | MapLibre GL, Plotly, deck.gl, vanilla JS |
| Tunneling | Cloudflare Tunnel (IPv4, edge-ip-version: 4) |
| Hardware | NVIDIA Jetson AGX Orin, ARM64, Ubuntu 22.04 |

---

## Lokaal draaien

```bash
# Vereisten: Python 3.10, Julia 1.12.5, Python 3.13 venv voor Ribasim
cd /home/bob/waterlab

# Dashboard starten
uvicorn wflow_ijssel.dashboard.main:app --host 0.0.0.0 --port 8000

# Open http://localhost:8000
```

Het dashboard is ook publiek bereikbaar via **[https://waterlab.felixisfelix.com](https://waterlab.felixisfelix.com)**.

---

## Ribasim op ARM64

De officiële Ribasim Linux binary is x86-64 en werkt niet op aarch64. De oplossing:

1. **Model bouwen** — Python 3.13 venv (`/home/bob/waterlab/.venv313/`) met `ribasim` package
2. **Simulatie draaien** — Julia met het `Ribasim` Julia-package: `Ribasim.run(toml_path)`

Eerste Julia-run duurt ~32 seconden door JIT-compilatie; daarna aanzienlijk sneller.

---

## Status

> **Experimenteel.** Dit project is een onderzoeks- en leerplatform, geen operationeel systeem. Simulaties zijn indicatief en niet gekalibreerd voor operationele waterbeheerbeslissingen.

---

## Licentie

Persoonlijk onderzoeksproject — geen licentie van toepassing.
