"""Nachtelijke wflow-nowcast met warme state.

Cyclus — TWEE runs, niet één (zie docs/superpowers/specs/2026-09-08-verwachting-
v2-wflow-design.md §3.2 en de Critical-1-bevinding in
.superpowers/sdd/2026-09-08-verwachting-v2-fase-c/): wflow schrijft zijn
state-snapshot aan het EIND van de simulatie, dus een enkele run over
[D-1, D+14] zou de warme state besmetten met dertien dagen *voorspelde*
neerslag in plaats van gemeten weer. Vandaar het knip in tweeën:

  1. NOWCAST-stap: forcing over [D-1, D] uit gemeten data, draai wflow vanaf
     de instates van gisteren. ALLEEN bij exitcode 0 én bestaande outstates:
     promoveer outstates -> instates. Dit is de enige stap die de warme
     keten bijwerkt.
  2. FORECAST-stap: forcing over [D, D+14], draai wflow opnieuw vanaf de
     zojuist gepromoveerde state. Lees hieruit de reeks voor `latest.json`.
     Promoveer deze outstates NIET.

Beide runs gebruiken dezelfde config en hetzelfde forcing-pad; de forcing
wordt tussen de runs herschreven.

Foutafhandeling: mislukt stap 1 (exitcode of promotie), dan blijven de
instates ongemoeid en heeft stap 2 geen zin -> overslaan. Mislukt stap 2
(exitcode, ontbrekende CSV of een lege reeks), dan is de warme state via
stap 1 wél al terecht bijgewerkt, maar is er geen nieuwe verwachting. In
beide gevallen wordt een mislukte poging zichtbaar geregistreerd (zie
`_record_failed_attempt`) in plaats van stil te falen: de laatste goede
reeks blijft staan, met een waarschuwing erbij.
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

# Spin-up: de meegeleverde instates komen uit de historische proef van december
# 1994 en hebben een vrijwel leeg riviernetwerk. Zonder aanloop levert een run
# van vijftien dagen ~0 m³/s bij Kampen terwijl de instroom bij Westervoort
# klopt — wflow klaagt daar niet over. De 1995-proef had ~60 dagen nodig om het
# kanaal te vullen; een jaar geeft daarnaast de bodem- en grondwaterberging tijd
# om op de werkelijke toestand uit te komen.
SPINUP_DAYS = 365
SPINUP_TIMEOUT = 5400


def build_forcing_window(path, start: str, end: str) -> dict:
    from wflow_ijssel.operational.forcing import build_forcing
    return build_forcing(path, start, end)


def _julia_bin() -> str:
    """Vind het julia-binair, ook zonder het PATH van een interactieve shell.

    Onder systemd is het PATH kaal en zit juliaup er niet in — een kale "julia"
    geeft dan FileNotFoundError. We zoeken eerst in het PATH en vallen daarna
    terug op de juliaup-locatie.
    """
    import shutil

    gevonden = shutil.which("julia")
    if gevonden:
        return gevonden
    fallback = Path.home() / ".juliaup" / "bin" / "julia"
    if fallback.exists():
        return str(fallback)
    raise FileNotFoundError(
        "julia niet gevonden in PATH noch op ~/.juliaup/bin/julia — "
        "zonder Julia kan de wflow-nowcast niet draaien")


def run_wflow(config_path=CONFIG, timeout: int = 1800) -> int:
    """Draai wflow via run_ijssel.jl. Retourneert de exitcode."""
    cmd = [_julia_bin()]
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
    """Maak de outstates van deze run de instates van morgen.

    Atomair: kopieer eerst naar een tijdelijk bestand in dezelfde map, hernoem
    dan pas naar de live instates (zelfde patroon als `write_latest`). Een
    rechtstreekse `shutil.copy2` over het levende instates-bestand zou bij
    onderbreking een half bestand achterlaten en de warme keten breken.
    """
    out_states = Path(out_states or OUT_STATES)
    in_states = Path(in_states or IN_STATES)
    if not out_states.exists():
        logger.warning("outstates ontbreekt (%s) — instates blijven staan", out_states)
        return False
    tmp = in_states.with_suffix(in_states.suffix + ".tmp")
    shutil.copy2(out_states, tmp)
    os.replace(tmp, in_states)
    return True


def read_csv_output(path) -> dict:
    """Lees output_ijssel.csv naar dagreeksen."""
    import csv as _csv

    dates, q_kampen, q_west, q_olst = [], [], [], []
    with open(path, newline="") as f:
        for row in _csv.DictReader(f):
            dates.append(row["time"][:10])
            q_kampen.append(float(row["Q_kampen"]))
            q_west.append(float(row["Q_westervoort"]))
            # Olst is later toegevoegd als toetspunt; oudere CSV's missen de kolom.
            if "Q_olst" in row:
                q_olst.append(float(row["Q_olst"]))
    out = {"dates": dates, "q_kampen": q_kampen, "q_westervoort": q_west}
    if q_olst:
        out["q_olst"] = q_olst
    return out


def _validate_series(series: dict) -> None:
    """Gooi ValueError als de reeks leeg is.

    Een CSV met alleen een header (geen datarijen) is geen fout die wflow of
    `read_csv_output` laat klappen — het levert gewoon lege lijsten. Zonder
    deze check zou zo'n reeks als `status: "ok"` weggeschreven worden: een
    "beschikbare" nowcast zonder data.
    """
    if not series.get("dates"):
        raise ValueError("output_ijssel.csv bevat geen databregels (alleen header?)")


def write_latest(path, payload: dict) -> Path:
    """Schrijf atomair: nooit een half bestand voor de lezer."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1))
    os.replace(tmp, path)
    return path


def _record_failed_attempt(today: date, exit_code, fase: str) -> dict:
    """Registreer een mislukte nachtrun zichtbaar, zonder de laatste goede reeks weg te gooien.

    Bij falen schreef `run_nightly` voorheen helemaal geen `latest.json`: de
    leeftijd van het bestaande bestand bleef zo 1 dag en `read_wflow_forecast`
    meldde onverstoorbaar "vers", ook na een mislukte nacht. Dat is precies de
    stille degradatie die de docstring van `read_wflow_forecast` uitsluit.

    Bestaat er al een `latest.json` (van een eerdere geslaagde nacht), werk die
    dan bij met een poging-registratie (`last_attempt`) en laat de laatste
    goede reeks ongemoeid staan — een verwachting van gisteren met een
    duidelijke waarschuwing is bruikbaarder dan geen verwachting. Bestaat er
    nog helemaal geen `latest.json`, schrijf er dan één met status "mislukt".
    """
    attempt = {"date": today.isoformat(), "outcome": "mislukt",
               "exit_code": exit_code, "fase": fase}

    bestaand = None
    if LATEST.exists():
        try:
            bestaand = json.loads(LATEST.read_text())
        except Exception as e:
            logger.warning("latest.json onleesbaar bij het registreren van een "
                            "mislukte poging (%s) — schrijf een verse mislukt-status", e)

    if bestaand is not None:
        bestaand["last_attempt"] = attempt
        write_latest(LATEST, bestaand)
        logger.error("nachtrun mislukt in fase '%s' (exit %s) — oude reeks van "
                      "%s blijft staan, met poging-registratie", fase, exit_code,
                      bestaand.get("issue_date"))
        return {"status": "mislukt", "exit_code": exit_code, "fase": fase,
                "previous_series_kept": True}

    payload = {"status": "mislukt",
               "generated_at": time.strftime("%Y-%m-%d %H:%M"),
               "issue_date": today.isoformat(),
               "last_attempt": attempt}
    write_latest(LATEST, payload)
    logger.error("nachtrun mislukt in fase '%s' (exit %s) — nog geen eerdere "
                  "goede reeks, latest.json krijgt status 'mislukt'", fase, exit_code)
    return {"status": "mislukt", "exit_code": exit_code, "fase": fase,
            "previous_series_kept": False}


def run_spinup(days: int = SPINUP_DAYS, today=None) -> dict:
    """Bouw de éérste warme state op, vanaf de koude historische instates.

    Draait wflow over `days` dagen gemeten forcing tot en met vandaag en
    promoveert het resultaat tot de operationele instates. Daarna kan
    `run_nightly` het per dag overnemen.

    Dit is eenmalig werk (~1-2 min rekentijd bij 365 dagen), maar het is geen
    optionele opwarming: zonder spin-up produceert de nachtrun een debiet bij
    Kampen dat orden van grootte te laag is, zonder enige foutmelding.

    Schrijft bewust GEEN latest.json — een spin-up is geen verwachting.
    """
    today = today or date.today()
    start = (today - timedelta(days=days)).isoformat()
    end = today.isoformat()

    logger.info("spin-up: %s .. %s (%d dagen)", start, end, days)
    meta = build_forcing_window(FORCING, start, end)
    code = run_wflow(timeout=SPINUP_TIMEOUT)
    if code != 0:
        logger.error("spin-up mislukt (exit %d) — instates ongemoeid gelaten", code)
        return {"status": "mislukt", "exit_code": code}

    promoted = promote_states()
    series = read_csv_output(OUT_DIR / "output_ijssel.csv")
    q_eind = series["q_kampen"][-1] if series["q_kampen"] else None
    logger.info("spin-up klaar: Q_kampen op de laatste dag = %s m3/s", q_eind)
    return {"status": "ok", "days": days, "start": start, "end": end,
            "states_promoted": promoted, "q_kampen_eind": q_eind,
            "boundary_sources": meta.get("sources")}


def run_nightly(today=None) -> dict:
    """De volledige nachtelijke cyclus: nowcast-stap (promoveert) + forecast-stap (promoveert niet)."""
    today = today or date.today()

    # ── stap 1: nowcast [D-1, D] uit gemeten data — bouwt de warme keten bij ──
    nowcast_start = (today - timedelta(days=1)).isoformat()
    nowcast_end = today.isoformat()
    try:
        build_forcing_window(FORCING, nowcast_start, nowcast_end)
    except Exception as e:
        # Open-Meteo of RWS onbereikbaar, of een gat in de dagreeks. Zonder deze
        # vangst crashte de nachtrun met een ongevangen exceptie: niets in
        # latest.json, dus een onzichtbare mislukking — precies wat de garantie
        # "elke mislukte poging is zichtbaar" moest uitsluiten.
        logger.error("nowcast-forcing kon niet gebouwd worden: %s", e)
        return _record_failed_attempt(today, None, fase="nowcast-forcing")

    code = run_wflow()
    if code != 0:
        logger.error("nowcast-stap mislukt (exit %d) — instates ongemoeid, "
                      "forecast-stap overgeslagen", code)
        return _record_failed_attempt(today, code, fase="nowcast")

    if not promote_states():
        # promote_states loggt zelf al waarom; hier alleen de nachtrun afbreken.
        return _record_failed_attempt(today, None, fase="nowcast-outstates-ontbreken")

    # ── stap 2: forecast [D, D+14] vanaf de zojuist gepromoveerde state ──────
    fcast_start = today.isoformat()
    fcast_end = (today + timedelta(days=HORIZON)).isoformat()
    try:
        meta = build_forcing_window(FORCING, fcast_start, fcast_end)
    except Exception as e:
        logger.error("forecast-forcing kon niet gebouwd worden: %s — de warme "
                      "state is wel bijgewerkt door de nowcast-stap", e)
        return _record_failed_attempt(today, None, fase="forecast-forcing")

    code = run_wflow()
    if code != 0:
        logger.error("forecast-stap mislukt (exit %d) — warme state is al "
                      "bijgewerkt door de nowcast-stap, maar geen nieuwe "
                      "verwachting", code)
        return _record_failed_attempt(today, code, fase="forecast")

    try:
        series = read_csv_output(OUT_DIR / "output_ijssel.csv")
        _validate_series(series)
    except (FileNotFoundError, ValueError) as e:
        logger.error("forecast-stap gaf exit 0 maar de uitvoer is niet "
                      "bruikbaar: %s", e)
        return _record_failed_attempt(today, None, fase="forecast-ongeldige-uitvoer")

    payload = {
        "status": "ok",
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "issue_date": today.isoformat(),
        "model": "wflow SBM 1.0.2 (kinematic wave)",
        "gauge": {
            "naam": "IJssel bij Kampen (modeluitstroom)",
            "lon": 5.838, "lat": 52.579,
            "noot": ("Dit is de pit waarin het afwateringsnetwerk vanaf Westervoort "
                     "eindigt, ~6 km van de stad Kampen. Bewust NIET de cel met de "
                     "grootste uparea (5.496/53.221) die de historische proeven "
                     "gebruiken: die is van de IJssel-tak afgekoppeld. Zie "
                     "docs/WL-SCHEMA-1_afgekoppelde-uitstroom.md."),
        },
        "archived": False,   # wordt hieronder gezet
        "boundary_sources": meta.get("sources"),
        "lobith_ratio": meta.get("ratio"),
        # Altijd True hier: we bereiken dit punt alleen als promote_states()
        # na de nowcast-stap is geslaagd (zie boven) — de forecast-stap
        # promoveert zelf bewust niets.
        "states_promoted": True,
        "series": series,
    }
    # Archiveer de uitgifte vóór het schrijven van latest.json, maar laat een
    # archiveerfout de nachtrun niet ongeldig maken: de verwachting zelf is goed.
    try:
        from wflow_ijssel.operational.archive import append_issue
        append_issue(payload)
        payload["archived"] = True
    except Exception as e:
        logger.warning("uitgifte kon niet gearchiveerd worden: %s", e)

    write_latest(LATEST, payload)
    return payload


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if "--spinup" in sys.argv:
        res = run_spinup()
    else:
        res = run_nightly()
    raise SystemExit(0 if res.get("status") == "ok" else 1)
