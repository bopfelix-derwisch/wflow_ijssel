"""Warme-state-cyclus en de nachtrun (fase C)."""
import json

import pytest

from wflow_ijssel.operational import nowcast


def test_promote_states_verplaatst_de_outstates(tmp_path):
    out = tmp_path / "outstates.nc"
    inn = tmp_path / "instates.nc"
    out.write_bytes(b"nieuwe-state")
    inn.write_bytes(b"oude-state")

    assert nowcast.promote_states(out, inn) is True
    assert inn.read_bytes() == b"nieuwe-state"


def test_promote_states_laat_de_instates_met_rust_als_de_outstates_ontbreken(tmp_path):
    """Eén mislukte nacht mag de warme keten niet breken."""
    out = tmp_path / "outstates.nc"          # bestaat niet
    inn = tmp_path / "instates.nc"
    inn.write_bytes(b"oude-state")

    assert nowcast.promote_states(out, inn) is False
    assert inn.read_bytes() == b"oude-state"


def test_write_latest_is_atomair(tmp_path):
    """Er mag nooit een half bestand op schijf staan; .tmp blijft niet achter."""
    doel = tmp_path / "latest.json"
    nowcast.write_latest(doel, {"a": 1})
    assert json.loads(doel.read_text()) == {"a": 1}

    nowcast.write_latest(doel, {"a": 2})
    assert json.loads(doel.read_text()) == {"a": 2}
    assert list(tmp_path.glob("*.tmp")) == []


def test_read_csv_output_leest_de_wflow_kolommen(tmp_path):
    csv = tmp_path / "output_ijssel.csv"
    csv.write_text(
        "time,Q_kampen,h_kampen,Q_westervoort\n"
        "2026-09-01T00:00:00,150.5,2.1,120.0\n"
        "2026-09-02T00:00:00,160.5,2.2,130.0\n"
    )
    out = nowcast.read_csv_output(csv)
    assert out["dates"] == ["2026-09-01", "2026-09-02"]
    assert out["q_kampen"] == pytest.approx([150.5, 160.5])
    assert out["q_westervoort"] == pytest.approx([120.0, 130.0])


def test_run_nightly_promoveert_niet_bij_een_mislukte_run(tmp_path, monkeypatch):
    """Het kerncontract: exitcode != 0 -> instates ongemoeid, geen nieuwe latest.json."""
    inn = tmp_path / "instates.nc"
    inn.write_bytes(b"oude-state")
    out = tmp_path / "outstates.nc"
    out.write_bytes(b"zou-niet-gepromoveerd-mogen-worden")
    latest = tmp_path / "latest.json"

    monkeypatch.setattr(nowcast, "IN_STATES", inn)
    monkeypatch.setattr(nowcast, "OUT_STATES", out)
    monkeypatch.setattr(nowcast, "LATEST", latest)
    monkeypatch.setattr(nowcast, "build_forcing_window", lambda *a, **k: {"dates": []})
    monkeypatch.setattr(nowcast, "run_wflow", lambda *a, **k: 1)

    res = nowcast.run_nightly()
    assert res["status"] == "mislukt"
    assert inn.read_bytes() == b"oude-state"
    assert not latest.exists()
