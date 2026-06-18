"""WL-CHAT-1 — bevraagbare uitleg-chatbot, gegrond in de provenance-laag.

Principe (PO-noot): de bot put UITSLUITEND uit de WL-PROV/GOV-bronnen + een
feiten-brief, niet uit vrije generatie. Achter login (tokenkosten-beheersing) met
een per-sessie + globaal dagbudget en een rate-limit in lijn met de 60 req/min-grens.
Antwoorden verwijzen terug naar de uitleg (tabs/docs).
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT     = Path(__file__).parent.parent
DOCS_DIR = ROOT / "docs"

# ── grounding-corpus (PROV-bronnen + feiten-brief) ──────────────────────────
# Klein genoeg om volledig mee te sturen; geen vector-DB nodig.
_GROUNDING_DOCS = [
    "WL-GOV-1_wel_niet.md",
    "WL-PROV-2_schematisatie.md",
    "grondwater_voorspelling_voorstel.md",
    "WL-BRO-0_feasibility.md",
]

_FACTS_BRIEF = """# Waterlab — feiten-brief (voor de uitleg-assistent)

Waterlab is een persoonlijk leer-/PoC-platform voor hydrologische modellering + AI,
gebouwd door één persoon op een NVIDIA Jetson AGX Orin. Het is een indicatief leerlab,
GEEN operationeel voorspelsysteem (zie WL-GOV-1).

## Tabs (navigatie)
- Waterlab: landing met de redeneerlijn (waardestromen W1/W2/W4/W5 × informatiefuncties) en de wél/niet-grens.
- Handleiding: navigatie, de drie API's en databronnen.
- Rijn & IJssel: het stroomgebied (Pannerdense Kop, Westervoort → Kampen).
- POC's: de negen proeven, elk met een uitklapbare Herkomst-keten (databron → randvoorwaarde → modelstap → output → AI-duiding) — dat is WL-PROV-1.
- Verwachting: live 14-daagse IJssel-verwachting + integrale Claude-duiding.
- Ensemble AI / Multimodel: wflow-ensemble (5 neerslagscenario's) en de Ribasim→AI→wflow-pipeline.
- Jan 1995 / Zomer 2018 / Jul 2021: historische wflow-simulaties; klik een bol (Kampen/Westervoort) voor detail per punt.
- Grondwater: BRO-grondwater vs IJssel + lag-correlatie + reservoirmodel.
- Validatie: gesimuleerd vs gemeten met skill-score (NSE/KGE/Pearson r/bias) + hindcast-terugblik. Dat is WL-VAL-1/2.
- FEWS: Waterlab als FEWS PI REST 1.25-service.

## De negen proeven (kort)
1. 14-daagse verwachting + Claude expert-duiding, integraal met grondwater. Statistisch recessiemodel, geen gekalibreerde nowcast.
2. Ensemble AI: 5 wflow SBM-runs (neerslag ×0.70–×1.30) op zomer 2018; Qwen2.5-32B lokaal interpreteert.
3. Multimodel: Ribasim (netwerk) → LLM kiest kritieke knoop → wflow ×5 deelbekken. Op ARM64.
4. Hoogwater jan 1995: wflow SBM, instroom Westervoort gesynthetiseerd uit RIZA/RWS-archief.
5. Droogte zomer 2018: wflow SBM op ERA5; geen grondwateronttrekking → overschatting bij droogte.
6. Hoogwater jul 2021: twee runs — ERA5 vs gemeten RWS-inflow Westervoort; validatie via Nash-Sutcliffe.
7. FEWS PI REST: Deltares-compatibele tijdreeksen-API (filters/locations/parameters/timeseries).
8. GraphQL-façade: read-only query-laag op /graphql; resolvers delegeren naar bestaande bronnen (geen tweede datapad).
9. BRO-grondwater ↔ IJssel: gemeten grondwater (BRO GLD via PDOK) + lineair reservoirmodel; data-gedreven, geen MODFLOW/iMOD-kwelmodel.

FEWS (7) en GraphQL (8) zijn een dwarse platform-/interoplaag, geen waardestroom.

## API's
- FEWS PI REST 1.25 op /fews/rest/fewspiservice/v1/
- GraphQL op /graphql (GraphiQL); read-only, max 60 req/min/IP, diepte 10.
- REST: /api/forecast, /api/grondwater, /api/ensemble, /api/multimodel, /api/validation.

## Eerlijke kanttekeningen (uit de validatie, WL-VAL-1)
- Gemeten debiet bestaat alleen bij Westervoort/Lobith (instroom), NIET bij Kampen (RWS publiceert daar alleen waterpeil). Er is dus geen gemeten Kampen-afvoer om de modeloutput tegen te toetsen.
- De gesimuleerde wflow-waarde "h" bij Kampen is river_water__depth (rivierwaterdiepte, m boven de bedding), GEEN waterpeil in m+NAP — absoluut onvergelijkbaar met de RWS-meting (datum-offset ~12 m, amplitude ~38×). Alleen de dynamiek (Pearson r≈0.5) is zinnig.
- De Westervoort-afvoerverwachting (recessie) overschat systematisch; de fout (RMSE) groeit met de horizon (dag 14 ~100 m³/s), maar de onzekerheidsband vangt ~99% van de realisaties (hindcast, WL-VAL-2).
- Niets is te valideren vóór ~2000 (geen RWS-data); 1995-instroom was zelf gesynthetiseerd.

## Herkomst & schematisatie (WL-PROV-2)
wflow SBM rekent op een raster (~1 km, Copernicus DEM + pyflwdir, PDOK NWB LDD-fix) MET een bovenstroomse instroom-randvoorwaarde bij Westervoort — het is geen 1-D-float. Westervoort = de IJssel-tak ná de Pannerdense Kop (~13% van de Rijn, ~25% bij hoogwater); Lobith is de Rijn-totaal en alleen referentie.
"""

_SYSTEM_PROMPT = (
    "Je bent de uitleg-assistent van Waterlab. Beantwoord vragen UITSLUITEND op basis van de "
    "WATERLAB-CONTEXT hieronder. Verzin niets: staat het antwoord niet in de context, zeg dat "
    "eerlijk en verwijs naar de Handleiding-tab of de Herkomst-keten op de POC's-tab. Antwoord in "
    "het Nederlands, bondig (max ~150 woorden), feitelijk, zonder verkooppraat. Noem waar relevant "
    "de tab of het document waar het vandaan komt (bv. 'zie de Validatie-tab' of 'docs/WL-PROV-2'). "
    "Waterlab is een indicatief leerlab, geen operationeel systeem — wees daar eerlijk over.\n\n"
    "=== WATERLAB-CONTEXT ===\n"
)

# Vaste 'lees verder'-bronnen onder elk antwoord (link terug naar de uitleg).
_SOURCES = [
    {"label": "Handleiding", "tab": "handleiding"},
    {"label": "Herkomst (POC's)", "tab": "pocs"},
    {"label": "Validatie", "tab": "validatie"},
    {"label": "WL-PROV-2 · schematisatie", "doc": "WL-PROV-2_schematisatie"},
    {"label": "WL-GOV-1 · wél/niet", "doc": "WL-GOV-1_wel_niet"},
]

_corpus_cache = None


def _corpus() -> str:
    global _corpus_cache
    if _corpus_cache is None:
        parts = [_FACTS_BRIEF]
        for name in _GROUNDING_DOCS:
            p = DOCS_DIR / name
            if p.is_file():
                parts.append(f"\n\n# === docs/{name} ===\n" + p.read_text(encoding="utf-8"))
        _corpus_cache = "\n".join(parts)
    return _corpus_cache


# ── auth + budget ───────────────────────────────────────────────────────────
def _password() -> str:
    return os.environ.get("WATERLAB_CHAT_PASSWORD", "waterlab")

_SESSIONS: dict = {}          # token -> {created, messages, hits[], tok_in, tok_out}
_SESSION_MSG_CAP = 30         # berichten per sessie
_RATE_WINDOW = 60             # s
_RATE_MAX = 8                 # berichten per minuut per sessie
_daily = {"date": "", "count": 0}
_DAILY_CAP = 300              # harde kostenplafond: berichten per dag (alle sessies)
_MAX_TOKENS = 500


def login(password: str) -> str | None:
    if not password or password != _password():
        return None
    token = secrets.token_urlsafe(18)
    _SESSIONS[token] = {"created": time.time(), "messages": 0, "hits": [],
                        "tok_in": 0, "tok_out": 0}
    return token


def _check_budget(token: str) -> tuple[bool, str]:
    sess = _SESSIONS.get(token)
    if sess is None:
        return False, "auth"
    today = date.today().isoformat()
    if _daily["date"] != today:
        _daily.update(date=today, count=0)
    if _daily["count"] >= _DAILY_CAP:
        return False, "Dagbudget bereikt — de uitleg-assistent is morgen weer beschikbaar."
    if sess["messages"] >= _SESSION_MSG_CAP:
        return False, f"Sessiebudget bereikt ({_SESSION_MSG_CAP} vragen). Log opnieuw in voor een nieuwe sessie."
    now = time.monotonic()
    sess["hits"] = [h for h in sess["hits"] if h > now - _RATE_WINDOW]
    if len(sess["hits"]) >= _RATE_MAX:
        return False, f"Even rustig — max {_RATE_MAX} vragen per minuut."
    sess["hits"].append(now)
    return True, ""


def answer(token: str, question: str, history: list | None = None) -> dict:
    ok, reason = _check_budget(token)
    if not ok:
        return {"ok": False, "reason": reason, "code": ("auth" if reason == "auth" else "budget")}
    question = (question or "").strip()[:1000]
    if not question:
        return {"ok": False, "reason": "Lege vraag.", "code": "input"}

    import anthropic as _anthropic
    msgs = []
    for turn in (history or [])[-6:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()[:2000]
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": question})

    try:
        client = _anthropic.Anthropic()
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT + _corpus(),
            messages=msgs,
        )
        text = resp.content[0].text.strip()
        sess = _SESSIONS[token]
        sess["messages"] += 1
        _daily["count"] += 1
        if getattr(resp, "usage", None):
            sess["tok_in"] += getattr(resp.usage, "input_tokens", 0) or 0
            sess["tok_out"] += getattr(resp.usage, "output_tokens", 0) or 0
        return {
            "ok": True, "answer": text, "sources": _SOURCES,
            "remaining": _SESSION_MSG_CAP - sess["messages"],
        }
    except Exception as e:
        logger.warning("chat-antwoord faalde: %s", e)
        return {"ok": False, "reason": "De assistent is even niet bereikbaar.", "code": "error"}
