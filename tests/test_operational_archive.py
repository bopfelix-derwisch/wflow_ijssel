"""Verificatie-archief: uitgiftes bewaren en later scoren."""
import json

import pytest

from wflow_ijssel.operational.archive import (
    align_for_scoring, append_issue, build_verification, load_issues,
)


def _payload(issue: str, start_dag: int = 10, n: int = 14, q0: float = 100.0):
    dates = [f"2026-09-{start_dag + i:02d}" for i in range(n)]
    return {
        "issue_date": issue,
        "generated_at": issue + " 03:00",
        "series": {"dates": dates,
                   "q_olst": [q0 + i for i in range(n)],
                   "q_kampen": [2 * (q0 + i) for i in range(n)]},
    }


def test_uitgifte_wordt_weggeschreven_en_teruggelezen(tmp_path):
    p = tmp_path / "archive.jsonl"
    append_issue(_payload("2026-09-09"), p)
    uit = load_issues(p)
    assert len(uit) == 1
    assert uit[0]["issue_date"] == "2026-09-09"
    assert len(uit[0]["q_olst"]) == 14


def test_dezelfde_uitgiftedatum_overschrijft_in_plaats_van_te_verdubbelen(tmp_path):
    """De nachtrun kan handmatig herhaald worden; twee regels voor dezelfde dag
    zouden die uitgifte dubbel laten meewegen in de score."""
    p = tmp_path / "archive.jsonl"
    append_issue(_payload("2026-09-09", q0=100.0), p)
    append_issue(_payload("2026-09-09", q0=200.0), p)
    uit = load_issues(p)
    assert len(uit) == 1
    assert uit[0]["q_olst"][0] == 200.0


def test_archief_blijft_gesorteerd_op_uitgiftedatum(tmp_path):
    p = tmp_path / "archive.jsonl"
    append_issue(_payload("2026-09-11"), p)
    append_issue(_payload("2026-09-09"), p)
    append_issue(_payload("2026-09-10"), p)
    assert [r["issue_date"] for r in load_issues(p)] == \
        ["2026-09-09", "2026-09-10", "2026-09-11"]


def test_uitgifte_zonder_datum_of_reeks_wordt_geweigerd(tmp_path):
    p = tmp_path / "archive.jsonl"
    with pytest.raises(ValueError):
        append_issue({"series": {"dates": ["2026-09-10"]}}, p)
    with pytest.raises(ValueError):
        append_issue({"issue_date": "2026-09-09", "series": {"dates": []}}, p)


def test_kapotte_regel_blokkeert_de_rest_niet(tmp_path):
    p = tmp_path / "archive.jsonl"
    append_issue(_payload("2026-09-09"), p)
    with open(p, "a") as f:
        f.write("{dit is geen json\n")
    assert len(load_issues(p)) == 1


def test_leeg_archief_geeft_lege_lijst(tmp_path):
    assert load_issues(tmp_path / "bestaat-niet.jsonl") == []


def test_uitlijnen_koppelt_voorspelling_aan_realisatie():
    issues = [_payload("2026-09-09")]
    issues = [{"issue_date": "2026-09-09",
               "dates": issues[0]["series"]["dates"],
               "q_olst": issues[0]["series"]["q_olst"]}]
    realisatie = {d: 150.0 for d in issues[0]["dates"]}
    preds, obs = align_for_scoring(issues, realisatie)
    assert len(preds) == 1 and len(preds[0]) == 14
    assert obs[0] == [150.0] * 14


def test_uitgifte_met_een_ontbrekende_realisatie_telt_niet_mee():
    """Half meerekenen zou de latere lead-times bevoordelen: juist de verste
    dagen ontbreken het vaakst."""
    p = _payload("2026-09-09")
    issues = [{"issue_date": "2026-09-09", "dates": p["series"]["dates"],
               "q_olst": p["series"]["q_olst"]}]
    realisatie = {d: 150.0 for d in issues[0]["dates"][:-1]}   # laatste dag mist
    preds, obs = align_for_scoring(issues, realisatie)
    assert preds == [] and obs == []


def test_te_korte_reeks_telt_niet_mee():
    issues = [{"issue_date": "2026-09-09",
               "dates": ["2026-09-10", "2026-09-11"], "q_olst": [100.0, 101.0]}]
    preds, obs = align_for_scoring(issues, {"2026-09-10": 1.0, "2026-09-11": 1.0})
    assert preds == []


def test_verificatie_meldt_eerlijk_dat_er_nog_niets_te_scoren_valt():
    uit = build_verification({}, issues=[])
    assert uit["available"] is False
    assert "twee weken" in uit["reason"]
    assert uit["n_scoorbaar"] == 0


def test_verificatie_rekent_de_fout_per_lead_time():
    p = _payload("2026-09-09", q0=100.0)      # voorspelt 100..113
    issues = [{"issue_date": "2026-09-09", "dates": p["series"]["dates"],
               "q_olst": p["series"]["q_olst"]}]
    # realisatie steeds 10 lager → bias +10 op elke horizon
    realisatie = {d: 100.0 + i - 10 for i, d in enumerate(issues[0]["dates"])}
    uit = build_verification(realisatie, issues=issues)
    assert uit["available"] is True
    assert uit["n_scoorbaar"] == 1
    ph = uit["per_horizon"]
    assert ph["bias"][0] == pytest.approx(10.0)
    assert ph["bias"][13] == pytest.approx(10.0)
    # dekking is betekenisloos zonder band en hoort niet gerapporteerd te worden
    assert "coverage" not in ph
