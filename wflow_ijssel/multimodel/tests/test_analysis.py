"""Tests voor analysis.py."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from multimodel.analysis import build_multimodel_stats


def _mock_network():
    return {
        "nodes": [
            {"name": "IJssel-Kampen", "lon": 5.921, "lat": 52.555,
             "mean_level": 0.18, "threshold_level": 0.5, "deficit_pct": 64.0,
             "flows": [180.0] * 10, "levels": [0.18] * 10, "flow_fraction": 0.3},
        ],
        "days": 10,
    }


def _mock_orchestrator():
    return {
        "critical_node":      "IJssel-Kampen",
        "selected_catchment": "ijssel",
        "deficit_pct":        64.0,
        "trigger_reason":     "IJssel-Kampen 64.0% onder drempelstand",
        "llm_explanation":    "Test motivatie.",
        "wflow_params": {
            "precip_multipliers": [0.1, 0.25],
            "scenario_names":     ["extreem_droog", "droog"],
        },
    }


def _mock_ensemble():
    return [
        {"name": "extreem_droog", "multiplier": 0.1, "peak_q": 120.0,
         "peak_date": "2018-07-15", "days_above_threshold": 0,
         "q": [100.0, 120.0], "h": [0.5, 0.6], "dates": ["2018-07-01", "2018-07-02"]},
        {"name": "droog", "multiplier": 0.25, "peak_q": 250.0,
         "peak_date": "2018-07-14", "days_above_threshold": 0,
         "q": [200.0, 250.0], "h": [0.8, 0.9], "dates": ["2018-07-01", "2018-07-02"]},
    ]


def test_build_multimodel_stats_structure():
    stats = build_multimodel_stats(_mock_network(), _mock_orchestrator(), _mock_ensemble())
    assert "ribasim" in stats
    assert "orchestrator" in stats
    assert "ensemble" in stats


def test_build_multimodel_stats_ribasim_section():
    stats = build_multimodel_stats(_mock_network(), _mock_orchestrator(), _mock_ensemble())
    r = stats["ribasim"]
    assert r["critical_node"] == "IJssel-Kampen"
    assert len(r["nodes"]) == 1
    assert r["nodes"][0]["deficit_pct"] == 64.0


def test_build_multimodel_stats_ensemble_section():
    stats = build_multimodel_stats(_mock_network(), _mock_orchestrator(), _mock_ensemble())
    e = stats["ensemble"]
    assert len(e["scenarios"]) == 2
    assert "timeseries" in e
    assert "q_mean" in e["timeseries"]
