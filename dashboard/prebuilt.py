"""Vooraf berekende antwoorden, gemaakt door de nachtrun.

Gemeten op 2026-09-09, met koude caches: `/api/forecast` deed er **74 seconden**
over, `/api/grondwater/reservoir` 45 en de AI-interventie 12. De caches in het
serverproces houden dat 15 minuten vast (het reservoirmodel 6 uur) en zijn leeg
na elke herstart. Een bezoeker die meer dan een kwartier na de vorige langskomt,
wacht dus opnieuw ruim een minuut op een lege grafiek.

Dat werk hoort in de nachtrun, niet in de eerste bezoeker. Die rekent toch al
alles uit; hij schrijft het resultaat nu ook weg. De endpoints serveren dat
bestand zolang het van vandaag is, en vallen anders terug op live rekenen — een
mislukte nacht maakt de pagina traag, niet stuk.

Dat een bezoeker om 20:00 cijfers van 03:00 ziet is hier geen bezwaar maar juist
consistent: het is één uitgifte, met één uitgiftedatum, precies zoals een
operationele verwachting hoort te werken. `prebuilt_at` staat in het antwoord.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date as _date
from pathlib import Path

logger = logging.getLogger(__name__)

DIR = Path(__file__).resolve().parent.parent / "wflow_ijssel" / "data" / "forecast"

# Namen van de vooraf berekende antwoorden.
FORECAST = "api_forecast"
INTERVENTION = "api_intervention"
RESERVOIR = "api_reservoir"


def _pad(naam: str) -> Path:
    return DIR / f"{naam}.json"


def write(naam: str, payload: dict, today=None) -> Path:
    """Schrijf atomair, met de uitgiftedatum erin zodat de lezer hem kan toetsen."""
    today = today or _date.today()
    pad = _pad(naam)
    pad.parent.mkdir(parents=True, exist_ok=True)
    inhoud = {"prebuilt_for": today.isoformat(),
              "prebuilt_at": __import__("time").strftime("%Y-%m-%d %H:%M"),
              "payload": payload}
    tmp = pad.with_suffix(pad.suffix + ".tmp")
    tmp.write_text(json.dumps(inhoud))
    os.replace(tmp, pad)
    return pad


def read(naam: str, today=None, max_age_days: int = 1):
    """Lees een vooraf berekend antwoord, of None.

    None bij: bestand ontbreekt, onleesbaar, of ouder dan `max_age_days`. De
    aanroeper rekent dan zelf — trager, maar de pagina blijft werken.
    """
    today = today or _date.today()
    pad = _pad(naam)
    if not pad.exists():
        return None
    try:
        inhoud = json.loads(pad.read_text())
        voor = _date.fromisoformat(inhoud["prebuilt_for"])
    except Exception as e:
        logger.warning("vooraf berekend antwoord %s onleesbaar: %s", naam, e)
        return None

    leeftijd = (today - voor).days
    if leeftijd > max_age_days or leeftijd < 0:
        logger.info("vooraf berekend antwoord %s is %d dagen oud — zelf rekenen",
                    naam, leeftijd)
        return None

    payload = inhoud.get("payload")
    if isinstance(payload, dict):
        payload = {**payload, "prebuilt_at": inhoud.get("prebuilt_at"),
                   "prebuilt_age_days": leeftijd}
    return payload
