# AI-Orchestrated Multimodel Water System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End-to-end pipeline: Python Rijn/IJssel networkmodel (Ribasim-stijl) → AI orchestrator detecteert kritieke knoop → wflow IJssel droogte-ensemble → Multimodel dashboard-tab met Leaflet-kaart.

**Architecture:** Vier lagen in `waterlab/multimodel/`: networkmodel (pure Python, geen Julia), AI orchestrator (Qwen via llama.cpp), wflow-koppeling (hergebruikt bestaande ensemble pipeline), analyse + dashboard (FastAPI + Leaflet.js). Ribasim Python package werkt niet met Python 3.10 (pandera incompatibiliteit) — daarom een eigen lichtgewicht routing implementatie met dezelfde output-interface.

**Tech Stack:** Python 3.10, NumPy, xarray, PyYAML, requests (LLM), FastAPI (bestaand), Leaflet.js (CDN), bestaande Wflow Julia pipeline.

**Context voor implementeerders:**
- Git repo root: `/home/bob/waterlab/` — alle git-commando's van hier
- Python venv: `/home/bob/waterlab/wflow_ijssel/.venv/` — activeer met `source /home/bob/waterlab/wflow_ijssel/.venv/bin/activate`
- Bestaande ensemble code in: `/home/bob/waterlab/wflow_ijssel/ensemble/`
- Dashboard: `/home/bob/waterlab/wflow_ijssel/dashboard/` (server.py, index.html, app.js)
- LLM server draait op `http://127.0.0.1:8080`, model: `qwen2.5-32b-instruct-q4_k_m-00001-of-00005.gguf`
- Data output naar: `/home/bob/waterlab/multimodel_data/`
- wflow draait ERA5 1994-1995 forcing; voor droogte hergebruiken we de bestaande forcing met lage precip-multipliers (0.1–0.5) i.p.v. een nieuwe ERA5 download

---

## Bestandsstructuur

```
waterlab/
  multimodel/
    __init__.py                 # leeg
    network_model.py            # Rijn/IJssel routing model (Ribasim-stijl)
    orchestrator.py             # AI beslissingslogica + LLM
    wflow_trigger.py            # triggert wflow ensemble met orchestrator-params
    analysis.py                 # combineert network + wflow → multimodel_stats.json
    main.py                     # pipeline entry point
    config/
      settings.yaml             # netwerk-drempelwaarden, llm-config, paden
    tests/
      __init__.py
      test_network_model.py
      test_orchestrator.py
      test_analysis.py
  run_multimodel.py             # top-level CLI (naast run_ensemble.py)
  wflow_ijssel/
    dashboard/
      server.py                 # + /api/multimodel endpoint (toevoegen)
      index.html                # + Multimodel tab (toevoegen)
      app.js                    # + loadMultimodel(), renderMultimodelMap() (toevoegen)
  multimodel_data/              # runtime (gitignored)
    outputs/
      multimodel_stats.json
```

---

## Task 1: Project scaffold + config

**Files:**
- Create: `waterlab/multimodel/__init__.py`
- Create: `waterlab/multimodel/config/settings.yaml`
- Create: `waterlab/multimodel/tests/__init__.py`
- Create: `waterlab/run_multimodel.py`

- [ ] **Stap 1: Maak directories aan**

```bash
cd /home/bob/waterlab
mkdir -p multimodel/config multimodel/tests multimodel_data/outputs
```

- [ ] **Stap 2: Schrijf `multimodel/__init__.py`**

```python
```
(leeg bestand)

- [ ] **Stap 3: Schrijf `multimodel/tests/__init__.py`**

```python
```
(leeg bestand)

- [ ] **Stap 4: Schrijf `multimodel/config/settings.yaml`**

```yaml
wflow_root: "/home/bob/waterlab/wflow_ijssel"
base_forcing: "data/input/forcing-ijssel.nc"
base_config:  "data/output/ijssel_config.toml"
julia_project: "/home/bob/waterlab/wflow_ijssel"
run_script:   "run_ijssel.jl"
multimodel_data_root: "/home/bob/waterlab/multimodel_data"

network:
  simulation_days: 90
  lobith_base_flow: 600.0
  lobith_amplitude:  150.0
  nodes:
    - name: "IJssel-Kampen"
      lon: 5.921
      lat: 52.555
      threshold_level: 0.5
      flow_fraction: 0.30
    - name: "Neder-Rijn"
      lon: 5.800
      lat: 51.960
      threshold_level: 1.2
      flow_fraction: 0.35
    - name: "Lek"
      lon: 5.000
      lat: 51.900
      threshold_level: 0.8
      flow_fraction: 0.35
    - name: "Pannerdensch-Kanaal"
      lon: 6.000
      lat: 51.850
      threshold_level: 2.0
      flow_fraction: 1.0
  catchment_map:
    "IJssel-Kampen": "ijssel"

llm:
  base_url: "http://127.0.0.1:8080"
  model: "qwen2.5-32b-instruct-q4_k_m-00001-of-00005.gguf"
  max_tokens: 400
  temperature: 0.3

analysis:
  station_lon: 5.921
  station_lat: 52.555
  threshold_q: 800.0

scenarios:
  values: [0.10, 0.25, 0.40, 0.60, 0.80]
  names:  ["extreem_droog", "droog", "matig_droog", "licht_droog", "normaal"]
```

- [ ] **Stap 5: Schrijf `run_multimodel.py`**

```python
"""Top-level CLI voor de multimodel pipeline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from multimodel.main import main

if __name__ == "__main__":
    main()
```

- [ ] **Stap 6: Commit**

```bash
cd /home/bob/waterlab
git add multimodel/ run_multimodel.py
git commit -m "feat: multimodel scaffold + config"
```

---

## Task 2: `network_model.py` — Rijn/IJssel routing

**Files:**
- Create: `waterlab/multimodel/network_model.py`
- Create: `waterlab/multimodel/tests/test_network_model.py`

Het model simuleert dagelijks debiet per knoop via een eenvoudige fractie-routing:
- Lobith inflow: sinusvorm rond 600 m³/s (droogtescenario)
- Per knoop: `flow = upstream_flow * flow_fraction`
- Waterstand: `level = flow / 1000.0` (lineaire benadering, m NAP)
- Output: dict per knoop met `flows` (lijst) en `levels` (lijst) over `simulation_days` tijdstappen

- [ ] **Stap 1: Schrijf de falende test**

Maak `/home/bob/waterlab/multimodel/tests/test_network_model.py`:

```python
"""Tests voor network_model.py."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from multimodel.network_model import simulate_network


def test_simulate_network_returns_all_nodes():
    settings = {
        "network": {
            "simulation_days": 10,
            "lobith_base_flow": 600.0,
            "lobith_amplitude": 150.0,
            "nodes": [
                {"name": "IJssel-Kampen", "lon": 5.921, "lat": 52.555,
                 "threshold_level": 0.5, "flow_fraction": 0.30},
                {"name": "Neder-Rijn",    "lon": 5.800, "lat": 51.960,
                 "threshold_level": 1.2, "flow_fraction": 0.35},
            ],
            "catchment_map": {"IJssel-Kampen": "ijssel"},
        }
    }
    result = simulate_network(settings)
    assert "nodes" in result
    assert len(result["nodes"]) == 2
    assert result["nodes"][0]["name"] == "IJssel-Kampen"


def test_simulate_network_flow_values():
    settings = {
        "network": {
            "simulation_days": 10,
            "lobith_base_flow": 600.0,
            "lobith_amplitude":   0.0,
            "nodes": [
                {"name": "IJssel-Kampen", "lon": 5.921, "lat": 52.555,
                 "threshold_level": 0.5, "flow_fraction": 0.30},
            ],
            "catchment_map": {"IJssel-Kampen": "ijssel"},
        }
    }
    result = simulate_network(settings)
    node = result["nodes"][0]
    assert len(node["flows"]) == 10
    assert abs(node["flows"][0] - 180.0) < 0.1


def test_simulate_network_deficit_computed():
    settings = {
        "network": {
            "simulation_days": 10,
            "lobith_base_flow": 600.0,
            "lobith_amplitude":   0.0,
            "nodes": [
                {"name": "IJssel-Kampen", "lon": 5.921, "lat": 52.555,
                 "threshold_level": 0.5, "flow_fraction": 0.30},
            ],
            "catchment_map": {"IJssel-Kampen": "ijssel"},
        }
    }
    result = simulate_network(settings)
    node = result["nodes"][0]
    # level = flow/1000 = 0.18 m, threshold = 0.5 m → deficit > 0
    assert node["deficit_pct"] > 0
    assert node["mean_level"] < node["threshold_level"]
```

- [ ] **Stap 2: Verifieer dat de test faalt**

```bash
cd /home/bob/waterlab
source wflow_ijssel/.venv/bin/activate
python -m pytest multimodel/tests/test_network_model.py -v 2>&1 | tail -10
```

Verwacht: `ImportError` of `ModuleNotFoundError`

- [ ] **Stap 3: Schrijf `multimodel/network_model.py`**

```python
"""Lichtgewicht Rijn/IJssel routeringsmodel (Ribasim-stijl, pure Python)."""
from __future__ import annotations
import math
import numpy as np


def simulate_network(settings: dict) -> dict:
    """
    Simuleert dagelijks debiet en waterstand per knoop.

    Retourneert:
      {
        "nodes": [
          {
            "name": str,
            "lon": float, "lat": float,
            "flows": list[float],       # m³/s per dag
            "levels": list[float],      # m NAP per dag
            "mean_level": float,
            "threshold_level": float,
            "deficit_pct": float,       # % onder drempelstand
            "flow_fraction": float,
          },
          ...
        ],
        "days": int,
      }
    """
    cfg   = settings["network"]
    days  = cfg["simulation_days"]
    base  = cfg["lobith_base_flow"]
    amp   = cfg["lobith_amplitude"]

    lobith = [base + amp * math.sin(2 * math.pi * t / 90) for t in range(days)]

    results = []
    for node in cfg["nodes"]:
        frac   = node["flow_fraction"]
        flows  = [q * frac for q in lobith]
        levels = [q / 1000.0 for q in flows]
        mean_l = float(np.mean(levels))
        thresh = node["threshold_level"]
        deficit = max(0.0, (thresh - mean_l) / thresh * 100.0)

        results.append({
            "name":            node["name"],
            "lon":             node["lon"],
            "lat":             node["lat"],
            "flows":           [round(f, 1) for f in flows],
            "levels":          [round(l, 4) for l in levels],
            "mean_level":      round(mean_l, 4),
            "threshold_level": thresh,
            "deficit_pct":     round(deficit, 1),
            "flow_fraction":   frac,
        })

    return {"nodes": results, "days": days}
```

- [ ] **Stap 4: Verifieer dat de tests slagen**

```bash
cd /home/bob/waterlab
source wflow_ijssel/.venv/bin/activate
python -m pytest multimodel/tests/test_network_model.py -v 2>&1 | tail -10
```

Verwacht: `3 passed`

- [ ] **Stap 5: Commit**

```bash
cd /home/bob/waterlab
git add multimodel/network_model.py multimodel/tests/test_network_model.py
git commit -m "feat: network_model Rijn/IJssel routing (pure Python)"
```

---

## Task 3: `orchestrator.py` — AI beslissingslogica

**Files:**
- Create: `waterlab/multimodel/orchestrator.py`
- Create: `waterlab/multimodel/tests/test_orchestrator.py`

- [ ] **Stap 1: Schrijf de falende test**

Maak `/home/bob/waterlab/multimodel/tests/test_orchestrator.py`:

```python
"""Tests voor orchestrator.py."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from multimodel.orchestrator import select_critical_node, build_orchestrator_result


def _make_nodes(deficits):
    return [
        {"name": f"node_{i}", "deficit_pct": d, "mean_level": 0.3,
         "threshold_level": 0.5, "lon": 5.0 + i, "lat": 52.0}
        for i, d in enumerate(deficits)
    ]


def test_select_critical_node_picks_highest_deficit():
    nodes = _make_nodes([10.0, 55.0, 30.0])
    result = select_critical_node(nodes)
    assert result["name"] == "node_1"
    assert result["deficit_pct"] == 55.0


def test_build_orchestrator_result_maps_catchment():
    nodes = _make_nodes([47.0])
    nodes[0]["name"] = "IJssel-Kampen"
    catchment_map = {"IJssel-Kampen": "ijssel"}
    multipliers   = [0.10, 0.25, 0.40, 0.60, 0.80]
    names         = ["extreem_droog", "droog", "matig_droog", "licht_droog", "normaal"]

    result = build_orchestrator_result(
        critical_node=nodes[0],
        catchment_map=catchment_map,
        multipliers=multipliers,
        scenario_names=names,
        llm_explanation="Test uitleg.",
    )
    assert result["selected_catchment"] == "ijssel"
    assert result["critical_node"] == "IJssel-Kampen"
    assert result["deficit_pct"] == 47.0
    assert len(result["wflow_params"]["precip_multipliers"]) == 5
    assert result["llm_explanation"] == "Test uitleg."


def test_build_orchestrator_result_unknown_catchment():
    nodes = _make_nodes([20.0])
    nodes[0]["name"] = "Onbekend"
    result = build_orchestrator_result(
        critical_node=nodes[0],
        catchment_map={"IJssel-Kampen": "ijssel"},
        multipliers=[0.5],
        scenario_names=["test"],
        llm_explanation="",
    )
    assert result["selected_catchment"] is None
```

- [ ] **Stap 2: Verifieer dat de test faalt**

```bash
cd /home/bob/waterlab
source wflow_ijssel/.venv/bin/activate
python -m pytest multimodel/tests/test_orchestrator.py -v 2>&1 | tail -10
```

Verwacht: `ImportError`

- [ ] **Stap 3: Schrijf `multimodel/orchestrator.py`**

```python
"""AI orchestrator: selecteert kritieke knoop en genereert wflow-parameters."""
from __future__ import annotations
import json
import requests


SYSTEM_PROMPT = """Je bent een hydroloog die een waternetwerk analyseert tijdens een droogteperiode.
Geef een beknopte beslissingsmotivatie in het Nederlands.
Noem: welke knoop kritiek is, het waterdeficit, en waarom detailmodellering nodig is.
Maximaal 150 woorden. Schrijf doorlopende tekst, geen opsomming."""


def select_critical_node(nodes: list[dict]) -> dict:
    """Retourneert de knoop met het hoogste deficit_pct."""
    return max(nodes, key=lambda n: n["deficit_pct"])


def build_llm_prompt(critical_node: dict, all_nodes: list[dict]) -> str:
    lines = [
        "Netwerktoestand Rijn/IJssel (droogtescenario zomer 2018):",
    ]
    for n in all_nodes:
        lines.append(
            f"  {n['name']}: gemiddeld peil {n['mean_level']:.3f} m NAP "
            f"(drempel {n['threshold_level']} m, deficit {n['deficit_pct']:.1f}%)"
        )
    lines += [
        "",
        f"Kritieke knoop: {critical_node['name']} ({critical_node['deficit_pct']:.1f}% onder drempel).",
        "Beslis of detailmodellering met wflow nodig is en motiveer waarom.",
    ]
    return "\n".join(lines)


def call_llm(prompt: str, llm_config: dict) -> str:
    payload = {
        "model":    llm_config["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens":  llm_config.get("max_tokens", 400),
        "temperature": llm_config.get("temperature", 0.3),
    }
    resp = requests.post(
        f"{llm_config['base_url']}/v1/chat/completions",
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def build_orchestrator_result(
    critical_node: dict,
    catchment_map: dict,
    multipliers: list[float],
    scenario_names: list[str],
    llm_explanation: str,
) -> dict:
    trigger = (
        f"{critical_node['name']} {critical_node['deficit_pct']:.1f}% "
        f"onder drempelstand van {critical_node['threshold_level']} m NAP"
    )
    return {
        "critical_node":      critical_node["name"],
        "selected_catchment": catchment_map.get(critical_node["name"]),
        "deficit_pct":        critical_node["deficit_pct"],
        "trigger_reason":     trigger,
        "llm_explanation":    llm_explanation,
        "wflow_params": {
            "precip_multipliers": multipliers,
            "scenario_names":     scenario_names,
        },
    }


def orchestrate(network_result: dict, settings: dict) -> dict:
    """
    Volledige orchestratie: selecteer knoop, roep LLM aan, retourneer beslissing.
    network_result: output van simulate_network()
    """
    nodes         = network_result["nodes"]
    critical      = select_critical_node(nodes)
    catchment_map = settings["network"]["catchment_map"]
    multipliers   = settings["scenarios"]["values"]
    names         = settings["scenarios"]["names"]

    prompt      = build_llm_prompt(critical, nodes)
    explanation = call_llm(prompt, settings["llm"])

    return build_orchestrator_result(
        critical_node=critical,
        catchment_map=catchment_map,
        multipliers=multipliers,
        scenario_names=names,
        llm_explanation=explanation,
    )
```

- [ ] **Stap 4: Verifieer dat de tests slagen**

```bash
cd /home/bob/waterlab
source wflow_ijssel/.venv/bin/activate
python -m pytest multimodel/tests/test_orchestrator.py -v 2>&1 | tail -10
```

Verwacht: `4 passed`

- [ ] **Stap 5: Commit**

```bash
cd /home/bob/waterlab
git add multimodel/orchestrator.py multimodel/tests/test_orchestrator.py
git commit -m "feat: orchestrator kritieke knoop selectie + LLM beslissing"
```

---

## Task 4: `wflow_trigger.py` — wflow ensemble koppeling

**Files:**
- Create: `waterlab/multimodel/wflow_trigger.py`

Hergebruikt `wflow_ijssel/ensemble/scenario_generator.py` en `wflow_ijssel/ensemble/wflow_runner.py` en `wflow_ijssel/ensemble/output_collector.py`. De orchestrator levert de `precip_multipliers` en `scenario_names`; deze worden als settings doorgegeven aan de bestaande ensemble functies.

- [ ] **Stap 1: Schrijf `multimodel/wflow_trigger.py`**

```python
"""Triggert wflow ensemble met parameters van de orchestrator."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "wflow_ijssel" / "ensemble"))

from scenario_generator import generate_scenarios
from wflow_runner import run_scenario
from output_collector import collect, save_json


def run_wflow_ensemble(orchestrator_result: dict, settings: dict, out_dir: Path) -> list[dict]:
    """
    Draait wflow ensemble met scenario's uit orchestrator_result.
    Retourneert lijst van collect()-resultaten (één per scenario).
    """
    wflow_params = orchestrator_result["wflow_params"]

    ensemble_settings = {
        "wflow_root":          settings["wflow_root"],
        "base_forcing":        settings["base_forcing"],
        "base_config":         settings["base_config"],
        "julia_project":       settings["julia_project"],
        "run_script":          settings["run_script"],
        "scenarios": {
            "parameter": "precip_multiplier",
            "values":    wflow_params["precip_multipliers"],
            "names":     wflow_params["scenario_names"],
        },
    }

    scenarios   = generate_scenarios(ensemble_settings, out_dir)
    outputs_dir = out_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for sc in scenarios:
        print(f"  → Run: {sc['name']} (multiplier={sc['multiplier']})")
        output_nc = run_scenario(
            sc,
            julia_project=settings["julia_project"],
            run_script=str(Path(settings["wflow_root"]) / settings["run_script"]),
        )
        result = collect(
            output_nc=output_nc,
            station_lon=settings["analysis"]["station_lon"],
            station_lat=settings["analysis"]["station_lat"],
            threshold=settings["analysis"]["threshold_q"],
            delete_nc=True,
        )
        result["name"]       = sc["name"]
        result["multiplier"] = sc["multiplier"]
        save_json(result, outputs_dir / f"{sc['name']}.json")
        print(f"  ✓ {sc['name']}: piek={result['peak_q']} m³/s")
        results.append(result)

    return results
```

- [ ] **Stap 2: Smoke test (geen apart testbestand — verifieer import)**

```bash
cd /home/bob/waterlab
source wflow_ijssel/.venv/bin/activate
python3 -c "from multimodel.wflow_trigger import run_wflow_ensemble; print('import ok')"
```

Verwacht: `import ok`

- [ ] **Stap 3: Commit**

```bash
cd /home/bob/waterlab
git add multimodel/wflow_trigger.py
git commit -m "feat: wflow_trigger hergebruikt ensemble pipeline voor droogte-runs"
```

---

## Task 5: `analysis.py` — combineer outputs

**Files:**
- Create: `waterlab/multimodel/analysis.py`
- Create: `waterlab/multimodel/tests/test_analysis.py`

- [ ] **Stap 1: Schrijf de falende test**

Maak `/home/bob/waterlab/multimodel/tests/test_analysis.py`:

```python
"""Tests voor analysis.py."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from multimodel.analysis import build_multimodel_stats


def _mock_network():
    return {
        "nodes": [
            {"name": "IJssel-Kampen", "lon": 5.921, "lat": 52.555,
             "mean_level": 0.18, "threshold_level": 0.5, "deficit_pct": 64.0,
             "flows": [180.0] * 10, "levels": [0.18] * 10, "flow_fraction": 0.3},
        ],
        "days": 10,
    }


def _mock_orchestrator():
    return {
        "critical_node":      "IJssel-Kampen",
        "selected_catchment": "ijssel",
        "deficit_pct":        64.0,
        "trigger_reason":     "IJssel-Kampen 64.0% onder drempelstand",
        "llm_explanation":    "Test motivatie.",
        "wflow_params": {
            "precip_multipliers": [0.1, 0.25],
            "scenario_names":     ["extreem_droog", "droog"],
        },
    }


def _mock_ensemble():
    return [
        {"name": "extreem_droog", "multiplier": 0.1, "peak_q": 120.0,
         "peak_date": "2018-07-15", "days_above_threshold": 0,
         "q": [100.0, 120.0], "h": [0.5, 0.6], "dates": ["2018-07-01", "2018-07-02"]},
        {"name": "droog", "multiplier": 0.25, "peak_q": 250.0,
         "peak_date": "2018-07-14", "days_above_threshold": 0,
         "q": [200.0, 250.0], "h": [0.8, 0.9], "dates": ["2018-07-01", "2018-07-02"]},
    ]


def test_build_multimodel_stats_structure():
    stats = build_multimodel_stats(_mock_network(), _mock_orchestrator(), _mock_ensemble())
    assert "ribasim" in stats
    assert "orchestrator" in stats
    assert "ensemble" in stats


def test_build_multimodel_stats_ribasim_section():
    stats = build_multimodel_stats(_mock_network(), _mock_orchestrator(), _mock_ensemble())
    r = stats["ribasim"]
    assert r["critical_node"] == "IJssel-Kampen"
    assert len(r["nodes"]) == 1
    assert r["nodes"][0]["deficit_pct"] == 64.0


def test_build_multimodel_stats_ensemble_section():
    stats = build_multimodel_stats(_mock_network(), _mock_orchestrator(), _mock_ensemble())
    e = stats["ensemble"]
    assert len(e["scenarios"]) == 2
    assert "timeseries" in e
    assert "q_mean" in e["timeseries"]
```

- [ ] **Stap 2: Verifieer dat de test faalt**

```bash
cd /home/bob/waterlab
source wflow_ijssel/.venv/bin/activate
python -m pytest multimodel/tests/test_analysis.py -v 2>&1 | tail -10
```

Verwacht: `ImportError`

- [ ] **Stap 3: Schrijf `multimodel/analysis.py`**

```python
"""Combineert networkmodel + wflow ensemble → multimodel_stats.json."""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np


def build_multimodel_stats(
    network_result: dict,
    orchestrator_result: dict,
    ensemble_results: list[dict],
) -> dict:
    """
    Combineert alle pipeline-outputs in één JSON-struct voor het dashboard.
    """
    # Ensemble statistieken
    q_matrix = np.array([r["q"] for r in ensemble_results])
    q_mean   = [round(float(v), 1) for v in q_matrix.mean(axis=0)]
    q_p10    = [round(float(v), 1) for v in np.percentile(q_matrix, 10, axis=0)]
    q_p90    = [round(float(v), 1) for v in np.percentile(q_matrix, 90, axis=0)]
    dates    = ensemble_results[0]["dates"]

    return {
        "ribasim": {
            "critical_node": orchestrator_result["critical_node"],
            "nodes": [
                {
                    "name":            n["name"],
                    "lon":             n["lon"],
                    "lat":             n["lat"],
                    "mean_level":      n["mean_level"],
                    "threshold_level": n["threshold_level"],
                    "deficit_pct":     n["deficit_pct"],
                }
                for n in network_result["nodes"]
            ],
        },
        "orchestrator": {
            "trigger_reason":     orchestrator_result["trigger_reason"],
            "selected_catchment": orchestrator_result["selected_catchment"],
            "llm_explanation":    orchestrator_result["llm_explanation"],
        },
        "ensemble": {
            "scenarios": [
                {
                    "name":       r["name"],
                    "multiplier": r["multiplier"],
                    "peak_q":     r["peak_q"],
                    "peak_date":  r["peak_date"],
                    "days_above": r["days_above_threshold"],
                }
                for r in ensemble_results
            ],
            "timeseries": {
                "dates":  dates,
                "q_p10":  q_p10,
                "q_mean": q_mean,
                "q_p90":  q_p90,
            },
        },
    }


def save_stats(stats: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2))
```

- [ ] **Stap 4: Verifieer dat de tests slagen**

```bash
cd /home/bob/waterlab
source wflow_ijssel/.venv/bin/activate
python -m pytest multimodel/tests/test_analysis.py -v 2>&1 | tail -10
```

Verwacht: `3 passed`

- [ ] **Stap 5: Commit**

```bash
cd /home/bob/waterlab
git add multimodel/analysis.py multimodel/tests/test_analysis.py
git commit -m "feat: analysis.py combineert network + ensemble → multimodel_stats"
```

---

## Task 6: `main.py` — pipeline entry point

**Files:**
- Create: `waterlab/multimodel/main.py`

- [ ] **Stap 1: Schrijf `multimodel/main.py`**

```python
"""Multimodel pipeline: networkmodel → orchestrator → wflow → analyse."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from network_model import simulate_network
from orchestrator import orchestrate
from wflow_trigger import run_wflow_ensemble
from analysis import build_multimodel_stats, save_stats


def run_pipeline(settings_path: Path, dry_run: bool = False) -> None:
    with open(settings_path) as f:
        settings = yaml.safe_load(f)

    out_dir     = Path(settings["multimodel_data_root"])
    outputs_dir = out_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    print("=== Stap 1: Netwerkmodel (Rijn/IJssel) ===")
    network_result = simulate_network(settings)
    print(f"  {len(network_result['nodes'])} knopen gesimuleerd over {network_result['days']} dagen")
    for n in network_result["nodes"]:
        print(f"  {n['name']:25} deficit={n['deficit_pct']:.1f}%  peil={n['mean_level']:.3f} m NAP")

    print("\n=== Stap 2: AI Orchestrator ===")
    orchestrator_result = orchestrate(network_result, settings)
    print(f"  Kritieke knoop: {orchestrator_result['critical_node']}")
    print(f"  Geselecteerd stroomgebied: {orchestrator_result['selected_catchment']}")
    print(f"  Reden: {orchestrator_result['trigger_reason']}")

    if dry_run:
        print("[dry-run] Geen wflow-runs uitgevoerd.")
        return

    if orchestrator_result["selected_catchment"] is None:
        print("  Geen wflow-koppeling gevonden, pipeline stopt.")
        return

    print("\n=== Stap 3: wflow droogte-ensemble ===")
    ensemble_dir     = out_dir / "ensemble"
    ensemble_results = run_wflow_ensemble(orchestrator_result, settings, ensemble_dir)

    print("\n=== Stap 4: Resultaten combineren ===")
    stats      = build_multimodel_stats(network_result, orchestrator_result, ensemble_results)
    stats_path = outputs_dir / "multimodel_stats.json"
    save_stats(stats, stats_path)
    print(f"  Opgeslagen: {stats_path}")

    print("\n=== Klaar ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="Multimodel Water Pipeline")
    parser.add_argument(
        "--settings",
        default=str(Path(__file__).parent / "config" / "settings.yaml"),
        help="Pad naar settings.yaml",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Draai alleen stap 1+2, geen wflow")
    args = parser.parse_args()
    run_pipeline(Path(args.settings), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Stap 2: Smoke test dry-run**

```bash
cd /home/bob/waterlab
source wflow_ijssel/.venv/bin/activate
python3 run_multimodel.py --dry-run 2>&1
```

Verwacht: stap 1 + stap 2 printen zonder fouten, `[dry-run]` bericht.

- [ ] **Stap 3: Commit**

```bash
cd /home/bob/waterlab
git add multimodel/main.py
git commit -m "feat: main.py multimodel pipeline entry point"
```

---

## Task 7: Dashboard — `/api/multimodel` endpoint

**Files:**
- Modify: `waterlab/wflow_ijssel/dashboard/server.py`

- [ ] **Stap 1: Lees de huidige server.py** (om het patroon te volgen)

De bestaande `/api/ensemble` endpoint staat op regels 114–131. Het patroon is identiek.

- [ ] **Stap 2: Voeg `/api/multimodel` toe aan `server.py`**

Voeg na de `/api/ensemble` endpoint (na regel 131) toe:

```python
MULTIMODEL_DIR = Path("/home/bob/waterlab/multimodel_data/outputs")


@app.get("/api/multimodel")
def get_multimodel():
    stats_path = MULTIMODEL_DIR / "multimodel_stats.json"
    if not stats_path.exists():
        return JSONResponse({"available": False})
    try:
        stats = json.loads(stats_path.read_text())
    except Exception:
        return JSONResponse({"available": False})
    return JSONResponse({"available": True, **stats})
```

- [ ] **Stap 3: Herstart uvicorn en verifieer**

```bash
kill $(cat /tmp/uvicorn.pid) 2>/dev/null
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
nohup python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn.log 2>&1 &
echo $! > /tmp/uvicorn.pid
sleep 3
curl -s http://localhost:8000/api/multimodel
```

Verwacht: `{"available":false}`

- [ ] **Stap 4: Commit**

```bash
cd /home/bob/waterlab
git add wflow_ijssel/dashboard/server.py
git commit -m "feat: /api/multimodel endpoint in dashboard server"
```

---

## Task 8: Dashboard — Multimodel tab (HTML + JS)

**Files:**
- Modify: `waterlab/wflow_ijssel/dashboard/index.html`
- Modify: `waterlab/wflow_ijssel/dashboard/app.js`

**Context:** De bestaande Ensemble AI tab gebruikt `#ensemble-panel`, `.llm-block`, `.ensemble-scenario-table`. De Multimodel tab volgt hetzelfde patroon maar voegt een Leaflet-kaart toe. Leaflet via CDN in de `<head>`.

- [ ] **Stap 1: Voeg Leaflet CDN toe aan `index.html`**

Voeg in de `<head>` toe na bestaande `<link>` / `<script>` tags:

```html
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
```

- [ ] **Stap 2: Voeg Multimodel tab-knop toe aan `index.html`**

Voeg de Multimodel-knop toe na de Ensemble AI tab-knop (zoek op `data-year="ensemble"`):

```html
<button class="year-tab" data-year="multimodel">Multimodel</button>
```

- [ ] **Stap 3: Voeg CSS toe aan `index.html`**

Voeg in het `<style>` blok toe (na de bestaande `.active-ensemble` regel):

```css
.year-tab.active-multimodel { background: #1565c0; }
#multimodel-panel { display: none; }
#multimodel-panel.visible { display: block; }
#multimodel-map { height: 350px; width: 100%; border-radius: 8px; margin-bottom: 1rem; }
```

- [ ] **Stap 4: Voeg Multimodel panel toe aan `index.html`**

Voeg na het `#ensemble-panel` div toe:

```html
<div id="multimodel-panel">
  <div id="multimodel-unavailable" style="display:none; padding:2rem; text-align:center; color:#888;">
    Multimodel pipeline nog niet uitgevoerd. Draai: <code>python run_multimodel.py</code>
  </div>
  <div id="multimodel-content" style="display:none;">
    <div id="multimodel-map"></div>
    <div class="llm-block" style="border-left:4px solid #1565c0;">
      <strong>AI Beslissing</strong>
      <p id="mm-trigger-reason" style="font-weight:bold; color:#1565c0;"></p>
      <p id="mm-llm-text"></p>
    </div>
    <h3>wflow Droogte-ensemble</h3>
    <div id="mm-ensemble-chart"></div>
    <table class="ensemble-scenario-table">
      <thead><tr><th>Scenario</th><th>Multiplier</th><th>Piek (m³/s)</th><th>Piekdatum</th><th>Dagen &gt; drempel</th></tr></thead>
      <tbody id="mm-scenario-tbody"></tbody>
    </table>
  </div>
</div>
```

- [ ] **Stap 5: Voeg `switchYear` multimodel-case toe in `app.js`**

Zoek in `app.js` de `switchYear` functie. Voeg toe na het `ensemble`-geval:

```javascript
if (year === "multimodel") {
  hideAll();
  document.getElementById("multimodel-panel").classList.add("visible");
  banner.textContent = "Multimodel · Rijn/IJssel netwerk → AI → wflow droogte-ensemble";
  document.getElementById("alert-badge").textContent = "🌐 Multimodel";
  document.getElementById("alert-badge").style.background = "#1565c0";
  document.body.className = "";
  loadMultimodel();
  return;
}
```

- [ ] **Stap 6: Voeg `loadMultimodel()` en renderfuncties toe aan `app.js`**

Voeg onderaan `app.js` toe:

```javascript
let mmLeafletMap = null;

async function loadMultimodel() {
  const unavail = document.getElementById("multimodel-unavailable");
  const content = document.getElementById("multimodel-content");
  try {
    const resp = await fetch("/api/multimodel");
    const data = await resp.json();
    if (!data.available) {
      unavail.style.display = "block";
      content.style.display = "none";
      return;
    }
    unavail.style.display = "none";
    content.style.display = "block";
    renderMultimodelMap(data);
    document.getElementById("mm-trigger-reason").textContent =
      data.orchestrator.trigger_reason;
    document.getElementById("mm-llm-text").textContent =
      data.orchestrator.llm_explanation;
    renderMultimodelChart(data);
    renderMultimodelScenarios(data);
  } catch (e) {
    unavail.style.display = "block";
    content.style.display = "none";
  }
}

function renderMultimodelMap(d) {
  if (mmLeafletMap) {
    mmLeafletMap.remove();
    mmLeafletMap = null;
  }
  mmLeafletMap = L.map("multimodel-map").setView([52.1, 5.9], 8);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap"
  }).addTo(mmLeafletMap);

  // Rivier-assen (vereenvoudigd Rijn/IJssel netwerk)
  const rivers = [
    [[51.862, 6.112], [51.850, 6.000], [51.960, 5.970]],  // Lobith → splitsing
    [[51.960, 5.970], [52.252, 6.157], [52.555, 5.921]],  // IJssel
    [[51.960, 5.970], [51.960, 5.800], [51.900, 5.000]],  // Neder-Rijn/Lek
  ];
  rivers.forEach(r => L.polyline(r, {color: "#1565c0", weight: 3, opacity: 0.7})
    .addTo(mmLeafletMap));

  // Knopen
  const criticalNode = d.ribasim.critical_node;
  d.ribasim.nodes.forEach(node => {
    const deficit = node.deficit_pct;
    const color   = deficit > 50 ? "#d32f2f" : deficit > 20 ? "#f57c00" : "#388e3c";
    const isCrit  = node.name === criticalNode;
    const circle  = L.circleMarker([node.lat, node.lon], {
      radius:      isCrit ? 14 : 10,
      fillColor:   color,
      color:       isCrit ? "#000" : "#fff",
      weight:      isCrit ? 3 : 1,
      fillOpacity: 0.85,
    }).addTo(mmLeafletMap);
    circle.bindPopup(
      `<b>${node.name}</b><br>` +
      `Peil: ${node.mean_level.toFixed(3)} m NAP<br>` +
      `Drempel: ${node.threshold_level} m<br>` +
      `Deficit: <b>${node.deficit_pct.toFixed(1)}%</b>` +
      (isCrit ? "<br><b>⚠ Kritieke knoop</b>" : "")
    );
  });

  // Lobith marker
  L.marker([51.862, 6.112])
    .bindPopup("<b>Lobith</b><br>Bovenstroomse inflow")
    .addTo(mmLeafletMap);
}

function renderMultimodelChart(d) {
  const ts = d.ensemble.timeseries;
  const traces = [
    {x: ts.dates, y: ts.q_p10,  name: "P10",  line: {color: "#90caf9", dash: "dash"}},
    {x: ts.dates, y: ts.q_mean, name: "Gemiddeld", line: {color: "#1565c0", width: 2}},
    {x: ts.dates, y: ts.q_p90,  name: "P90",  line: {color: "#ef9a9a", dash: "dash"}},
  ];
  Plotly.newPlot("mm-ensemble-chart", traces, {
    margin: {t: 10, b: 40, l: 50, r: 10},
    yaxis:  {title: "Afvoer (m³/s)"},
    legend: {orientation: "h"},
    paper_bgcolor: "transparent", plot_bgcolor: "transparent",
  });
}

function renderMultimodelScenarios(d) {
  const tbody = document.getElementById("mm-scenario-tbody");
  tbody.innerHTML = "";
  d.ensemble.scenarios.forEach(s => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${s.name}</td><td>×${s.multiplier.toFixed(2)}</td>` +
      `<td>${s.peak_q}</td><td>${s.peak_date}</td><td>${s.days_above}</td>`;
    tbody.appendChild(tr);
  });
}
```

- [ ] **Stap 7: Update cache-bust versienummer in `index.html`**

Zoek `app.js?v=` in `index.html` en verhoog het versienummer naar `v=12`.

- [ ] **Stap 8: Herstart uvicorn en test in browser**

```bash
kill $(cat /tmp/uvicorn.pid) 2>/dev/null
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
nohup python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn.log 2>&1 &
echo $! > /tmp/uvicorn.pid
sleep 2
curl -s http://localhost:8000/ | grep -c "multimodel"
```

Verwacht: `1` of meer (de tab-knop is aanwezig in de HTML)

- [ ] **Stap 9: Commit**

```bash
cd /home/bob/waterlab
git add wflow_ijssel/dashboard/index.html wflow_ijssel/dashboard/app.js
git commit -m "feat: Multimodel dashboard tab met Leaflet-kaart + ensemble grafiek"
```

---

## Task 9: Pipeline draaien + push

- [ ] **Stap 1: Draai alle tests**

```bash
cd /home/bob/waterlab
source wflow_ijssel/.venv/bin/activate
python -m pytest multimodel/tests/ -v 2>&1 | tail -20
```

Verwacht: alle tests groen.

- [ ] **Stap 2: Dry-run verificatie**

```bash
cd /home/bob/waterlab
source wflow_ijssel/.venv/bin/activate
python3 run_multimodel.py --dry-run 2>&1
```

Verwacht: netwerk + orchestrator stappen, geen wflow-runs.

- [ ] **Stap 3: Voeg `multimodel_data/` toe aan `.gitignore`**

Controleer dat `/home/bob/waterlab/wflow_ijssel/.gitignore` de regel `../multimodel_data/` bevat (of voeg die toe). De runtime-data hoeft niet in git.

```bash
grep "multimodel_data" /home/bob/waterlab/wflow_ijssel/.gitignore || \
  echo "../multimodel_data/" >> /home/bob/waterlab/wflow_ijssel/.gitignore
```

- [ ] **Stap 4: Draai de volledige pipeline**

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
nohup python3 ../run_multimodel.py > /home/bob/waterlab/multimodel_data/run.log 2>&1 &
echo "PID: $!"
```

Monitor voortgang:

```bash
tail -f /home/bob/waterlab/multimodel_data/run.log
```

Verwacht: stap 1 (4 knopen), stap 2 (AI beslissing), stap 3 (5 wflow-runs à ~132s), stap 4 (multimodel_stats.json).

- [ ] **Stap 5: Verifieer API na pipeline**

```bash
curl -s http://localhost:8000/api/multimodel | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('available:', d['available'])
print('kritieke knoop:', d['ribasim']['critical_node'])
print('orchestrator:', d['orchestrator']['trigger_reason'])
print('ensemble scenarios:', len(d['ensemble']['scenarios']))
"
```

Verwacht: `available: True`, correcte waarden.

- [ ] **Stap 6: Push naar GitHub**

```bash
cd /home/bob/waterlab
TOKEN="<GITHUB_PAT>"
git remote set-url origin "https://bopfelix-derwisch:${TOKEN}@github.com/bopfelix-derwisch/wflow_ijssel.git"
git push
git remote set-url origin https://github.com/bopfelix-derwisch/wflow_ijssel.git
```
