"""
Build a Ribasim IJssel/Rijn network model and write it to disk.
Called via Python 3.13 venv (ribasim requires Python >=3.11).

Usage:
    /path/to/.venv313/bin/python build_ribasim_model.py <out_dir> <settings_json>
"""
from __future__ import annotations
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import Point

from ribasim.model import Model
from ribasim.geometry.node import Node
from ribasim.nodes import basin, tabulated_rating_curve, flow_boundary


def build(out_dir: Path, settings: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg  = settings["network"]
    days = cfg["simulation_days"]
    base = cfg["lobith_base_flow"]
    amp  = cfg["lobith_amplitude"]

    # Derive starttime from settings (default to 2018-05-01)
    starttime = datetime.fromisoformat(
        settings.get("ribasim", {}).get("starttime", "2018-05-01T00:00:00")
    )
    endtime = datetime(starttime.year + (0 if starttime.month < 10 else 1),
                       ((starttime.month + days // 30 - 1) % 12) + 1, 1)
    # Simpler: just add 'days' as timedelta
    from datetime import timedelta
    endtime = starttime + timedelta(days=days)

    dates = pd.date_range(starttime, periods=days, freq="D")
    # Lobith synthetic: sinusoidal drought pattern
    lobith_q = np.array([base + amp * math.sin(2 * math.pi * t / days)
                         for t in range(days)])

    model = Model(
        starttime=starttime,
        endtime=endtime,
        crs="EPSG:4326",
    )

    node_id = 1
    AREA    = 200e6  # m² per basin (simplified)
    Q_SCALE = base + amp  # max expected Lobith flow

    for i, node_cfg in enumerate(cfg["nodes"]):
        frac = node_cfg["flow_fraction"]
        name = node_cfg["name"]
        lon  = node_cfg["lon"]
        lat  = node_cfg["lat"]
        thr  = node_cfg["threshold_level"]

        q_branch = lobith_q * frac

        # FlowBoundary → Basin → TRC → Terminal
        fb_id   = node_id;       node_id += 1
        b_id    = node_id;       node_id += 1
        trc_id  = node_id;       node_id += 1
        term_id = node_id;       node_id += 1

        fb   = model.flow_boundary.add(
            Node(fb_id, Point(lon + 0.1, lat - 0.1), name=f"FB-{name}"),
            [flow_boundary.Time(time=dates, flow_rate=q_branch)],
        )
        b    = model.basin.add(
            Node(b_id, Point(lon, lat), name=name),
            [basin.Profile(area=[AREA, AREA], level=[0.0, 5.0]),
             basin.State(level=[thr])],
        )
        trc  = model.tabulated_rating_curve.add(
            Node(trc_id, Point(lon - 0.1, lat + 0.05), name=f"TRC-{name}"),
            [tabulated_rating_curve.Static(
                level=[0.0, 5.0],
                flow_rate=[0.0, Q_SCALE * frac * 2],
            )],
        )
        term = model.terminal.add(
            Node(term_id, Point(lon - 0.3, lat + 0.1), name=f"Term-{name}")
        )

        model.link.add(fb, b)
        model.link.add(b, trc)
        model.link.add(trc, term)

    toml_path = out_dir / "ribasim.toml"
    model.write(toml_path)
    print(f"ribasim model written to {toml_path}", flush=True)

    # Write a node-id mapping so the caller can look up results
    mapping = {}
    nid = 1
    for node_cfg in cfg["nodes"]:
        mapping[node_cfg["name"]] = {
            "fb_id": nid, "basin_id": nid + 1, "trc_id": nid + 2, "term_id": nid + 3
        }
        nid += 4
    with open(out_dir / "node_mapping.json", "w") as f:
        json.dump(mapping, f)


if __name__ == "__main__":
    out_path = Path(sys.argv[1])
    settings = json.loads(sys.argv[2])
    build(out_path, settings)
