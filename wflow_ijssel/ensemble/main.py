"""Ensemble pipeline: scenario's genereren, draaien, analyseren en interpreteren."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import yaml

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

    # Dashboard-compatible format: scenarios[] + timeseries{}
    dashboard_stats = {
        "scenarios": [
            {
                "name":       r["name"],
                "multiplier": r["multiplier"],
                "peak_q":     r["peak_q"],
                "peak_date":  r["peak_date"],
                "days_above": r["days_above_threshold"],
            }
            for r in results
        ],
        "timeseries": {
            "dates":  stats["dates"],
            "q_p10":  stats["q_p10"],
            "q_mean": stats["q_mean"],
            "q_p90":  stats["q_p90"],
        },
    }
    stats_path = outputs_dir / "ensemble_stats.json"
    save_json(dashboard_stats, stats_path)
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
