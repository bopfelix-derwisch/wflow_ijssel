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
