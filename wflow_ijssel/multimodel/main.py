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
