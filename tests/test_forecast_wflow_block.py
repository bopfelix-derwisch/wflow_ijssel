"""Het wflow-blok in /api/forecast: leeftijd, status en terugval (fase C)."""
import json
from datetime import date

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
