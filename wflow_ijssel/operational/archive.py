"""Verificatie-archief: bewaar elke uitgegeven verwachting en scoor hem later.

Waarom niet een klassieke hindcast. Om wflow over het verleden na te rekenen heb
je voor elke uitgiftedatum de modelstaat van dát moment nodig. Die bestaat niet;
je zou een jaar opnieuw moeten doorrekenen met dagelijkse state-snapshots. Duur,
en de uitkomst hangt af van hoe goed je die reconstructie doet.

Operationele diensten lossen dat anders op: je bewaart wat je hebt uitgegeven en
scoort het zodra de werkelijkheid binnenkomt. Dat levert vandaag niets en over
een maand een eerlijk skill-cijfer — over precies de verwachtingen die het lab
werkelijk heeft gepubliceerd, niet over een gereconstrueerde variant ervan.

**Toetspunt is Olst, niet Kampen.** RWS meet daar dagelijks het debiet, en de
modelcel is geverifieerd onderdeel van het pad Westervoort → uitstroom. Bij
Kampen wijkt het model sterk af door het schematisatiedefect (WL-SCHEMA-1);
scoren op een punt waarvan je weet dat het netwerk kapot is, meet de fout van de
schematisatie en niet die van de verwachting.

Wat dit later mogelijk maakt: de modelfout per lead-time die fase E nodig heeft
om de ensembleband eerlijk op te blazen. Zonder die term is een band uit alleen
weersspreiding aantoonbaar te smal — `dashboard/assimilation.py` mat 21% dekking
waar 80% hoort.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "wflow_ijssel" / "data" / "forecast" / "archive.jsonl"

MAX_LEAD = 14


def append_issue(payload: dict, path=None) -> Path:
    """Leg één uitgifte vast. Idempotent: dezelfde uitgiftedatum overschrijft.

    Idempotentie is geen luxe — de nachtrun kan handmatig herhaald worden, en
    twee regels voor dezelfde dag zouden die uitgifte dubbel laten meewegen in
    de score.
    """
    path = Path(path or ARCHIVE)
    path.parent.mkdir(parents=True, exist_ok=True)

    issue = payload.get("issue_date")
    if not issue:
        raise ValueError("payload zonder issue_date kan niet gearchiveerd worden")
    serie = (payload.get("series") or {})
    regel = {
        "issue_date": issue,
        "generated_at": payload.get("generated_at"),
        "dates": serie.get("dates", []),
        "q_olst": serie.get("q_olst", []),
        "q_kampen": serie.get("q_kampen", []),
    }
    if not regel["dates"]:
        raise ValueError("uitgifte zonder dagreeks kan niet gearchiveerd worden")

    bestaand = [r for r in load_issues(path) if r.get("issue_date") != issue]
    bestaand.append(regel)
    bestaand.sort(key=lambda r: r["issue_date"])

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in bestaand))
    os.replace(tmp, path)
    logger.info("uitgifte %s gearchiveerd (%d in archief)", issue, len(bestaand))
    return path


def load_issues(path=None) -> list:
    """Lees het archief. Een kapotte regel wordt overgeslagen, niet fataal —
    één slechte nacht mag de hele verificatie niet blokkeren."""
    path = Path(path or ARCHIVE)
    if not path.exists():
        return []
    uit = []
    for n, regel in enumerate(path.read_text().splitlines(), 1):
        regel = regel.strip()
        if not regel:
            continue
        try:
            uit.append(json.loads(regel))
        except Exception as e:                                   # pragma: no cover
            logger.warning("archiefregel %d onleesbaar, overgeslagen: %s", n, e)
    return uit


def align_for_scoring(issues: list, realisatie: dict, veld: str = "q_olst",
                      max_lead: int = MAX_LEAD):
    """Zet het archief om in (voorspeld, gerealiseerd) per lead-time.

    Retourneert twee lijsten-van-lijsten, geschikt voor
    `dashboard.validation.horizon_skill`. Alleen uitgiftes waarvan álle
    lead-times een realisatie hebben doen mee: een uitgifte half meerekenen zou
    de latere lead-times systematisch bevoordelen, want juist de verste dagen
    ontbreken dan het vaakst.
    """
    preds, obs = [], []
    for r in issues:
        reeks = r.get(veld) or []
        dates = r.get("dates") or []
        if len(reeks) < max_lead or len(dates) < max_lead:
            continue
        p = list(reeks[:max_lead])
        o = [realisatie.get(d) for d in dates[:max_lead]]
        if any(v is None for v in o):
            continue
        preds.append(p)
        obs.append([float(v) for v in o])
    return preds, obs


def build_verification(realisatie: dict, issues=None, max_lead: int = MAX_LEAD) -> dict:
    """Skill per lead-time over de werkelijk uitgegeven verwachtingen."""
    from dashboard.validation import horizon_skill

    issues = load_issues() if issues is None else issues
    preds, obs = align_for_scoring(issues, realisatie, max_lead=max_lead)

    uit = {
        "station": "olst",
        "n_uitgiftes_in_archief": len(issues),
        "n_scoorbaar": len(preds),
        "note": ("Skill over de verwachtingen die dit lab werkelijk heeft uitgegeven, "
                 "gescoord tegen de RWS-meting bij Olst zodra die binnenkwam. Geen "
                 "gereconstrueerde hindcast: het archief groeit per nacht."),
    }
    if not preds:
        uit["available"] = False
        uit["reason"] = ("Nog geen uitgifte waarvan alle 14 dagen gerealiseerd zijn; "
                         "de eerste score kan pas twee weken na de eerste nachtrun.")
        return uit

    # horizon_skill verwacht ook een band; die hebben we nog niet (fase E), dus
    # geven we de voorspelling zelf mee. De dekking is dan betekenisloos en
    # wordt hieronder weggelaten in plaats van misleidend gerapporteerd.
    skill = horizon_skill(preds, obs, preds, preds)
    skill.pop("coverage", None)
    uit["available"] = True
    uit["per_horizon"] = skill
    return uit
