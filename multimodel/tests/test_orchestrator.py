"""Tests voor orchestrator.py."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from multimodel.orchestrator import select_critical_node, build_orchestrator_result


def _make_nodes(deficits):
    return [
        {"name": f"node_{i}", "deficit_pct": d, "mean_level": 0.3,
         "threshold_level": 0.5, "lon": 5.0 + i, "lat": 52.0}
        for i, d in enumerate(deficits)
    ]


def test_select_critical_node_picks_highest_deficit():
    nodes = _make_nodes([10.0, 55.0, 30.0])
    result = select_critical_node(nodes)
    assert result["name"] == "node_1"
    assert result["deficit_pct"] == 55.0


def test_build_orchestrator_result_maps_catchment():
    nodes = _make_nodes([47.0])
    nodes[0]["name"] = "IJssel-Kampen"
    catchment_map = {"IJssel-Kampen": "ijssel"}
    multipliers   = [0.10, 0.25, 0.40, 0.60, 0.80]
    names         = ["extreem_droog", "droog", "matig_droog", "licht_droog", "normaal"]

    result = build_orchestrator_result(
        critical_node=nodes[0],
        catchment_map=catchment_map,
        multipliers=multipliers,
        scenario_names=names,
        llm_explanation="Test uitleg.",
    )
    assert result["selected_catchment"] == "ijssel"
    assert result["critical_node"] == "IJssel-Kampen"
    assert result["deficit_pct"] == 47.0
    assert len(result["wflow_params"]["precip_multipliers"]) == 5
    assert result["llm_explanation"] == "Test uitleg."


def test_build_orchestrator_result_unknown_catchment():
    nodes = _make_nodes([20.0])
    nodes[0]["name"] = "Onbekend"
    result = build_orchestrator_result(
        critical_node=nodes[0],
        catchment_map={"IJssel-Kampen": "ijssel"},
        multipliers=[0.5],
        scenario_names=["test"],
        llm_explanation="",
    )
    assert result["selected_catchment"] is None


def test_build_orchestrator_result_trigger_reason():
    nodes = _make_nodes([47.3])
    nodes[0]["name"] = "IJssel-Kampen"
    nodes[0]["threshold_level"] = 0.5
    result = build_orchestrator_result(
        critical_node=nodes[0],
        catchment_map={"IJssel-Kampen": "ijssel"},
        multipliers=[0.5],
        scenario_names=["test"],
        llm_explanation="",
    )
    assert "IJssel-Kampen" in result["trigger_reason"]
    assert "47.3%" in result["trigger_reason"]
