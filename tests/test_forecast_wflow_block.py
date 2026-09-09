"""Het wflow-blok in /api/forecast: leeftijd, status en terugval (fase C)."""
import json
from datetime import date
from pathlib import Path

import pytest

from dashboard.forecast import read_wflow_forecast


def _schrijf(tmp_path, issue: str, status: str = "ok"):
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({
        "status": status,
        "issue_date": issue,
        "generated_at": issue + " 03:00",
        "model": "wflow SBM 1.0.2 (kinematic wave)",
        "gauge": {"naam": "IJssel bij Kampen (modeluitstroom)",
                  "lon": 5.838, "lat": 52.579},
        "series": {"dates": ["2026-09-08", "2026-09-09"],
                   "q_kampen": [150.0, 160.0],
                   "q_westervoort": [120.0, 130.0]},
    }))
    return p


def test_verse_forecast_is_beschikbaar(tmp_path):
    p = _schrijf(tmp_path, "2026-09-08")
    r = read_wflow_forecast(p, today=date(2026, 9, 8))
    assert r["available"] is True
    assert r["status"] == "vers"
    assert r["age_days"] == 0
    assert r["q_kampen"] == [150.0, 160.0]
    assert r["gauge"]["lon"] == 5.838


def test_een_dag_oud_telt_nog_als_vers(tmp_path):
    p = _schrijf(tmp_path, "2026-09-08")
    r = read_wflow_forecast(p, today=date(2026, 9, 9))
    assert r["available"] is True
    assert r["status"] == "vers"
    assert r["age_days"] == 1


def test_twee_dagen_oud_is_verouderd_maar_nog_bruikbaar(tmp_path):
    p = _schrijf(tmp_path, "2026-09-08")
    r = read_wflow_forecast(p, today=date(2026, 9, 10))
    assert r["available"] is True
    assert r["status"] == "verouderd"
    assert r["age_days"] == 2
    assert "2026-09-08" in r["note"]


def test_ouder_dan_48_uur_vervalt(tmp_path):
    p = _schrijf(tmp_path, "2026-09-08")
    r = read_wflow_forecast(p, today=date(2026, 9, 11))
    assert r["available"] is False
    assert r["status"] == "vervallen"
    assert r["age_days"] == 3
    assert r["q_kampen"] == []


def test_ontbrekend_bestand_geeft_nette_terugval(tmp_path):
    r = read_wflow_forecast(tmp_path / "bestaat-niet.json", today=date(2026, 9, 8))
    assert r["available"] is False
    assert r["status"] == "ontbreekt"
    assert r["q_kampen"] == []


def test_kapotte_json_geeft_nette_terugval(tmp_path):
    p = tmp_path / "latest.json"
    p.write_text("{dit is geen json")
    r = read_wflow_forecast(p, today=date(2026, 9, 8))
    assert r["available"] is False
    assert r["status"] == "onleesbaar"


def test_ongeldige_uitgiftedatum_geeft_nette_terugval(tmp_path):
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({"status": "ok", "issue_date": "gisteren", "series": {}}))
    r = read_wflow_forecast(p, today=date(2026, 9, 8))
    assert r["available"] is False
    assert r["status"] == "onleesbaar"


def test_mislukte_nachtrun_is_niet_beschikbaar(tmp_path):
    p = _schrijf(tmp_path, "2026-09-08", status="mislukt")
    r = read_wflow_forecast(p, today=date(2026, 9, 8))
    assert r["available"] is False
    assert r["status"] == "mislukt"


def test_toekomstige_uitgiftedatum_telt_als_vers(tmp_path):
    """Klokverschil mag geen negatieve leeftijd tot een vervallen lijn maken."""
    p = _schrijf(tmp_path, "2026-09-09")
    r = read_wflow_forecast(p, today=date(2026, 9, 8))
    assert r["available"] is True
    assert r["status"] == "vers"


def test_mislukte_poging_blijft_zichtbaar_ook_als_de_oude_reeks_nog_vers_is(tmp_path):
    """Bevinding Critical 2: een mislukte nachtrun mag niet onzichtbaar zijn,
    ook al toont de vorige goede reeks nog status "vers"."""
    p = _schrijf(tmp_path, "2026-09-08")
    data = json.loads(p.read_text())
    data["last_attempt"] = {"date": "2026-09-09", "outcome": "mislukt",
                            "exit_code": 1, "fase": "nowcast"}
    p.write_text(json.dumps(data))

    r = read_wflow_forecast(p, today=date(2026, 9, 9))
    assert r["available"] is True
    assert r["status"] == "vers"
    assert "mislukt" in r["note"]
    assert "2026-09-09" in r["note"]


def test_geslaagde_poging_laat_geen_oude_waarschuwing_achter(tmp_path):
    """Een last_attempt met outcome "ok" mag geen waarschuwing in de note zetten."""
    p = _schrijf(tmp_path, "2026-09-08")
    data = json.loads(p.read_text())
    data["last_attempt"] = {"date": "2026-09-08", "outcome": "ok", "exit_code": 0}
    p.write_text(json.dumps(data))

    r = read_wflow_forecast(p, today=date(2026, 9, 8))
    assert "mislukt" not in r["note"]


def test_lege_reeks_geeft_nooit_available_true_ook_niet_bij_status_ok(tmp_path):
    """Bevinding Important 4, verdediging in de leesfunctie zelf: een status
    "ok" met een lege reeks mag nooit als beschikbaar gelden, ook al zou
    run_nightly() dat nooit meer mogen wegschrijven."""
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({
        "status": "ok", "issue_date": "2026-09-08", "generated_at": "2026-09-08 03:00",
        "series": {"dates": [], "q_kampen": [], "q_westervoort": []},
    }))
    r = read_wflow_forecast(p, today=date(2026, 9, 8))
    assert r["available"] is False
    assert r["q_kampen"] == []


def test_claude_md_en_app_js_zeggen_hetzelfde_over_de_wflow_lijn():
    """CLAUDE.md en app.js moeten het eens zijn of de tab de wflow-lijn toont.

    Ontstaan uit bevinding Important 5 van de eindreview: CLAUDE.md beweerde
    tab-gedrag dat niet bestond. De toets is nu symmetrisch — tekent app.js de
    lijn, dan moet CLAUDE.md dat beschrijven; tekent hij hem niet, dan mag
    CLAUDE.md het niet beweren. Zo blijft de bewaker werken in beide richtingen.
    """
    root = Path(__file__).resolve().parent.parent
    app_js = (root / "dashboard" / "app.js").read_text()
    claude_md = (root / "CLAUDE.md").read_text()

    tekent = "d.wflow" in app_js
    beweert = "Zichtbaar op de Verwachting-tab" in claude_md

    assert tekent == beweert, (
        f"app.js tekent de wflow-lijn: {tekent}, maar CLAUDE.md beweert "
        f"zichtbaarheid: {beweert} — die twee moeten synchroon blijven"
    )


def test_elke_terugval_draagt_een_leesbare_reden(tmp_path):
    """Stil terugvallen is hier het ergste wat het lab kan doen."""
    gevallen = [
        read_wflow_forecast(tmp_path / "weg.json", today=date(2026, 9, 8)),
        read_wflow_forecast(_schrijf(tmp_path, "2026-09-01"), today=date(2026, 9, 8)),
        read_wflow_forecast(_schrijf(tmp_path, "2026-09-08", status="mislukt"),
                            today=date(2026, 9, 8)),
    ]
    for r in gevallen:
        assert r["available"] is False
        assert isinstance(r["note"], str) and len(r["note"]) > 20
