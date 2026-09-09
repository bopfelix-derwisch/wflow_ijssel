"""Nachtelijke wflow-nowcast met warme state.

Cyclus:
  1. bouw forcing over [D-1, D+14]
  2. draai wflow vanaf de instates van gisteren
  3. ALLEEN bij exitcode 0: promoveer outstates -> instates
  4. schrijf latest.json atomair

Stap 3 is kritiek: één mislukte nacht mag de warme keten niet breken. Bij
falen blijven de oude instates staan en draait de volgende nacht met een dag
extra forcing.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
WFLOW_DIR = ROOT / "wflow_ijssel"
CONFIG = WFLOW_DIR / "ijssel_config_operational.toml"
SYSIMAGE = ROOT / "wflow_sysimage.so"
RUN_SCRIPT = ROOT / "run_ijssel.jl"

OP_DIR = WFLOW_DIR / "data" / "operational"
OUT_DIR = WFLOW_DIR / "data" / "output_operational"
FORCING = OP_DIR / "forcing-operational.nc"
IN_STATES = OP_DIR / "instates-ijssel.nc"
OUT_STATES = OUT_DIR / "outstates-ijssel.nc"
LATEST = WFLOW_DIR / "data" / "forecast" / "latest.json"

HORIZON = 14


def build_forcing_window(path, start: str, end: str) -> dict:
    from wflow_ijssel.operational.forcing import build_forcing
    return build_forcing(path, start, end)


def run_wflow(config_path=CONFIG, timeout: int = 1800) -> int:
    """Draai wflow via run_ijssel.jl. Retourneert de exitcode."""
    cmd = ["julia"]
    if SYSIMAGE.exists():
        cmd += [f"--sysimage={SYSIMAGE}"]
    else:
        logger.warning("wflow_sysimage.so ontbreekt — run duurt ~2 min i.p.v. ~17 s")
    cmd += [f"--project={ROOT}", str(RUN_SCRIPT), str(config_path)]

    log_path = OUT_DIR / "run.log"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with open(log_path, "wb") as log:
        proc = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=log, timeout=timeout)
    logger.info("wflow exit=%d na %.0fs (log: %s)",
                proc.returncode, time.monotonic() - t0, log_path)
    return proc.returncode


def promote_states(out_states=None, in_states=None) -> bool:
    """Maak de outstates van deze run de instates van morgen."""
    out_states = Path(out_states or OUT_STATES)
    in_states = Path(in_states or IN_STATES)
    if not out_states.exists():
        logger.warning("outstates ontbreekt (%s) — instates blijven staan", out_states)
        return False
    shutil.copy2(out_states, in_states)
    return True


def read_csv_output(path) -> dict:
    """Lees output_ijssel.csv naar dagreeksen."""
    import csv as _csv

    dates, q_kampen, q_west = [], [], []
    with open(path, newline="") as f:
        for row in _csv.DictReader(f):
            dates.append(row["time"][:10])
            q_kampen.append(float(row["Q_kampen"]))
            q_west.append(float(row["Q_westervoort"]))
    return {"dates": dates, "q_kampen": q_kampen, "q_westervoort": q_west}


def write_latest(path, payload: dict) -> Path:
    """Schrijf atomair: nooit een half bestand voor de lezer."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1))
    os.replace(tmp, path)
    return path


def run_nightly() -> dict:
    """De volledige nachtelijke cyclus."""
    today = date.today()
    start = (today - timedelta(days=1)).isoformat()
    end = (today + timedelta(days=HORIZON)).isoformat()

    meta = build_forcing_window(FORCING, start, end)
    code = run_wflow()
    if code != 0:
        logger.error("nachtrun mislukt (exit %d) — instates ongemoeid gelaten", code)
        return {"status": "mislukt", "exit_code": code}

    promoted = promote_states()
    series = read_csv_output(OUT_DIR / "output_ijssel.csv")
    payload = {
        "status": "ok",
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "issue_date": today.isoformat(),
        "model": "wflow SBM 1.0.2 (kinematic wave)",
        "boundary_sources": meta.get("sources"),
        "lobith_ratio": meta.get("ratio"),
        "states_promoted": promoted,
        "series": series,
    }
    write_latest(LATEST, payload)
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    res = run_nightly()
    raise SystemExit(0 if res.get("status") == "ok" else 1)
