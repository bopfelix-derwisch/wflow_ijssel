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
