import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient met nep-data in een tmp output-map."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    (output_dir / "kpis.json").write_text(json.dumps({
        "peak_q": 3240.0, "peak_date": "1995-01-29", "days_above_threshold": 8
    }))
    (output_dir / "timeseries_kampen.json").write_text(json.dumps({
        "dates": ["1995-01-01", "1995-01-02"],
        "q": [850.0, 1200.0],
        "h_nap": [1.1, 1.4],
    }))
    (output_dir / "river_day_1995-01-01.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "features": []
    }))

    import dashboard.server as srv
    monkeypatch.setattr(srv, "OUTPUT_DIR", output_dir)
    return TestClient(srv.app)


def test_kpis_endpoint(client):
    resp = client.get("/api/kpis")
    assert resp.status_code == 200
    data = resp.json()
    assert data["peak_q"] == pytest.approx(3240.0)
    assert data["peak_date"] == "1995-01-29"


def test_timeseries_endpoint(client):
    resp = client.get("/api/timeseries/kampen")
    assert resp.status_code == 200
    data = resp.json()
    assert "dates" in data and "q" in data and "h_nap" in data
    assert len(data["q"]) == 2


def test_river_geojson_endpoint(client):
    resp = client.get("/api/river/1995-01-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"


def test_river_geojson_404_on_unknown_date(client):
    resp = client.get("/api/river/1995-02-15")
    assert resp.status_code == 404
