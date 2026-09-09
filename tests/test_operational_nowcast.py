"""Warme-state-cyclus en de nachtrun (fase C)."""
import json
from datetime import date
from pathlib import Path

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
    """Het kerncontract: exitcode != 0 op de nowcast-stap -> instates ongemoeid.

    Bevinding Critical 2: een mislukte nacht schrijft nu wél een latest.json —
    bestond er nog geen, dan met status "mislukt" (in plaats van stil niets
    te schrijven, wat een mislukte nacht onzichtbaar maakte).
    """
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

    res = nowcast.run_nightly(today=date(2026, 9, 9))
    assert res["status"] == "mislukt"
    assert inn.read_bytes() == b"oude-state"
    opgeslagen = json.loads(latest.read_text())
    assert opgeslagen["status"] == "mislukt"
    assert opgeslagen["last_attempt"]["outcome"] == "mislukt"
    assert opgeslagen["last_attempt"]["date"] == "2026-09-09"
    assert opgeslagen["last_attempt"]["fase"] == "nowcast"


def test_run_nightly_promoveert_alleen_na_de_nowcast_stap_niet_na_de_forecast_stap(
        tmp_path, monkeypatch):
    """Bevinding Critical 1: de warme state mag niet besmet raken met dertien
    dagen voorspelde neerslag. De cyclus is twee runs: nowcast [D-1, D]
    promoveert de outstates, forecast [D, D+14] draait vanaf die state maar
    promoveert zelf niets.
    """
    events = []

    def fake_build(path, start, end):
        events.append(("forcing", start, end))
        return {"sources": ["test"], "ratio": 1.0}

    def fake_run(*a, **k):
        events.append(("wflow_run",))
        return 0

    def fake_promote(*a, **k):
        events.append(("promote",))
        return True

    monkeypatch.setattr(nowcast, "build_forcing_window", fake_build)
    monkeypatch.setattr(nowcast, "run_wflow", fake_run)
    monkeypatch.setattr(nowcast, "promote_states", fake_promote)
    monkeypatch.setattr(nowcast, "OUT_DIR", tmp_path)
    monkeypatch.setattr(nowcast, "LATEST", tmp_path / "latest.json")
    # prebuild_dashboard rekent de dure endpoint-antwoorden voor en gaat daarvoor
    # het netwerk op; zonder deze stub duurt deze test ruim twee minuten.
    monkeypatch.setattr(nowcast, "prebuild_dashboard", lambda *a, **k: {})

    (tmp_path / "output_ijssel.csv").write_text(
        "time,Q_kampen,h_kampen,Q_westervoort\n"
        "2026-09-10T00:00:00,200.0,2.0,150.0\n"
    )

    res = nowcast.run_nightly(today=date(2026, 9, 9))

    assert res["status"] == "ok"
    # Exact één promotie, tussen de twee forcing-vensters in: na de
    # nowcast-run, vóór de forecast-run.
    assert events == [
        ("forcing", "2026-09-08", "2026-09-09"),
        ("wflow_run",),
        ("promote",),
        ("forcing", "2026-09-09", "2026-09-23"),
        ("wflow_run",),
    ]


def test_run_nightly_slaat_de_forecast_stap_over_als_de_nowcast_stap_faalt(
        tmp_path, monkeypatch):
    """Bevinding Critical 1 (foutafhandeling): mislukt stap 1, dan heeft
    stap 2 geen zin -- er mag geen tweede forcing-venster gebouwd worden."""
    vensters = []
    monkeypatch.setattr(nowcast, "build_forcing_window",
                        lambda path, start, end: vensters.append((start, end)) or {})
    monkeypatch.setattr(nowcast, "run_wflow", lambda *a, **k: 1)
    monkeypatch.setattr(nowcast, "LATEST", tmp_path / "latest.json")

    res = nowcast.run_nightly(today=date(2026, 9, 9))

    assert res["status"] == "mislukt"
    assert vensters == [("2026-09-08", "2026-09-09")]  # geen tweede venster


def test_mislukte_nachtrun_na_een_goede_nacht_bewaart_de_oude_reeks(tmp_path, monkeypatch):
    """Bevinding Critical 2: een mislukte nacht mag de laatste goede reeks niet
    weggooien -- een verwachting van gisteren met een waarschuwing is
    bruikbaarder dan geen verwachting."""
    latest = tmp_path / "latest.json"
    oude_payload = {
        "status": "ok", "issue_date": "2026-09-08", "generated_at": "2026-09-08 03:00",
        "series": {"dates": ["2026-09-08"], "q_kampen": [200.0], "q_westervoort": [150.0]},
    }
    latest.write_text(json.dumps(oude_payload))

    monkeypatch.setattr(nowcast, "LATEST", latest)
    monkeypatch.setattr(nowcast, "build_forcing_window", lambda *a, **k: {"dates": []})
    monkeypatch.setattr(nowcast, "run_wflow", lambda *a, **k: 1)

    res = nowcast.run_nightly(today=date(2026, 9, 9))

    assert res["status"] == "mislukt"
    opgeslagen = json.loads(latest.read_text())
    assert opgeslagen["status"] == "ok"                     # oude, goede status blijft
    assert opgeslagen["series"]["q_kampen"] == [200.0]       # oude reeks blijft staan
    assert opgeslagen["last_attempt"]["outcome"] == "mislukt"
    assert opgeslagen["last_attempt"]["date"] == "2026-09-09"


def test_promote_states_is_atomair_bij_een_onderbroken_kopie(tmp_path, monkeypatch):
    """Bevinding Important 3: shutil.copy2 rechtstreeks over de live instates
    laat bij onderbreking een half bestand achter. Het patroon moet zijn:
    schrijf naar een tijdelijk bestand, hernoem pas daarna (zoals write_latest).
    """
    out = tmp_path / "outstates.nc"
    inn = tmp_path / "instates.nc"
    out.write_bytes(b"nieuwe-state")
    inn.write_bytes(b"oude-state")

    def kapotte_copy(src, dst):
        Path(dst).write_bytes(b"HALF")
        raise OSError("onderbroken (simulatie)")

    monkeypatch.setattr(nowcast.shutil, "copy2", kapotte_copy)

    with pytest.raises(OSError):
        nowcast.promote_states(out, inn)

    # de live instates zijn nooit aangeraakt: geen half bestand
    assert inn.read_bytes() == b"oude-state"


def test_run_nightly_crasht_niet_als_de_csv_ontbreekt_na_exitcode_0(tmp_path, monkeypatch):
    """Bevinding Important 4: exitcode 0 zonder output_ijssel.csv mag niet als
    ongevangen FileNotFoundError naar boven komen."""
    monkeypatch.setattr(nowcast, "build_forcing_window", lambda *a, **k: {"dates": []})
    monkeypatch.setattr(nowcast, "run_wflow", lambda *a, **k: 0)
    monkeypatch.setattr(nowcast, "promote_states", lambda *a, **k: True)
    monkeypatch.setattr(nowcast, "OUT_DIR", tmp_path)  # output_ijssel.csv bestaat hier niet
    monkeypatch.setattr(nowcast, "LATEST", tmp_path / "latest.json")

    res = nowcast.run_nightly(today=date(2026, 9, 9))  # mag niet raisen
    assert res["status"] == "mislukt"


def test_run_nightly_accepteert_geen_lege_reeks_als_status_ok(tmp_path, monkeypatch):
    """Bevinding Important 4: een CSV met alleen een header mag niet als
    status "ok" weggeschreven worden -- dat zou een "beschikbare" nowcast
    zonder data zijn."""
    monkeypatch.setattr(nowcast, "build_forcing_window", lambda *a, **k: {"dates": []})
    monkeypatch.setattr(nowcast, "run_wflow", lambda *a, **k: 0)
    monkeypatch.setattr(nowcast, "promote_states", lambda *a, **k: True)
    monkeypatch.setattr(nowcast, "OUT_DIR", tmp_path)
    (tmp_path / "output_ijssel.csv").write_text("time,Q_kampen,h_kampen,Q_westervoort\n")
    monkeypatch.setattr(nowcast, "LATEST", tmp_path / "latest.json")

    res = nowcast.run_nightly(today=date(2026, 9, 9))
    assert res["status"] == "mislukt"


def test_run_nightly_registreert_een_forcing_fout_in_plaats_van_te_crashen(tmp_path, monkeypatch):
    """Valt Open-Meteo of RWS uit, dan crashte run_nightly met een ongevangen
    exceptie: geen registratie in latest.json, dus de nachtrun mislukte
    onzichtbaar. Dat ondermijnt precies de garantie uit Critical 2 — alleen
    wflow-exitcodes en CSV-validatie waren afgedekt, forcing-opbouw niet."""
    latest = tmp_path / "latest.json"
    inn = tmp_path / "instates.nc"
    inn.write_bytes(b"oude-state")

    monkeypatch.setattr(nowcast, "LATEST", latest)
    monkeypatch.setattr(nowcast, "IN_STATES", inn)

    def stuk(*a, **k):
        raise RuntimeError("Open-Meteo onbereikbaar")

    monkeypatch.setattr(nowcast, "build_forcing_window", stuk)
    monkeypatch.setattr(nowcast, "run_wflow", lambda *a, **k: 0)

    res = nowcast.run_nightly()
    assert res["status"] == "mislukt"
    assert "forcing" in res.get("fase", "")
    assert inn.read_bytes() == b"oude-state"
    assert latest.exists(), "een mislukte poging hoort zichtbaar te zijn in latest.json"


def test_run_nightly_registreert_ook_een_forcing_fout_in_de_forecast_stap(tmp_path, monkeypatch):
    """De nowcast-stap slaagt, de forecast-forcing valt uit: de warme state is
    dan terecht al bijgewerkt, maar de mislukking moet zichtbaar blijven."""
    latest = tmp_path / "latest.json"
    inn = tmp_path / "instates.nc"
    out = tmp_path / "outstates.nc"
    inn.write_bytes(b"oud"); out.write_bytes(b"nieuw")

    monkeypatch.setattr(nowcast, "LATEST", latest)
    monkeypatch.setattr(nowcast, "IN_STATES", inn)
    monkeypatch.setattr(nowcast, "OUT_STATES", out)
    monkeypatch.setattr(nowcast, "run_wflow", lambda *a, **k: 0)

    pogingen = {"n": 0}

    def soms_stuk(*a, **k):
        pogingen["n"] += 1
        if pogingen["n"] == 1:
            return {"sources": [], "ratio": None}
        raise RuntimeError("RWS onbereikbaar")

    monkeypatch.setattr(nowcast, "build_forcing_window", soms_stuk)

    res = nowcast.run_nightly()
    assert res["status"] == "mislukt"
    assert inn.read_bytes() == b"nieuw", "de nowcast-stap hoort wél gepromoveerd te hebben"
    assert latest.exists()


def _geslaagde_run(tmp_path, monkeypatch, prebuild):
    """Gemeenschappelijke opzet voor een nachtrun die de happy path haalt."""
    monkeypatch.setattr(nowcast, "build_forcing_window",
                        lambda *a, **k: {"sources": [], "ratio": None})
    monkeypatch.setattr(nowcast, "run_wflow", lambda *a, **k: 0)
    monkeypatch.setattr(nowcast, "promote_states", lambda *a, **k: True)
    monkeypatch.setattr(nowcast, "OUT_DIR", tmp_path)
    monkeypatch.setattr(nowcast, "LATEST", tmp_path / "latest.json")
    monkeypatch.setattr(nowcast, "prebuild_dashboard", prebuild)
    (tmp_path / "output_ijssel.csv").write_text(
        "time,Q_kampen,h_kampen,Q_westervoort\n"
        "2026-09-10T00:00:00,200.0,2.0,150.0\n"
    )
    return nowcast.run_nightly(today=date(2026, 9, 9))


def test_run_nightly_berekent_de_dashboard_antwoorden_voor(tmp_path, monkeypatch):
    """Koud duurt /api/forecast 74 s; dat werk hoort in de nachtrun te gebeuren,
    niet bij de eerste bezoeker."""
    geroepen = []
    res = _geslaagde_run(tmp_path, monkeypatch,
                         lambda *a, **k: geroepen.append(True) or {})
    assert res["status"] == "ok"
    assert geroepen, "de nachtrun hoort de dure antwoorden voor te berekenen"
    assert res["prebuilt"] is True


def test_een_mislukte_voorberekening_maakt_de_nachtrun_niet_ongeldig(tmp_path, monkeypatch):
    """De verwachting zelf is goed; alleen de pagina wordt dan trager."""
    def stuk(*a, **k):
        raise RuntimeError("Open-Meteo onbereikbaar")

    res = _geslaagde_run(tmp_path, monkeypatch, stuk)
    assert res["status"] == "ok"
    assert res["prebuilt"] is False
    opgeslagen = json.loads((tmp_path / "latest.json").read_text())
    assert opgeslagen["status"] == "ok"
    assert opgeslagen["prebuilt"] is False
