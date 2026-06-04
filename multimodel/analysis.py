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
    """Combineert alle pipeline-outputs in één JSON-struct voor het dashboard."""
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
