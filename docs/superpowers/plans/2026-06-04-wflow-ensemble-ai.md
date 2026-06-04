# Wflow Ensemble AI — Implementatieplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Een lokaal ensemble-systeem op de Jetson Orin dat 5 Wflow-scenario's draait met variërende neerslagforcering, de spread statistisch analyseert en de uitkomsten laat samenvatten door de al draaiende Qwen2.5-32B LLM.

**Architecture:** `scenario_generator` maakt 5 neerslagvarianten van `forcing-ijssel.nc` → `wflow_runner` draait ze sequentieel via een per-scenario TOML-config → `output_collector` extraheert tijdreeksen naar compacte JSON en ruimt NetCDF op → `analysis_engine` berekent ensemble-statistieken (mean, p10/p90, hotspots) → `llm_agent` roept llama.cpp-server (poort 8080, OpenAI-compatible) aan voor interpretatie → `interface` biedt een CLI om alles te orkestreren.

**Tech Stack:** Python 3.10+ (xarray, numpy, scipy, requests), Julia/Wflow.jl (reeds geïnstalleerd), llama.cpp-server op poort 8080 (Qwen2.5-32B, reeds draaiend), PyYAML, argparse

**Feasibility-opmerkingen:**
- Ollama uit de spec is **niet nodig**: llama.cpp-server draait al op `http://127.0.0.1:8080` met OpenAI-compatible API.
- Disk: output_ijssel.nc is 34 MB per run. NetCDF wordt direct na extractie verwijderd; netto extra diskgebruik ≤ 200 MB.
- RAM: 29 GB vrij, ruim voldoende voor sequentiële runs.
- `run_ijssel.jl` krijgt één regel extra zodat het een optioneel config-pad als argument accepteert (backwards-compatible).

---

## Bestandsoverzicht

| Bestand | Verantwoordelijkheid |
|---|---|
| `wflow_ijssel/run_ijssel.jl` | **Modify**: accepteer optioneel ARGS[1] als config-pad |
| `wflow_ijssel/ensemble/__init__.py` | Package marker |
| `wflow_ijssel/ensemble/scenario_generator.py` | Maak 5 forcering-varianten + TOML-configs |
| `wflow_ijssel/ensemble/wflow_runner.py` | Draai één scenario; retourneer output-pad |
| `wflow_ijssel/ensemble/output_collector.py` | Lees NetCDF, extraheer tijdreeks Kampen → JSON, verwijder NC |
| `wflow_ijssel/ensemble/analysis_engine.py` | Ensemble-statistieken: mean, p10, p90, hotspots |
| `wflow_ijssel/ensemble/llm_agent.py` | POST naar llama.cpp OpenAI API, retourneer interpretatie |
| `wflow_ijssel/ensemble/main.py` | Orkestreer volledige pipeline |
| `wflow_ijssel/ensemble/config/settings.yaml` | Basisinstellingen (paden, LLM-URL, scenario-parameters) |
| `wflow_ijssel/tests/test_ensemble.py` | Unit tests voor alle ensemble-modules |

---

## Task 1: run_ijssel.jl aanpassen + ensemble scaffold

**Files:**
- Modify: `wflow_ijssel/run_ijssel.jl`
- Create: `wflow_ijssel/ensemble/__init__.py`
- Create: `wflow_ijssel/ensemble/config/settings.yaml`

- [ ] **Stap 1: Voeg optioneel config-pad toe aan run_ijssel.jl**

Vervang in `wflow_ijssel/run_ijssel.jl` de regel:
```julia
toml_path = joinpath(@__DIR__, "ijssel_config.toml")
```
door:
```julia
toml_path = length(ARGS) > 0 ? ARGS[1] : joinpath(@__DIR__, "ijssel_config.toml")
```

Dit is backwards-compatible: zonder argument werkt het precies zoals voorheen.

- [ ] **Stap 2: Verifieer dat bestaand gebruik nog werkt**

```bash
cd /home/bob/waterlab/wflow_ijssel
julia --project=. run_ijssel.jl --help 2>&1 | head -3 || echo "geen --help, OK"
```

Verwacht: geen crasht, Julia parseert ARGS zonder fout.

- [ ] **Stap 3: Maak ensemble package aan**

```bash
mkdir -p wflow_ijssel/ensemble/config wflow_ijssel/ensemble/data/scenarios wflow_ijssel/ensemble/data/outputs
touch wflow_ijssel/ensemble/__init__.py
```

- [ ] **Stap 4: Schrijf settings.yaml**

Maak `wflow_ijssel/ensemble/config/settings.yaml`:

```yaml
wflow_root: "/home/bob/waterlab/wflow_ijssel"
base_forcing: "data/input/forcing-ijssel.nc"
base_config:  "data/output/ijssel_config.toml"
julia_project: "/home/bob/waterlab/wflow_ijssel"
run_script:   "run_ijssel.jl"

ensemble_data_root: "/mnt/nvme/waterlab/ensemble"

scenarios:
  parameter: "precip_multiplier"
  values: [0.70, 0.85, 1.00, 1.15, 1.30]
  names:  ["droog", "normaal_droog", "baseline", "normaal_nat", "nat"]

llm:
  base_url: "http://127.0.0.1:8080"
  model:    "qwen2.5-32b-instruct-q4_k_m-00001-of-00005.gguf"
  max_tokens: 600
  temperature: 0.3

analysis:
  station_lon: 5.921
  station_lat: 52.555
  threshold_q: 1500.0
```

- [ ] **Stap 5: Commit**

```bash
cd /home/bob/waterlab/wflow_ijssel
git add run_ijssel.jl ensemble/
git commit -m "feat: ensemble scaffold + run_ijssel.jl config-pad argument"
```

---

## Task 2: scenario_generator.py

**Files:**
- Create: `wflow_ijssel/ensemble/scenario_generator.py`

Genereert voor elk scenario een aangepaste `forcing_<naam>.nc` en een bijbehorende TOML-config die daarnaar verwijst.

- [ ] **Stap 1: Schrijf falende test** (in Task 8 — hier alvast de spec)

Verwacht gedrag:
- `generate_scenarios()` maakt 5 forcing-bestanden aan in `ensemble/data/scenarios/`
- Elk bestand heeft dezelfde structuur als `forcing-ijssel.nc` maar met `precip *= multiplier`
- Retourneert lijst van `{"name": ..., "forcing_path": ..., "config_path": ..., "multiplier": ...}`

- [ ] **Stap 2: Schrijf scenario_generator.py**

Maak `wflow_ijssel/ensemble/scenario_generator.py`:

```python
"""Genereer neerslag-scenario's voor het ensemble."""
from __future__ import annotations
import shutil
import tomllib
import tomli_w
from pathlib import Path

import numpy as np
import xarray as xr
import yaml


def load_settings(settings_path: Path) -> dict:
    with open(settings_path) as f:
        return yaml.safe_load(f)


def generate_scenarios(settings: dict, out_dir: Path) -> list[dict]:
    """Maak scenario-forcing en TOML-configs aan. Retourneer scenario-metadata."""
    root          = Path(settings["wflow_root"])
    base_forcing  = root / settings["base_forcing"]
    base_config   = root / settings["base_config"]
    names         = settings["scenarios"]["names"]
    multipliers   = settings["scenarios"]["values"]

    scenarios_dir = out_dir / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    # Lees basis TOML als dict
    with open(base_config, "rb") as f:
        base_toml = tomllib.load(f)

    results = []
    for name, mult in zip(names, multipliers):
        scenario_dir = scenarios_dir / name
        scenario_dir.mkdir(exist_ok=True)

        # Forcing aanpassen
        forcing_out = scenario_dir / "forcing.nc"
        if not forcing_out.exists():
            ds = xr.open_dataset(base_forcing)
            ds["precip"] = (ds["precip"] * mult).clip(min=0)
            ds.to_netcdf(str(forcing_out))
            ds.close()

        # TOML aanpassen: wijs naar scenario-forcing en -output
        toml_out = scenario_dir / "config.toml"
        cfg = dict(base_toml)
        cfg["input"]  = dict(cfg["input"])
        cfg["input"]["path_forcing"] = str(forcing_out.resolve())
        cfg["output"] = dict(cfg.get("output", {}))
        cfg["output"]["path"] = str((scenario_dir / "output.nc").resolve())
        cfg["dir_output"] = str(scenario_dir.resolve())

        with open(toml_out, "wb") as f:
            tomli_w.dump(cfg, f)

        results.append({
            "name":        name,
            "multiplier":  mult,
            "forcing_path": str(forcing_out),
            "config_path":  str(toml_out),
            "output_nc":    str(scenario_dir / "output.nc"),
            "output_dir":   str(scenario_dir),
        })

    return results
```

- [ ] **Stap 3: Installeer tomli_w**

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
pip install tomli-w pyyaml
```

Verwacht: geen fouten.

- [ ] **Stap 4: Handmatige check**

```python
# Vanuit wflow_ijssel/ met venv actief:
import sys; sys.path.insert(0, "ensemble")
from scenario_generator import load_settings, generate_scenarios
from pathlib import Path

settings = load_settings(Path("ensemble/config/settings.yaml"))
scenarios = generate_scenarios(settings, Path("ensemble/data"))
for s in scenarios:
    print(s["name"], s["multiplier"], Path(s["forcing_path"]).exists())
```

Verwacht: vijf regels met `True`.

- [ ] **Stap 5: Commit**

```bash
git add ensemble/scenario_generator.py
git commit -m "feat: ensemble scenario_generator — 5 neerslagvarianten"
```

---

## Task 3: output_collector.py

**Files:**
- Create: `wflow_ijssel/ensemble/output_collector.py`

Leest de Wflow NetCDF-output, extraheert de tijdreeks bij Kampen naar compact JSON, en verwijdert daarna het grote NC-bestand om schijfruimte te sparen.

- [ ] **Stap 1: Schrijf output_collector.py**

Maak `wflow_ijssel/ensemble/output_collector.py`:

```python
"""Extraheer Kampen-tijdreeks uit Wflow NC-output; verwijder NC na extractie."""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import xarray as xr


def _nearest_idx(coord: np.ndarray, target: float) -> int:
    return int(np.argmin(np.abs(coord - target)))


def collect(output_nc: Path, station_lon: float, station_lat: float,
            threshold: float, delete_nc: bool = True) -> dict:
    """
    Retourneert dict met:
      dates, q, h_nap, peak_q, peak_date, days_above_threshold
    """
    ds = xr.open_dataset(str(output_nc))

    lons = ds["lon"].values if "lon" in ds else ds["x"].values
    lats = ds["lat"].values if "lat" in ds else ds["y"].values

    xi = _nearest_idx(lons, station_lon)
    yi = _nearest_idx(lats, station_lat)

    q    = ds["q_river"].isel(x=xi, y=yi).values.tolist()
    h    = ds["h_river"].isel(x=xi, y=yi).values.tolist()
    dates = [str(t)[:10] for t in ds["time"].values]
    ds.close()

    q_arr    = np.array(q)
    peak_idx = int(np.argmax(q_arr))

    result = {
        "dates":               dates,
        "q":                   [round(v, 2) for v in q],
        "h":                   [round(v, 3) for v in h],
        "peak_q":              round(float(q_arr[peak_idx]), 1),
        "peak_date":           dates[peak_idx],
        "days_above_threshold": int(np.sum(q_arr > threshold)),
    }

    if delete_nc:
        output_nc.unlink(missing_ok=True)

    return result


def save_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
```

- [ ] **Stap 2: Smoke test tegen bestaande output**

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
python3 -c "
import sys; sys.path.insert(0, 'ensemble')
from output_collector import collect
from pathlib import Path

result = collect(
    Path('data/output/output_ijssel.nc'),
    station_lon=5.921, station_lat=52.555,
    threshold=1500.0,
    delete_nc=False,   # laat het bestaande bestand staan
)
print('Peak Q:', result['peak_q'], 'op', result['peak_date'])
print('Dagen > drempel:', result['days_above_threshold'])
print('Tijdstappen:', len(result['dates']))
"
```

Verwacht: realistische waarden (peak ~849, 0 dagen boven 1500 m³/s).

- [ ] **Stap 3: Commit**

```bash
git add ensemble/output_collector.py
git commit -m "feat: ensemble output_collector — NC → JSON + disk cleanup"
```

---

## Task 4: wflow_runner.py

**Files:**
- Create: `wflow_ijssel/ensemble/wflow_runner.py`

Draait één scenario: roept `julia --project=. run_ijssel.jl <config>` aan, wacht op voltooiing, retourneert pad naar output NC.

- [ ] **Stap 1: Schrijf wflow_runner.py**

Maak `wflow_ijssel/ensemble/wflow_runner.py`:

```python
"""Voer één Wflow-scenario uit via subprocess."""
from __future__ import annotations
import subprocess
import time
from pathlib import Path


def run_scenario(scenario: dict, julia_project: str, run_script: str,
                 timeout: int = 3600) -> Path:
    """
    Draait julia --project=<julia_project> <run_script> <config_path>.
    Blokkeert tot voltooiing. Gooit RuntimeError bij non-zero exit.
    Retourneert Path naar output NC.
    """
    config_path = scenario["config_path"]
    output_nc   = Path(scenario["output_nc"])

    cmd = [
        "julia",
        f"--project={julia_project}",
        run_script,
        config_path,
    ]

    print(f"  → Run: {scenario['name']} (multiplier={scenario['multiplier']})")
    t0 = time.monotonic()

    result = subprocess.run(
        cmd,
        cwd=julia_project,
        capture_output=False,
        timeout=timeout,
    )

    elapsed = time.monotonic() - t0
    if result.returncode != 0:
        raise RuntimeError(
            f"Wflow mislukt voor scenario '{scenario['name']}' "
            f"(exit {result.returncode}) na {elapsed:.0f}s"
        )

    if not output_nc.exists():
        raise FileNotFoundError(
            f"Output NC niet aangemaakt: {output_nc}"
        )

    print(f"  ✓ Klaar: {scenario['name']} in {elapsed:.0f}s")
    return output_nc
```

- [ ] **Stap 2: Verifieer Julia-aanroep syntax**

```bash
cd /home/bob/waterlab/wflow_ijssel
# Droge test: geef een onbestaand config-pad mee, Julia moet snel crashen
julia --project=. run_ijssel.jl /tmp/nonexistent.toml 2>&1 | head -5
```

Verwacht: foutmelding "Config niet gevonden" of Julia-error — géén Wflow-run. Bewijst dat ARGS[1] werkt.

- [ ] **Stap 3: Commit**

```bash
git add ensemble/wflow_runner.py
git commit -m "feat: ensemble wflow_runner — subprocess wrapper voor Julia"
```

---

## Task 5: analysis_engine.py

**Files:**
- Create: `wflow_ijssel/ensemble/analysis_engine.py`

Berekent over alle scenario's: mean, p10, p90 per tijdstap; totale onzekerheidsrange; en identificeert welke dag de grootste spread heeft (hotspot).

- [ ] **Stap 1: Schrijf analysis_engine.py**

Maak `wflow_ijssel/ensemble/analysis_engine.py`:

```python
"""Ensemble-statistieken over alle scenario-uitkomsten."""
from __future__ import annotations
import numpy as np


def compute_ensemble_stats(results: list[dict]) -> dict:
    """
    results: lijst van output_collector.collect()-dicts (één per scenario).
    Retourneert dict met ensemble-statistieken.
    """
    names    = [r["name"] for r in results]
    q_matrix = np.array([r["q"] for r in results])   # shape: (n_scenarios, n_days)
    dates    = results[0]["dates"]

    q_mean = q_matrix.mean(axis=0)
    q_p10  = np.percentile(q_matrix, 10, axis=0)
    q_p90  = np.percentile(q_matrix, 90, axis=0)
    q_std  = q_matrix.std(axis=0)

    # Hotspot: dag met grootste spread (p90 - p10)
    spread    = q_p90 - q_p10
    hot_idx   = int(np.argmax(spread))

    peaks = {r["name"]: r["peak_q"] for r in results}

    return {
        "scenario_names": names,
        "dates":          dates,
        "q_mean":         [round(float(v), 1) for v in q_mean],
        "q_p10":          [round(float(v), 1) for v in q_p10],
        "q_p90":          [round(float(v), 1) for v in q_p90],
        "q_std":          [round(float(v), 1) for v in q_std],
        "hotspot_date":   dates[hot_idx],
        "hotspot_spread": round(float(spread[hot_idx]), 1),
        "peak_per_scenario": peaks,
        "days_above_threshold": {
            r["name"]: r["days_above_threshold"] for r in results
        },
    }
```

- [ ] **Stap 2: Smoke test met synthetische data**

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
python3 -c "
import sys; sys.path.insert(0, 'ensemble')
from analysis_engine import compute_ensemble_stats
import numpy as np

# Synthetisch: 3 scenario's, 5 dagen
fake = [
    {'name': 'droog',    'q': [400,500,600,550,500], 'peak_q': 600, 'peak_date': '1995-01-03', 'days_above_threshold': 0},
    {'name': 'baseline', 'q': [500,700,900,800,700], 'peak_q': 900, 'peak_date': '1995-01-03', 'days_above_threshold': 0},
    {'name': 'nat',      'q': [700,1100,1500,1300,1100], 'peak_q': 1500, 'peak_date': '1995-01-03', 'days_above_threshold': 1},
]
stats = compute_ensemble_stats(fake)
print('Mean dag 2:', stats['q_mean'][1])
print('P10/P90 dag 2:', stats['q_p10'][1], '/', stats['q_p90'][1])
print('Hotspot:', stats['hotspot_date'], '+/-', stats['hotspot_spread'])
"
```

Verwacht: realistische getallen zonder fout.

- [ ] **Stap 3: Commit**

```bash
git add ensemble/analysis_engine.py
git commit -m "feat: ensemble analysis_engine — mean/p10/p90/hotspot statistieken"
```

---

## Task 6: llm_agent.py

**Files:**
- Create: `wflow_ijssel/ensemble/llm_agent.py`

Stuurt ensemble-statistieken naar de al draaiende llama.cpp-server (poort 8080, OpenAI-compatible) en retourneert een tekstinterpretatie.

- [ ] **Stap 1: Verifieer LLM bereikbaar**

```bash
curl -s http://127.0.0.1:8080/v1/models | python3 -c "import sys,json; d=json.load(sys.stdin); print('Model:', d['data'][0]['id'])"
```

Verwacht: modelnaam van Qwen2.5-32B.

- [ ] **Stap 2: Schrijf llm_agent.py**

Maak `wflow_ijssel/ensemble/llm_agent.py`:

```python
"""LLM-interpretatie van ensemble-resultaten via llama.cpp OpenAI-compatible API."""
from __future__ import annotations
import json
import requests


SYSTEM_PROMPT = """Je bent een hydroloog die ensemble-modelresultaten interpreteert.
Geef een beknopte, feitelijke samenvatting in het Nederlands.
Noem: de bandbreedte van piekafvoeren, het hoogwaterrisico, en de belangrijkste onzekerheid.
Maximaal 200 woorden. Gebruik geen opsomming — schrijf doorlopende tekst."""


def build_user_message(stats: dict, threshold: float) -> str:
    peaks = stats["peak_per_scenario"]
    days  = stats["days_above_threshold"]
    lines = [
        f"Ensemble-analyse IJssel bij Kampen (drempel: {threshold} m³/s):",
        f"Scenario's: {', '.join(stats['scenario_names'])}",
        f"Piekafvoeren per scenario (m³/s): {json.dumps(peaks)}",
        f"Dagen boven drempel per scenario: {json.dumps(days)}",
        f"Ensemble gemiddelde piek (m³/s): {max(stats['q_mean']):.0f}",
        f"P10–P90 bandbreedte op hotspot-dag ({stats['hotspot_date']}): "
        f"{stats['hotspot_spread']:.0f} m³/s",
        "",
        "Interpreteer deze resultaten voor een waterbeheerder.",
    ]
    return "\n".join(lines)


def interpret(stats: dict, llm_config: dict, threshold: float = 1500.0) -> str:
    """
    Stuur ensemble-statistieken naar llama.cpp en retourneer de interpretatie.
    llm_config: {'base_url': ..., 'model': ..., 'max_tokens': ..., 'temperature': ...}
    """
    payload = {
        "model":       llm_config["model"],
        "messages": [
            {"role": "system",  "content": SYSTEM_PROMPT},
            {"role": "user",    "content": build_user_message(stats, threshold)},
        ],
        "max_tokens":  llm_config.get("max_tokens", 600),
        "temperature": llm_config.get("temperature", 0.3),
    }

    resp = requests.post(
        f"{llm_config['base_url']}/v1/chat/completions",
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()
```

- [ ] **Stap 3: Test met synthetische stats**

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
python3 -c "
import sys; sys.path.insert(0, 'ensemble')
from llm_agent import interpret
import yaml
from pathlib import Path

settings = yaml.safe_load(open('ensemble/config/settings.yaml'))
fake_stats = {
    'scenario_names': ['droog', 'baseline', 'nat'],
    'peak_per_scenario': {'droog': 620, 'baseline': 849, 'nat': 1120},
    'days_above_threshold': {'droog': 0, 'baseline': 0, 'nat': 0},
    'q_mean': [500] * 31,
    'hotspot_date': '1995-01-28',
    'hotspot_spread': 520,
}
print(interpret(fake_stats, settings['llm'], threshold=1500.0))
"
```

Verwacht: alinea van 100–200 woorden in het Nederlands over de ensemble-resultaten.

- [ ] **Stap 4: Commit**

```bash
git add ensemble/llm_agent.py
git commit -m "feat: ensemble llm_agent — LLM-interpretatie via llama.cpp"
```

---

## Task 7: main.py + CLI

**Files:**
- Create: `wflow_ijssel/ensemble/main.py`

Orkestreert de volledige pipeline: genereer → run → collect → analyseer → interpreteer. CLI met argparse.

- [ ] **Stap 1: Schrijf main.py**

Maak `wflow_ijssel/ensemble/main.py`:

```python
"""Ensemble pipeline: scenario's genereren, draaien, analyseren en interpreteren."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import yaml

# Voeg ensemble-map toe aan path zodat imports werken
sys.path.insert(0, str(Path(__file__).parent))

from scenario_generator import load_settings, generate_scenarios
from wflow_runner import run_scenario
from output_collector import collect, save_json
from analysis_engine import compute_ensemble_stats
from llm_agent import interpret


def run_pipeline(settings_path: Path, dry_run: bool = False) -> None:
    settings  = load_settings(settings_path)
    root      = Path(settings["wflow_root"])
    out_dir   = Path(settings.get("ensemble_data_root", str(Path(__file__).parent / "data")))
    outputs_dir = out_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    print("=== Stap 1: Scenario's genereren ===")
    scenarios = generate_scenarios(settings, out_dir)
    print(f"  {len(scenarios)} scenario's aangemaakt")

    if dry_run:
        print("[dry-run] Geen Wflow-runs uitgevoerd.")
        return

    print("\n=== Stap 2: Wflow-simulaties draaien (sequentieel) ===")
    results = []
    for sc in scenarios:
        output_nc = run_scenario(
            sc,
            julia_project=settings["julia_project"],
            run_script=str(root / settings["run_script"]),
        )
        print(f"  Extracteren: {sc['name']} ...")
        result = collect(
            output_nc=output_nc,
            station_lon=settings["analysis"]["station_lon"],
            station_lat=settings["analysis"]["station_lat"],
            threshold=settings["analysis"]["threshold_q"],
            delete_nc=True,
        )
        result["name"] = sc["name"]
        result["multiplier"] = sc["multiplier"]
        json_path = outputs_dir / f"{sc['name']}.json"
        save_json(result, json_path)
        print(f"  ✓ {sc['name']}: piek={result['peak_q']} m³/s, "
              f"dagen>{settings['analysis']['threshold_q']:.0f}: "
              f"{result['days_above_threshold']}")
        results.append(result)

    print("\n=== Stap 3: Ensemble-statistieken ===")
    stats = compute_ensemble_stats(results)
    stats_path = outputs_dir / "ensemble_stats.json"
    save_json(stats, stats_path)
    print(f"  Hotspot: {stats['hotspot_date']} (spread {stats['hotspot_spread']} m³/s)")
    print(f"  Resultaat: {stats_path}")

    print("\n=== Stap 4: LLM-interpretatie ===")
    interpretation = interpret(
        stats,
        llm_config=settings["llm"],
        threshold=settings["analysis"]["threshold_q"],
    )
    interp_path = outputs_dir / "interpretation.txt"
    interp_path.write_text(interpretation)
    print(f"\n{interpretation}\n")
    print(f"  Opgeslagen: {interp_path}")

    print("\n=== Klaar ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="Wflow Ensemble AI Pipeline")
    parser.add_argument(
        "--settings",
        default=str(Path(__file__).parent / "config" / "settings.yaml"),
        help="Pad naar settings.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Genereer alleen scenario's, draai geen Wflow",
    )
    args = parser.parse_args()
    run_pipeline(Path(args.settings), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Stap 2: Test dry-run**

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
python3 ensemble/main.py --dry-run
```

Verwacht:
```
=== Stap 1: Scenario's genereren ===
  5 scenario's aangemaakt
[dry-run] Geen Wflow-runs uitgevoerd.
```
En 5 forcing-bestanden in `ensemble/data/scenarios/`.

- [ ] **Stap 3: Commit**

```bash
git add ensemble/main.py
git commit -m "feat: ensemble main.py + CLI met dry-run optie"
```

---

## Task 8: Unit tests

**Files:**
- Create: `wflow_ijssel/tests/test_ensemble.py`

- [ ] **Stap 1: Schrijf test_ensemble.py**

Maak `wflow_ijssel/tests/test_ensemble.py`:

```python
"""Unit tests voor ensemble-modules."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

sys.path.insert(0, str(Path(__file__).parent.parent / "ensemble"))

from output_collector import collect
from analysis_engine import compute_ensemble_stats
from llm_agent import build_user_message


# ── output_collector ────────────────────────────────────────────────────────

@pytest.fixture
def mock_nc(tmp_path) -> Path:
    times = np.array(["1995-01-01", "1995-01-02", "1995-01-03"], dtype="datetime64")
    ny, nx = 5, 6
    q = np.zeros((3, ny, nx), dtype=np.float32)
    h = np.zeros((3, ny, nx), dtype=np.float32)
    q[:, 2, 3] = [800.0, 1600.0, 1200.0]
    h[:, 2, 3] = [1.2, 2.4, 1.8]
    lons = np.linspace(5.5, 6.5, nx)
    lats = np.linspace(52.8, 52.0, ny)

    ds = xr.Dataset(
        {"q_river": (["time", "y", "x"], q), "h_river": (["time", "y", "x"], h)},
        coords={"time": times, "lon": (["x"], lons), "lat": (["y"], lats)},
    )
    nc_path = tmp_path / "output.nc"
    ds.to_netcdf(nc_path)
    return nc_path


def test_collect_returns_required_keys(mock_nc):
    result = collect(mock_nc, station_lon=6.1, station_lat=52.4,
                     threshold=1500.0, delete_nc=False)
    for key in ("dates", "q", "h", "peak_q", "peak_date", "days_above_threshold"):
        assert key in result


def test_collect_peak_correct(mock_nc):
    result = collect(mock_nc, station_lon=6.1, station_lat=52.4,
                     threshold=1500.0, delete_nc=False)
    assert result["peak_q"] == pytest.approx(1600.0, abs=1.0)
    assert result["peak_date"] == "1995-01-02"


def test_collect_days_above_threshold(mock_nc):
    result = collect(mock_nc, station_lon=6.1, station_lat=52.4,
                     threshold=1500.0, delete_nc=False)
    assert result["days_above_threshold"] == 1


def test_collect_deletes_nc(mock_nc):
    assert mock_nc.exists()
    collect(mock_nc, station_lon=6.1, station_lat=52.4,
            threshold=1500.0, delete_nc=True)
    assert not mock_nc.exists()


# ── analysis_engine ──────────────────────────────────────────────────────────

FAKE_RESULTS = [
    {"name": "droog",    "q": [400.0, 500.0, 600.0], "peak_q": 600.0,
     "peak_date": "1995-01-03", "days_above_threshold": 0},
    {"name": "baseline", "q": [600.0, 800.0, 1000.0], "peak_q": 1000.0,
     "peak_date": "1995-01-03", "days_above_threshold": 0},
    {"name": "nat",      "q": [800.0, 1200.0, 1600.0], "peak_q": 1600.0,
     "peak_date": "1995-01-03", "days_above_threshold": 1},
]


def test_stats_keys():
    stats = compute_ensemble_stats(FAKE_RESULTS)
    for key in ("q_mean", "q_p10", "q_p90", "hotspot_date", "peak_per_scenario"):
        assert key in stats


def test_stats_mean_correct():
    stats = compute_ensemble_stats(FAKE_RESULTS)
    assert stats["q_mean"][0] == pytest.approx(600.0, abs=1.0)


def test_stats_p10_p90_ordering():
    stats = compute_ensemble_stats(FAKE_RESULTS)
    for p10, p90 in zip(stats["q_p10"], stats["q_p90"]):
        assert p10 <= p90


# ── llm_agent ────────────────────────────────────────────────────────────────

def test_build_user_message_contains_scenario_names():
    stats = {
        "scenario_names": ["droog", "nat"],
        "peak_per_scenario": {"droog": 600, "nat": 1600},
        "days_above_threshold": {"droog": 0, "nat": 1},
        "q_mean": [800.0],
        "hotspot_date": "1995-01-28",
        "hotspot_spread": 500.0,
    }
    msg = build_user_message(stats, threshold=1500.0)
    assert "droog" in msg
    assert "nat" in msg
    assert "1500" in msg
```

- [ ] **Stap 2: Draai tests**

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
python3 -m pytest tests/test_ensemble.py -v
```

Verwacht: alle 10 tests `PASSED`.

- [ ] **Stap 3: Commit**

```bash
git add tests/test_ensemble.py
git commit -m "test: unit tests ensemble-modules"
```

---

## Task 9: Volledige pipeline draaien + DRAAIBOEK bijwerken

- [ ] **Stap 1: Volledige run starten**

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
nohup python3 ensemble/main.py > ensemble/data/run.log 2>&1 &
echo "PID: $!"
tail -f ensemble/data/run.log
```

Verwacht na ~50 min (5 × ~10 min per run): `ensemble/data/outputs/interpretation.txt` gevuld met een Nederlands LLM-rapport.

- [ ] **Stap 2: Controleer outputs**

```bash
ls -lh ensemble/data/outputs/
cat ensemble/data/outputs/interpretation.txt
python3 -c "
import json
stats = json.load(open('ensemble/data/outputs/ensemble_stats.json'))
print('Scenarios:', stats['scenario_names'])
print('Peak per scenario:', stats['peak_per_scenario'])
print('Hotspot:', stats['hotspot_date'], stats['hotspot_spread'], 'm3/s')
"
```

- [ ] **Stap 3: Voeg ensemble-sectie toe aan DRAAIBOEK.md**

Voeg toe aan `DRAAIBOEK.md` onder Stap 6:

```markdown
## Stap 8 — Ensemble AI-analyse draaien

Genereert 5 neerslagscenario's (×0.70 t/m ×1.30), draait ze sequentieel in Wflow,
berekent ensemble-statistieken en laat Qwen2.5-32B de onzekerheid interpreteren.

**Vereist:** Stap 4–5 voltooid (wflow draait), llama-server actief op poort 8080.

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
python3 ensemble/main.py
```

Dry-run (alleen scenario-bestanden aanmaken, geen Wflow):
```bash
python3 ensemble/main.py --dry-run
```

Resultaten in `ensemble/data/outputs/`:
- `<naam>.json` — tijdreeks per scenario
- `ensemble_stats.json` — mean/p10/p90/hotspot
- `interpretation.txt` — LLM-samenvatting
```

- [ ] **Stap 4: Commit**

```bash
git add ensemble/ DRAAIBOEK.md
git commit -m "feat: volledige ensemble AI pipeline werkend + DRAAIBOEK bijgewerkt"
```

---

## Volgorde van uitvoering

```
Task 1 (scaffold) → Task 2 (generator) → Task 3 (collector) → Task 4 (runner)
→ Task 5 (analyse) → Task 6 (LLM) → Task 7 (main + CLI)
→ Task 8 (tests) → Task 9 (volledige run)
```

> Taken 1–8 vereisen geen actieve Wflow-run. Alleen Task 9 draait de echte simulaties (~50 min voor 5 scenario's). De LLM-server moet draaien bij Task 6 (test) en Task 9 (volledige run).
