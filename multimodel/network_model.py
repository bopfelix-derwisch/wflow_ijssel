"""Rijn/IJssel routeringsmodel via Ribasim (Python 3.13 + Julia solver)."""
from __future__ import annotations
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import xarray as xr

_VENV313   = Path("/home/bob/waterlab/.venv313/bin/python")
_BUILD_SCR = Path(__file__).parent / "build_ribasim_model.py"
_JULIA     = Path(shutil.which("julia") or "julia")


def simulate_network(settings: dict) -> dict:
    """
    Simuleert dagelijks debiet en waterstand per knoop via Ribasim.

    Retourneert:
      {
        "nodes": [
          {
            "name": str,
            "lon": float, "lat": float,
            "flows": list[float],
            "levels": list[float],
            "mean_level": float,
            "threshold_level": float,
            "deficit_pct": float,
            "flow_fraction": float,
          },
        ],
        "days": int,
      }
    """
    if _VENV313.exists():
        return _simulate_ribasim(settings)
    return _simulate_fallback(settings)


def _simulate_ribasim(settings: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # Step 1: build the ribasim model via Python 3.13 + ribasim package
        result = subprocess.run(
            [str(_VENV313), str(_BUILD_SCR), str(tmp_dir), json.dumps(settings)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ribasim model build failed:\n{result.stderr}")

        # Step 2: run the Julia solver
        julia_script = (
            f'using Ribasim; Ribasim.run("{tmp_dir}/ribasim.toml")'
        )
        result = subprocess.run(
            [str(_JULIA), "-e", julia_script],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ribasim Julia run failed:\n{result.stderr}")

        # Step 3: read results
        return _parse_results(tmp_dir, settings)


def _parse_results(run_dir: Path, settings: dict) -> dict:
    cfg = settings["network"]

    with open(run_dir / "node_mapping.json") as f:
        mapping = json.load(f)

    basin_nc = xr.open_dataset(run_dir / "results" / "basin.nc")
    flow_nc  = xr.open_dataset(run_dir / "results" / "flow.nc")

    from_ids  = flow_nc["from_node_id"].values   # (n_links,)
    flow_rate = flow_nc["flow_rate"].values       # (time, n_links)

    results = []
    for node_cfg in cfg["nodes"]:
        name  = node_cfg["name"]
        b_id  = mapping[name]["basin_id"]
        thresh = node_cfg["threshold_level"]
        frac   = node_cfg["flow_fraction"]

        # Flow out of basin (basin → TRC link)
        link_idx = int(np.where(from_ids == b_id)[0][0])
        flows = flow_rate[:, link_idx].tolist()

        # Convert to synthetic level (flow/1000) to keep threshold comparison
        # consistent with threshold_level values in settings.yaml.
        levels = [q / 1000.0 for q in flows]
        mean_l = float(np.mean(levels))

        deficit = max(0.0, (thresh - mean_l) / thresh * 100.0)

        results.append({
            "name":            name,
            "lon":             node_cfg["lon"],
            "lat":             node_cfg["lat"],
            "flows":           [round(q, 1) for q in flows],
            "levels":          [round(l, 4) for l in levels],
            "mean_level":      round(mean_l, 4),
            "threshold_level": thresh,
            "deficit_pct":     round(deficit, 1),
            "flow_fraction":   frac,
        })

    basin_nc.close()
    flow_nc.close()
    return {"nodes": results, "days": cfg["simulation_days"]}


def _simulate_fallback(settings: dict) -> dict:
    """Pure-Python fallback when ribasim/Julia are unavailable."""
    cfg  = settings["network"]
    days = cfg["simulation_days"]
    base = cfg["lobith_base_flow"]
    amp  = cfg["lobith_amplitude"]

    lobith = [base + amp * math.sin(2 * math.pi * t / days) for t in range(days)]

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
