"""AI orchestrator: selecteert kritieke knoop en genereert wflow-parameters."""
from __future__ import annotations
import requests


SYSTEM_PROMPT = """Je bent een hydroloog die een waternetwerk analyseert tijdens een droogteperiode.
Geef een beknopte beslissingsmotivatie in het Nederlands.
Noem: welke knoop kritiek is, het waterdeficit, en waarom detailmodellering nodig is.
Maximaal 150 woorden. Schrijf doorlopende tekst, geen opsomming."""


def select_critical_node(nodes: list[dict]) -> dict:
    """Retourneert de knoop met het hoogste deficit_pct."""
    return max(nodes, key=lambda n: n["deficit_pct"])


def build_llm_prompt(critical_node: dict, all_nodes: list[dict]) -> str:
    lines = [
        "Netwerktoestand Rijn/IJssel (droogtescenario zomer 2018):",
    ]
    for n in all_nodes:
        lines.append(
            f"  {n['name']}: gemiddeld peil {n['mean_level']:.3f} m NAP "
            f"(drempel {n['threshold_level']} m, deficit {n['deficit_pct']:.1f}%)"
        )
    lines += [
        "",
        f"Kritieke knoop: {critical_node['name']} ({critical_node['deficit_pct']:.1f}% onder drempel).",
        "Beslis of detailmodellering met wflow nodig is en motiveer waarom.",
    ]
    return "\n".join(lines)


def call_llm(prompt: str, llm_config: dict) -> str:
    payload = {
        "model":    llm_config["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens":  llm_config.get("max_tokens", 400),
        "temperature": llm_config.get("temperature", 0.3),
    }
    resp = requests.post(
        f"{llm_config['base_url']}/v1/chat/completions",
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def build_orchestrator_result(
    critical_node: dict,
    catchment_map: dict,
    multipliers: list[float],
    scenario_names: list[str],
    llm_explanation: str,
) -> dict:
    trigger = (
        f"{critical_node['name']} {critical_node['deficit_pct']:.1f}% "
        f"onder drempelstand van {critical_node['threshold_level']} m NAP"
    )
    return {
        "critical_node":      critical_node["name"],
        "selected_catchment": catchment_map.get(critical_node["name"]),
        "deficit_pct":        critical_node["deficit_pct"],
        "trigger_reason":     trigger,
        "llm_explanation":    llm_explanation,
        "wflow_params": {
            "precip_multipliers": multipliers,
            "scenario_names":     scenario_names,
        },
    }


def orchestrate(network_result: dict, settings: dict) -> dict:
    """
    Volledige orchestratie: selecteer knoop, roep LLM aan, retourneer beslissing.
    network_result: output van simulate_network()
    """
    nodes         = network_result["nodes"]
    critical      = select_critical_node(nodes)
    catchment_map = settings["network"]["catchment_map"]
    multipliers   = settings["scenarios"]["values"]
    names         = settings["scenarios"]["names"]

    prompt      = build_llm_prompt(critical, nodes)
    explanation = call_llm(prompt, settings["llm"])

    return build_orchestrator_result(
        critical_node=critical,
        catchment_map=catchment_map,
        multipliers=multipliers,
        scenario_names=names,
        llm_explanation=explanation,
    )
