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
