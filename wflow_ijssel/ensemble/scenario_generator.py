"""Genereer neerslag-scenario's voor het ensemble."""
from __future__ import annotations
import copy
import tomli
import tomli_w
from pathlib import Path

import xarray as xr
import yaml


def load_settings(settings_path: Path) -> dict:
    with open(settings_path) as f:
        return yaml.safe_load(f)


def generate_scenarios(settings: dict, out_dir: Path) -> list[dict]:
    """Maak scenario-forcing en TOML-configs aan. Retourneer scenario-metadata."""
    root          = Path(settings["wflow_root"])
    base_forcing  = root / settings["base_forcing"]
    base_config   = root / settings["base_config"]
    names         = settings["scenarios"]["names"]
    multipliers   = settings["scenarios"]["values"]

    scenarios_dir = out_dir / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    with open(base_config, "rb") as f:
        base_toml = tomli.load(f)

    results = []
    for name, mult in zip(names, multipliers):
        scenario_dir = scenarios_dir / name
        scenario_dir.mkdir(exist_ok=True)

        forcing_out = scenario_dir / "forcing.nc"
        if not forcing_out.exists():
            with xr.open_dataset(base_forcing) as ds:
                ds["precip"] = (ds["precip"] * mult).clip(min=0)
                ds.to_netcdf(str(forcing_out))

        toml_out = scenario_dir / "config.toml"
        cfg = copy.deepcopy(base_toml)
        cfg["input"]["path_forcing"] = str(forcing_out.resolve())
        cfg.setdefault("output", {})["path"] = str((scenario_dir / "output.nc").resolve())
        cfg["dir_output"] = str(scenario_dir.resolve())

        with open(toml_out, "wb") as f:
            tomli_w.dump(cfg, f)

        results.append({
            "name":        name,
            "multiplier":  mult,
            "forcing_path": str(forcing_out),
            "config_path":  str(toml_out),
            "output_nc":    str(scenario_dir / "output.nc"),
            "output_dir":   str(scenario_dir),
        })

    return results
