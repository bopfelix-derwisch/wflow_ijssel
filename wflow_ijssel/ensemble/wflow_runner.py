"""Voer één Wflow-scenario uit via subprocess."""
from __future__ import annotations
import subprocess
import time
from pathlib import Path


def run_scenario(scenario: dict, julia_project: str, run_script: str,
                 timeout: int = 7200) -> Path:
    """
    Draait julia --project=<julia_project> <run_script> <config_path>.
    Blokkeert tot voltooiing. Gooit RuntimeError bij non-zero exit.
    Retourneert Path naar output NC.
    """
    config_path = scenario["config_path"]
    output_nc   = Path(scenario["output_nc"])

    cmd = [
        "julia",
        f"--project={julia_project}",
        run_script,
        config_path,
    ]

    print(f"  → Run: {scenario['name']} (multiplier={scenario['multiplier']})")
    t0 = time.monotonic()

    result = subprocess.run(
        cmd,
        cwd=julia_project,
        capture_output=False,
        timeout=timeout,
    )

    elapsed = time.monotonic() - t0
    if result.returncode != 0:
        raise RuntimeError(
            f"Wflow mislukt voor scenario '{scenario['name']}' "
            f"(exit {result.returncode}) na {elapsed:.0f}s"
        )

    if not output_nc.exists():
        raise FileNotFoundError(
            f"Output NC niet aangemaakt: {output_nc}"
        )

    print(f"  ✓ Klaar: {scenario['name']} in {elapsed:.0f}s")
    return output_nc
