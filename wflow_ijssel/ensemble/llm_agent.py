"""LLM-interpretatie van ensemble-resultaten via llama.cpp OpenAI-compatible API."""
from __future__ import annotations
import json
import requests


SYSTEM_PROMPT = """Je bent een hydroloog die ensemble-modelresultaten interpreteert.
Geef een beknopte, feitelijke samenvatting in het Nederlands.
Noem: de bandbreedte van piekafvoeren, het hoogwaterrisico, en de belangrijkste onzekerheid.
Maximaal 200 woorden. Gebruik geen opsomming — schrijf doorlopende tekst."""


def build_user_message(stats: dict, threshold: float) -> str:
    peaks = stats["peak_per_scenario"]
    days  = stats["days_above_threshold"]
    lines = [
        f"Ensemble-analyse IJssel bij Kampen (drempel: {threshold} m³/s):",
        f"Scenario's: {', '.join(stats['scenario_names'])}",
        f"Piekafvoeren per scenario (m³/s): {json.dumps(peaks)}",
        f"Dagen boven drempel per scenario: {json.dumps(days)}",
        f"Ensemble gemiddelde piek (m³/s): {max(stats['q_mean']):.0f}",
        f"P10–P90 bandbreedte op hotspot-dag ({stats['hotspot_date']}): "
        f"{stats['hotspot_spread']:.0f} m³/s",
        "",
        "Interpreteer deze resultaten voor een waterbeheerder.",
    ]
    return "\n".join(lines)


def interpret(stats: dict, llm_config: dict, threshold: float = 1500.0) -> str:
    """
    Stuur ensemble-statistieken naar llama.cpp en retourneer de interpretatie.
    llm_config: {'base_url': ..., 'model': ..., 'max_tokens': ..., 'temperature': ...}
    """
    payload = {
        "model":       llm_config["model"],
        "messages": [
            {"role": "system",  "content": SYSTEM_PROMPT},
            {"role": "user",    "content": build_user_message(stats, threshold)},
        ],
        "max_tokens":  llm_config.get("max_tokens", 600),
        "temperature": llm_config.get("temperature", 0.3),
    }

    resp = requests.post(
        f"{llm_config['base_url']}/v1/chat/completions",
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()
