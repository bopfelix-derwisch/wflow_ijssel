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
