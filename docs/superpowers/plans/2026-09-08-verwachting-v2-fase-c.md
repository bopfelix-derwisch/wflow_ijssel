# Verwachting v2 — fase C (operationele wflow-nowcast) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elke nacht draait wflow SBM een nowcast + 14-daagse deterministische verwachting, en de Verwachting-tab toont die debietlijn naast het statistische model — met een zichtbare terugvalmodus als de nachtrun uitvalt.

**Architecture:** Een nieuw pakket `wflow_ijssel/operational/` bouwt de forcing (Open-Meteo → modelgrid) en de instroom-randvoorwaarde, draait wflow via subprocess vanuit een warme state, en schrijft `latest.json`. Het dashboard leest dat bestand en rekent zelf niets — één datapad. Het statistische model blijft zichtbaar én dient als fallback.

**Tech Stack:** Python 3.10 (system python `/usr/bin/python3`, packages via `--user`), pytest 9.0.3, xarray + numpy + requests; Julia 1.12.5 met Wflow 1.0.2, aangeroepen via `run_ijssel.jl`; systemd timer.

**Voorwerk:** fase A+B is gemerged (`d4b2572`). `dashboard/rws_client.py` is de enige RWS-ingang; `tools/arm_patches/verify_arm_patches.py` bewaakt de rekenkern; `wflow_sysimage.so` staat in de repo-root (486 MB, gitignored).

## Global Constraints

- Tests draaien met `/usr/bin/python3 -m pytest` vanaf de repo-root; `conftest.py` zet de root op `sys.path`.
- Draai de suite met `--ignore=tests/test_download_inflow.py`. Verwacht beeld vóór dit plan: **2 failed, 49 passed, 4 errors** — allemaal pre-existent (`test_export_output.py`, `test_server.py`), bevestigd op `master`. Een zevende faalpunt is wél van dit werk.
- **Committen mag zonder te vragen**, trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. **Pushen niet** — dat blijft op verzoek.
- Maak vóór taak 1 een werkbranch `feat/verwachting-v2-fase-c` vanaf `master`.
- **Raak `wflow_ijssel/data/output/`, `data/output_2018/`, `data/output_2021*/` nooit aan** — historische proefuitvoer, niet in git, uren rekentijd. De operationele run schrijft uitsluitend naar `wflow_ijssel/data/output_operational/`.
- **Raak `wflow_ijssel/data/input/instates-ijssel.nc` niet aan.** Dat is de instate van de historische proeven. De operationele cyclus gebruikt een eigen state onder `wflow_ijssel/data/operational/`.
- **Alle RWS-verkeer via `dashboard/rws_client.py`.** Voeg nooit een tweede `rw.get_data`-aanroep toe.
- Nederlandse docstrings, commentaar en testnamen.
- Geen `app.js`-wijziging in taak 1 t/m 5; taak 5 raakt alleen de backend. De grafiek zelf is fase F.

### Modelgrid — exacte waarden, letterlijk over te nemen

| | |
|---|---|
| vorm | `(time, y, x)` = `(n_dagen, 240, 300)` |
| x | 5.004166666666666 … 7.495833333333334, stap +0.008333333333333333 (**oplopend**) |
| y | 53.49583333333333 … 51.50416666666667, stap −0.008333333333333333 (**aflopend**) |
| variabelen | `precip` (mm/dag), `temp` (°C), `pet` (mm/dag), `inflow` (m³/s) |
| tijd-dtype | `datetime64[ns]`, dagwaarden op 00:00 |

**`y` loopt aflopend (noord → zuid).** Een oplopende y-as levert een stil gespiegeld stroomgebied op: wflow klaagt niet, de run slaagt, en alle uitkomsten zijn onzin. Dit is de gevaarlijkste val in dit plan.

### Open-Meteo — geverifieerd op 2026-09-08

- Multi-punt werkt met komma-gescheiden `latitude`/`longitude`; **99 punten in één call** gaf HTTP 200 en 86 KB. De respons is dan een **lijst** van objecten (bij één punt een enkel object).
- Dagvelden: `precipitation_sum`, `et0_fao_evapotranspiration`, `temperature_2m_mean`.
- Archief-API `https://archive-api.open-meteo.com/v1/archive` voor historie t/m ongeveer D−6; forecast-API `https://api.open-meteo.com/v1/forecast` met `past_days` voor het recente gat plus de verwachting.
- **Voor fase E (ensemble), alvast vastgelegd:** gebruik `ecmwf_ifs025` (50 leden, volledige 14 dagen). Gebruik **niet** `icon_eu` — die geeft 14 dagen terug maar levert vanaf dag 6 uitsluitend `null`, wat stilzwijgend een band met nul spreiding oplevert.

---

### Task 1: Meteo ophalen en op het modelgrid zetten

**Files:**
- Create: `wflow_ijssel/operational/__init__.py` (leeg)
- Create: `wflow_ijssel/operational/meteo.py`
- Test: `tests/test_operational_meteo.py`

**Interfaces:**
- Consumes: niets.
- Produces:
  - `grid_points(step=0.25) -> tuple[list[float], list[float]]` — (lats, lons) van het bevragingsraster, beide even lang, rijgewijs.
  - `fetch_daily(lats, lons, start, end) -> dict` — `{"dates": [iso...], "precip": ndarray(n_pts, n_dagen), "pet": ..., "temp": ...}`.
  - `to_model_grid(values, src_lats, src_lons, dst_y, dst_x) -> ndarray(n_dagen, len(dst_y), len(dst_x))` — bilineaire interpolatie van punten naar het modelgrid.
  - Constanten `MODEL_X`, `MODEL_Y` (numpy-arrays met exact de waarden uit de tabel hierboven).

- [ ] **Step 1: Write the failing test**

Maak `tests/test_operational_meteo.py`:

```python
"""Meteo-ophalen en regridden voor de operationele nowcast (fase C)."""
import numpy as np
import pytest

from wflow_ijssel.operational.meteo import (
    MODEL_X, MODEL_Y, grid_points, to_model_grid,
)


def test_modelgrid_heeft_de_exacte_vorm_en_richting():
    assert len(MODEL_X) == 300
    assert len(MODEL_Y) == 240
    assert MODEL_X[0] == pytest.approx(5.004166666666666)
    assert MODEL_X[-1] == pytest.approx(7.495833333333334)
    # y loopt AFLOPEND (noord -> zuid); een oplopende as spiegelt het stroomgebied
    assert MODEL_Y[0] == pytest.approx(53.49583333333333)
    assert MODEL_Y[-1] == pytest.approx(51.50416666666667)
    assert np.all(np.diff(MODEL_Y) < 0)
    assert np.all(np.diff(MODEL_X) > 0)


def test_grid_points_dekt_het_modelgrid():
    lats, lons = grid_points(step=0.25)
    assert len(lats) == len(lons)
    assert len(lats) > 50
    # het bevragingsraster moet het modelgrid omsluiten, anders extrapoleren we
    assert min(lats) <= MODEL_Y.min()
    assert max(lats) >= MODEL_Y.max()
    assert min(lons) <= MODEL_X.min()
    assert max(lons) >= MODEL_X.max()


def test_to_model_grid_reproduceert_een_constant_veld():
    lats = [la for la in (51.0, 52.0, 53.0, 54.0) for _ in range(4)]
    lons = [lo for _ in range(4) for lo in (5.0, 6.0, 7.0, 8.0)]
    values = np.full((16, 2), 3.5)          # 16 punten, 2 dagen
    out = to_model_grid(values, lats, lons, MODEL_Y, MODEL_X)
    assert out.shape == (2, 240, 300)
    assert np.allclose(out, 3.5)


def test_to_model_grid_interpoleert_een_lineaire_helling():
    """Veld dat lineair met de lengtegraad oploopt moet lineair blijven."""
    lats = [la for la in (51.0, 52.0, 53.0, 54.0) for _ in range(4)]
    lons = [lo for _ in range(4) for lo in (5.0, 6.0, 7.0, 8.0)]
    values = np.array([[lo] for lo in lons], dtype=float)   # 16 punten, 1 dag
    out = to_model_grid(values, lats, lons, MODEL_Y, MODEL_X)
    assert out.shape == (1, 240, 300)
    # elke rij moet de x-as volgen
    np.testing.assert_allclose(out[0, 0, :], MODEL_X, atol=1e-6)
    np.testing.assert_allclose(out[0, -1, :], MODEL_X, atol=1e-6)


def test_to_model_grid_verwerpt_verkeerde_vorm():
    lats = [51.0, 52.0]
    lons = [5.0, 6.0]
    with pytest.raises(ValueError):
        to_model_grid(np.zeros((3, 2)), lats, lons, MODEL_Y, MODEL_X)


def test_fetch_daily_leest_een_lijstrespons(monkeypatch):
    """Open-Meteo geeft bij meerdere punten een LIJST terug, bij één punt een object."""
    from wflow_ijssel.operational import meteo

    nep = [
        {"latitude": 52.0, "longitude": 6.0, "daily": {
            "time": ["2026-01-01", "2026-01-02"],
            "precipitation_sum": [1.0, 2.0],
            "et0_fao_evapotranspiration": [0.5, 0.6],
            "temperature_2m_mean": [4.0, 5.0]}},
        {"latitude": 52.0, "longitude": 6.25, "daily": {
            "time": ["2026-01-01", "2026-01-02"],
            "precipitation_sum": [3.0, 4.0],
            "et0_fao_evapotranspiration": [0.7, 0.8],
            "temperature_2m_mean": [6.0, 7.0]}},
    ]
    monkeypatch.setattr(meteo, "_get_json", lambda url, params: nep)

    out = meteo.fetch_daily([52.0, 52.0], [6.0, 6.25], "2026-01-01", "2026-01-02")
    assert out["dates"] == ["2026-01-01", "2026-01-02"]
    assert out["precip"].shape == (2, 2)
    np.testing.assert_allclose(out["precip"][:, 0], [1.0, 3.0])
    np.testing.assert_allclose(out["temp"][:, 1], [5.0, 7.0])


def test_fetch_daily_vult_ontbrekende_waarden_met_nul(monkeypatch):
    """Open-Meteo levert soms null; neerslag/verdamping mogen geen NaN de forcing in."""
    from wflow_ijssel.operational import meteo

    nep = {"latitude": 52.0, "longitude": 6.0, "daily": {
        "time": ["2026-01-01"], "precipitation_sum": [None],
        "et0_fao_evapotranspiration": [None], "temperature_2m_mean": [None]}}
    monkeypatch.setattr(meteo, "_get_json", lambda url, params: nep)

    out = meteo.fetch_daily([52.0], [6.0], "2026-01-01", "2026-01-01")
    assert out["precip"][0, 0] == 0.0
    assert out["pet"][0, 0] == 0.0
    assert out["temp"][0, 0] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_operational_meteo.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'wflow_ijssel.operational'`

- [ ] **Step 3: Write minimal implementation**

Maak `wflow_ijssel/operational/__init__.py` (leeg bestand) en `wflow_ijssel/operational/meteo.py`:

```python
"""Meteo-forcing voor de operationele nowcast: Open-Meteo → modelgrid.

De historische forcing komt uit ERA5-Land via CDS (`download_forcing.py`), met
~5 dagen latentie en zonder verwachting — operationeel onbruikbaar. Hier halen
we Open-Meteo op een grover puntenraster op en interpoleren naar het modelgrid.

Geverifieerd op 2026-09-08: 99 punten in één call geeft HTTP 200 (~86 KB). Bij
meerdere punten is de respons een LIJST van objecten, bij één punt een enkel
object.
"""
from __future__ import annotations

import logging

import numpy as np
import requests

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

DAILY_VARS = "precipitation_sum,et0_fao_evapotranspiration,temperature_2m_mean"

# Modelgrid van staticmaps-ijssel.nc / forcing-ijssel.nc — exact overnemen.
# LET OP: y loopt AFLOPEND (noord → zuid). Een oplopende as spiegelt het
# stroomgebied zonder dat wflow klaagt.
MODEL_X = np.linspace(5.004166666666666, 7.495833333333334, 300)
MODEL_Y = np.linspace(53.49583333333333, 51.50416666666667, 240)


def grid_points(step: float = 0.25) -> tuple[list[float], list[float]]:
    """Bevragingsraster dat het modelgrid ruim omsluit (geen extrapolatie)."""
    lats = np.arange(np.floor(MODEL_Y.min() / step) * step,
                     np.ceil(MODEL_Y.max() / step) * step + step / 2, step)
    lons = np.arange(np.floor(MODEL_X.min() / step) * step,
                     np.ceil(MODEL_X.max() / step) * step + step / 2, step)
    out_lat, out_lon = [], []
    for la in lats:
        for lo in lons:
            out_lat.append(round(float(la), 4))
            out_lon.append(round(float(lo), 4))
    return out_lat, out_lon


def _get_json(url: str, params: dict):
    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def _as_list(payload) -> list:
    return payload if isinstance(payload, list) else [payload]


def fetch_daily(lats, lons, start: str, end: str, archive: bool = False) -> dict:
    """Daggegevens per punt. Retourneert arrays met vorm (n_punten, n_dagen)."""
    url = ARCHIVE_URL if archive else FORECAST_URL
    params = {
        "latitude": ",".join(f"{v:.4f}" for v in lats),
        "longitude": ",".join(f"{v:.4f}" for v in lons),
        "daily": DAILY_VARS,
        "timezone": "Europe/Amsterdam",
        "start_date": start,
        "end_date": end,
    }
    payload = _as_list(_get_json(url, params))

    dates = payload[0]["daily"]["time"]
    n_pts, n_days = len(payload), len(dates)

    def column(key):
        arr = np.zeros((n_pts, n_days), dtype=float)
        for i, loc in enumerate(payload):
            vals = loc["daily"][key]
            arr[i, :] = [0.0 if v is None else float(v) for v in vals]
        return arr

    return {
        "dates": dates,
        "precip": column("precipitation_sum"),
        "pet": column("et0_fao_evapotranspiration"),
        "temp": column("temperature_2m_mean"),
    }


def to_model_grid(values, src_lats, src_lons, dst_y, dst_x) -> np.ndarray:
    """Bilineaire interpolatie van een puntenwolk naar het modelgrid.

    `values` heeft vorm (n_punten, n_dagen); de punten liggen op een regelmatig
    lat/lon-raster, rijgewijs geordend zoals `grid_points` ze oplevert.
    Resultaat: (n_dagen, len(dst_y), len(dst_x)).
    """
    values = np.asarray(values, dtype=float)
    if values.ndim != 2 or values.shape[0] != len(src_lats):
        raise ValueError(
            f"values moet vorm (n_punten, n_dagen) hebben met n_punten={len(src_lats)}, "
            f"kreeg {values.shape}")

    ulat = np.unique(np.asarray(src_lats, dtype=float))
    ulon = np.unique(np.asarray(src_lons, dtype=float))
    if len(ulat) * len(ulon) != len(src_lats):
        raise ValueError("bronpunten vormen geen regelmatig lat/lon-raster")

    n_days = values.shape[1]
    out = np.empty((n_days, len(dst_y), len(dst_x)), dtype=float)

    # index van elk bronpunt in het (lat, lon)-raster
    lat_idx = np.searchsorted(ulat, np.asarray(src_lats, dtype=float))
    lon_idx = np.searchsorted(ulon, np.asarray(src_lons, dtype=float))

    for d in range(n_days):
        field = np.empty((len(ulat), len(ulon)), dtype=float)
        field[lat_idx, lon_idx] = values[:, d]
        # interpoleer eerst over lengtegraad, dan over breedtegraad
        tmp = np.empty((len(ulat), len(dst_x)), dtype=float)
        for i in range(len(ulat)):
            tmp[i, :] = np.interp(dst_x, ulon, field[i, :])
        for j in range(len(dst_x)):
            out[d, :, j] = np.interp(dst_y, ulat, tmp[:, j])
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/usr/bin/python3 -m pytest tests/test_operational_meteo.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Rooktest tegen de echte API**

Run:
```bash
/usr/bin/python3 -c "
from wflow_ijssel.operational import meteo
lats, lons = meteo.grid_points()
print('punten:', len(lats))
d = meteo.fetch_daily(lats, lons, '2026-09-06', '2026-09-12')
print('dagen:', len(d['dates']), d['dates'][0], '..', d['dates'][-1])
print('precip vorm:', d['precip'].shape, 'bereik', d['precip'].min(), d['precip'].max())
g = meteo.to_model_grid(d['precip'], lats, lons, meteo.MODEL_Y, meteo.MODEL_X)
print('grid vorm:', g.shape, 'bereik', round(float(g.min()),2), round(float(g.max()),2))
"
```
Expected: ~99 punten, 7 dagen, gridvorm `(7, 240, 300)`, en een neerslagbereik dat binnen het puntenbereik ligt (interpolatie mag niet buiten de bron-extremen uitkomen).

- [ ] **Step 6: Commit**

```bash
git add wflow_ijssel/operational/__init__.py wflow_ijssel/operational/meteo.py tests/test_operational_meteo.py
git commit -m "feat(operational): Open-Meteo ophalen en regridden naar het modelgrid

99 punten op 0,25 graden in een call, bilineair naar 300x240. y loopt
aflopend, net als de bestaande forcing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Instroom-randvoorwaarde bij Westervoort

**Files:**
- Create: `wflow_ijssel/operational/boundary.py`
- Test: `tests/test_operational_boundary.py`

**Interfaces:**
- Consumes: `dashboard.rws_client.daily_series`, `dashboard.forecast._recession` en `_seasonal_mean`.
- Produces:
  - `blend(measured: dict, rws: dict, recession: dict, dates: list[str], blend_days: int = 2) -> list[float]` — pure functie; per datum de bron kiezen en over `blend_days` lineair mengen tussen RWS-verwachting en recessie.
  - `lobith_ratio(q_lobith: dict, q_westervoort: dict) -> float` — mediane verhouding Westervoort/Lobith over de overlappende dagen; `None` bij te weinig overlap.
  - `build_boundary(dates: list[str]) -> dict` — `{"values": [...], "sources": [...], "ratio": float|None}`.

wflow krijgt de instroom als randvoorwaarde bij Westervoort (6.154 O, 51.987 N). RWS-verwachtingen reiken maar ~3 dagen, dus dag 4 t/m 14 komt van het recessiemodel. **Olst niet gebruiken** — dat ligt binnen het modeldomein en zou het gebied tussen Westervoort en Olst dubbeltellen.

- [ ] **Step 1: Write the failing test**

Maak `tests/test_operational_boundary.py`:

```python
"""Instroom-randvoorwaarde bij Westervoort (fase C)."""
import pytest

from wflow_ijssel.operational.boundary import blend, lobith_ratio


DATES = [f"2026-09-{d:02d}" for d in range(1, 11)]


def test_blend_kiest_meting_boven_alles():
    measured = {"2026-09-01": 100.0, "2026-09-02": 110.0}
    rws = {"2026-09-01": 999.0, "2026-09-02": 999.0}
    recession = {d: 50.0 for d in DATES}
    out = blend(measured, rws, recession, DATES[:2])
    assert out == [100.0, 110.0]


def test_blend_gebruikt_rws_waar_geen_meting_is():
    measured = {"2026-09-01": 100.0}
    rws = {"2026-09-02": 120.0, "2026-09-03": 130.0}
    recession = {d: 50.0 for d in DATES}
    out = blend(measured, rws, recession, DATES[:3], blend_days=0)
    assert out == [100.0, 120.0, 130.0]


def test_blend_valt_terug_op_recessie_voorbij_de_rws_horizon():
    measured = {}
    rws = {"2026-09-01": 120.0}
    recession = {d: 60.0 for d in DATES}
    out = blend(measured, rws, recession, DATES[:4], blend_days=0)
    assert out == [120.0, 60.0, 60.0, 60.0]


def test_blend_mengt_de_overgang_zodat_er_geen_sprong_ontstaat():
    """Zonder menging springt de randvoorwaarde van 120 naar 60 in één dag."""
    measured = {}
    rws = {"2026-09-01": 120.0}
    recession = {d: 60.0 for d in DATES}
    out = blend(measured, rws, recession, DATES[:4], blend_days=2)
    assert out[0] == pytest.approx(120.0)
    # twee tussenstappen, monotoon dalend, eindigend op de recessiewaarde
    assert 60.0 < out[1] < 120.0
    assert 60.0 < out[2] < out[1]
    assert out[3] == pytest.approx(60.0)


def test_blend_verwerpt_een_lege_datumreeks():
    with pytest.raises(ValueError):
        blend({}, {}, {}, [])


def test_lobith_ratio_is_de_mediane_verhouding():
    lob = {"2026-09-01": 900.0, "2026-09-02": 1000.0, "2026-09-03": 800.0}
    wes = {"2026-09-01": 90.0, "2026-09-02": 100.0, "2026-09-03": 80.0}
    # min_overlap expliciet: de standaard is 20 dagen, deze reeks heeft er 3
    assert lobith_ratio(lob, wes, min_overlap=3) == pytest.approx(0.1)


def test_lobith_ratio_eist_standaard_twintig_dagen_overlap():
    """Drie toevallig kloppende dagen mogen geen schaalfactor rechtvaardigen."""
    lob = {"2026-09-01": 900.0, "2026-09-02": 1000.0, "2026-09-03": 800.0}
    wes = {"2026-09-01": 90.0, "2026-09-02": 100.0, "2026-09-03": 80.0}
    assert lobith_ratio(lob, wes) is None


def test_lobith_ratio_negeert_dagen_zonder_paar():
    lob = {"2026-09-01": 900.0, "2026-09-02": 1000.0}
    wes = {"2026-09-01": 90.0, "2026-09-09": 500.0}
    assert lobith_ratio(lob, wes, min_overlap=1) == pytest.approx(0.1)


def test_lobith_ratio_geeft_none_bij_te_weinig_overlap():
    assert lobith_ratio({"2026-09-01": 900.0}, {"2026-09-02": 90.0}) is None


def test_lobith_ratio_negeert_nul_en_negatieve_afvoer():
    lob = {"a": 0.0, "b": 1000.0, "c": -5.0}
    wes = {"a": 50.0, "b": 100.0, "c": 10.0}
    assert lobith_ratio(lob, wes, min_overlap=1) == pytest.approx(0.1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_operational_boundary.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'wflow_ijssel.operational.boundary'`

- [ ] **Step 3: Write minimal implementation**

Maak `wflow_ijssel/operational/boundary.py`:

```python
"""Instroom-randvoorwaarde bij Westervoort voor de operationele wflow-run.

wflow krijgt de Rijn-instroom als randvoorwaarde bij Westervoort (6.154 O,
51.987 N). Per dag:

  D-n … D    RWS-meting Westervoort
  D+1 … D+3  RWS-verwachting Lobith, geschaald naar Westervoort
  D+4 … D+14 recessiemodel

RWS-verwachtingen reiken maar ~3 dagen (geverifieerd 2026-09-08), vandaar de
recessie voor de rest. De overgang wordt over enkele dagen gemengd zodat er
geen sprong in de randvoorwaarde ontstaat.

Olst wordt hier bewust NIET gebruikt: dat ligt bínnen het modeldomein,
benedenstrooms van de instroomrand, en zou het gebied tussen Westervoort en
Olst dubbeltellen. Olst is het validatiepunt, niet de randvoorwaarde.
"""
from __future__ import annotations

import logging
import statistics

logger = logging.getLogger(__name__)

LOBITH = "lobith.bovenrijn.tolkamer"
WESTERVOORT = "westervoort"
MIN_OVERLAP = 20


def lobith_ratio(q_lobith: dict, q_westervoort: dict,
                 min_overlap: int = MIN_OVERLAP) -> "float | None":
    """Mediane verhouding Westervoort/Lobith over de overlappende dagen.

    De IJssel is ruwweg een negende van de Rijnafvoer, maar die verhouding
    varieert met het afvoerregime — we meten hem dus, en nemen hem niet aan.
    """
    ratios = []
    for d, lob in q_lobith.items():
        wes = q_westervoort.get(d)
        if wes is None or lob is None or lob <= 0 or wes <= 0:
            continue
        ratios.append(wes / lob)
    if len(ratios) < min_overlap:
        return None
    return float(statistics.median(ratios))


def blend(measured: dict, rws: dict, recession: dict,
          dates: list, blend_days: int = 2) -> list:
    """Stel de randvoorwaarde samen; meting > RWS-verwachting > recessie.

    Over `blend_days` na de laatste RWS-dag wordt lineair naar de recessie
    gemengd, zodat de randvoorwaarde niet springt.
    """
    if not dates:
        raise ValueError("dates mag niet leeg zijn")

    last_rws = max((d for d in dates if d in rws), default=None)
    out = []
    for d in dates:
        if d in measured:
            out.append(float(measured[d]))
            continue
        if d in rws:
            out.append(float(rws[d]))
            continue

        rec = float(recession[d])
        if last_rws is not None and blend_days > 0 and d > last_rws:
            steps_after = sum(1 for x in dates if last_rws < x <= d)
            if steps_after <= blend_days:
                w = steps_after / (blend_days + 1)
                out.append(float(rws[last_rws]) * (1 - w) + rec * w)
                continue
        out.append(rec)
    return out


def build_boundary(dates: list) -> dict:
    """Haal de bronnen op en stel de randvoorwaarde samen voor `dates`."""
    from datetime import date, timedelta

    import numpy as np

    from dashboard import rws_client
    from dashboard.forecast import _recession, _seasonal_mean

    today = date.today()
    hist_start = today - timedelta(days=400)

    def as_map(series):
        if series is None:
            return {}
        return {ts.strftime("%Y-%m-%d"): float(v) for ts, v in series.items()}

    wes = as_map(rws_client.daily_series(WESTERVOORT, "Q", "m3/s", hist_start, today))
    lob = as_map(rws_client.daily_series(LOBITH, "Q", "m3/s", hist_start, today))
    ratio = lobith_ratio(lob, wes)

    lob_fc = as_map(rws_client.daily_series(
        LOBITH, "Q", "m3/s", today, today + timedelta(days=14), proces_type="verwachting"))
    rws_fc = {}
    if ratio is not None:
        rws_fc = {d: v * ratio for d, v in lob_fc.items() if d not in wes}

    q0 = wes[max(wes)] if wes else float(_seasonal_mean(today.month))
    rec_vals = _recession(q0, len(dates), today.month)
    recession = {d: float(v) for d, v in zip(dates, np.asarray(rec_vals, dtype=float))}

    values = blend(wes, rws_fc, recession, dates)
    sources = [
        "meting" if d in wes else ("rws" if d in rws_fc else "recessie")
        for d in dates
    ]
    logger.info("randvoorwaarde: ratio=%s, bronnen=%s",
                round(ratio, 4) if ratio else None,
                {s: sources.count(s) for s in set(sources)})
    return {"values": values, "sources": sources, "ratio": ratio}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/usr/bin/python3 -m pytest tests/test_operational_boundary.py -v`
Expected: PASS, 9 passed

- [ ] **Step 5: Rooktest tegen de echte RWS-data**

Run:
```bash
/usr/bin/python3 -c "
from datetime import date, timedelta
from wflow_ijssel.operational.boundary import build_boundary
t = date.today()
dates = [(t + timedelta(days=i)).isoformat() for i in range(-2, 15)]
b = build_boundary(dates)
print('ratio Westervoort/Lobith:', b['ratio'])
for d, v, s in zip(dates, b['values'], b['sources']):
    print(f'  {d}  {v:8.1f}  {s}')
" 2>&1 | grep -v Downloading
```
Expected: een ratio rond 0,1 (de IJssel is ruwweg een negende van de Rijn), meetwaarden voor de dagen in het verleden, en een vloeiend verloop zonder sprong bij de overgang naar de recessie. Wijkt de ratio sterk af van 0,1, noteer dat dan in je verslag — het kan op een verkeerd station of een eenhedenprobleem wijzen.

- [ ] **Step 6: Commit**

```bash
git add wflow_ijssel/operational/boundary.py tests/test_operational_boundary.py
git commit -m "feat(operational): instroom-randvoorwaarde Westervoort

Meting > RWS-Lobith-verwachting (geschaald, ~3 dagen) > recessie, met
gemengde overgang. Olst bewust niet gebruikt: ligt binnen het domein.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Forcing-NetCDF schrijven

**Files:**
- Create: `wflow_ijssel/operational/forcing.py`
- Test: `tests/test_operational_forcing.py`

**Interfaces:**
- Consumes: `meteo.MODEL_X`, `meteo.MODEL_Y`.
- Produces:
  - `westervoort_cell(dst_y, dst_x) -> tuple[int, int]` — (rij, kolom) van de instroomcel.
  - `write_forcing(path, dates, precip, pet, temp, inflow_series) -> Path` — schrijft een NetCDF met exact het schema van `forcing-ijssel.nc`.
  - `build_forcing(path, start, end, inflow_dates=None) -> dict` — haalt meteo + randvoorwaarde op en schrijft het bestand; retourneert metadata.

**Het rekenvenster wordt volledig bepaald door de tijdas van dit bestand** — wflow negeert `starttime`/`endtime` uit de TOML (ARM-patches, zie `tools/arm_patches/README.md`). Het slicen gebeurt dus hier.

- [ ] **Step 1: Write the failing test**

Maak `tests/test_operational_forcing.py`:

```python
"""Forcing-NetCDF voor de operationele nowcast (fase C)."""
import numpy as np
import pytest
import xarray as xr

from wflow_ijssel.operational.forcing import westervoort_cell, write_forcing
from wflow_ijssel.operational.meteo import MODEL_X, MODEL_Y


def _velden(n_dagen):
    vorm = (n_dagen, len(MODEL_Y), len(MODEL_X))
    return (np.full(vorm, 2.0), np.full(vorm, 0.5), np.full(vorm, 8.0))


def test_westervoort_cel_ligt_in_het_grid():
    rij, kol = westervoort_cell(MODEL_Y, MODEL_X)
    assert 0 <= rij < len(MODEL_Y)
    assert 0 <= kol < len(MODEL_X)
    # 6.154 O, 51.987 N — zuidoostelijke hoek van het domein
    assert MODEL_Y[rij] == pytest.approx(51.987, abs=0.01)
    assert MODEL_X[kol] == pytest.approx(6.154, abs=0.01)


def test_write_forcing_schrijft_het_verwachte_schema(tmp_path):
    dates = ["2026-09-01", "2026-09-02", "2026-09-03"]
    precip, pet, temp = _velden(3)
    pad = write_forcing(tmp_path / "f.nc", dates, precip, pet, temp, [100.0, 110.0, 120.0])

    with xr.open_dataset(pad) as ds:
        assert set(ds.data_vars) == {"precip", "temp", "pet", "inflow"}
        assert ds["precip"].dims == ("time", "y", "x")
        assert ds.sizes == {"time": 3, "y": 240, "x": 300}
        # y moet AFLOPEND zijn — anders spiegelt het stroomgebied stilzwijgend
        assert ds.y.values[0] > ds.y.values[-1]
        assert ds.x.values[0] < ds.x.values[-1]
        np.testing.assert_allclose(ds.x.values, MODEL_X)
        np.testing.assert_allclose(ds.y.values, MODEL_Y)
        assert str(ds.time.dtype).startswith("datetime64")


def test_write_forcing_zet_inflow_alleen_in_de_westervoort_cel(tmp_path):
    dates = ["2026-09-01", "2026-09-02"]
    precip, pet, temp = _velden(2)
    pad = write_forcing(tmp_path / "f.nc", dates, precip, pet, temp, [300.0, 400.0])

    rij, kol = westervoort_cell(MODEL_Y, MODEL_X)
    with xr.open_dataset(pad) as ds:
        inflow = ds["inflow"].values
        assert inflow[0, rij, kol] == pytest.approx(300.0)
        assert inflow[1, rij, kol] == pytest.approx(400.0)
        # alle overige cellen nul
        inflow[:, rij, kol] = 0.0
        assert np.count_nonzero(inflow) == 0


def test_write_forcing_verwerpt_een_verkeerde_inflow_lengte(tmp_path):
    precip, pet, temp = _velden(3)
    with pytest.raises(ValueError):
        write_forcing(tmp_path / "f.nc", ["2026-09-01", "2026-09-02", "2026-09-03"],
                      precip, pet, temp, [100.0])


def test_write_forcing_verwerpt_een_verkeerde_veldvorm(tmp_path):
    precip, pet, temp = _velden(3)
    with pytest.raises(ValueError):
        write_forcing(tmp_path / "f.nc", ["2026-09-01"], precip, pet, temp, [100.0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_operational_forcing.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'wflow_ijssel.operational.forcing'`

- [ ] **Step 3: Write minimal implementation**

Maak `wflow_ijssel/operational/forcing.py`:

```python
"""Schrijf de forcing-NetCDF voor een operationele wflow-run.

Schema exact als `wflow_ijssel/data/input/forcing-ijssel.nc`: dims
(time, y, x) = (n, 240, 300), variabelen precip/temp/pet/inflow, y AFLOPEND.

BELANGRIJK: wflow negeert `starttime`/`endtime` uit de TOML (gevolg van de
ARM-JIT-patches, zie tools/arm_patches/README.md). Het rekenvenster komt
volledig uit de tijdas van dít bestand — hier wordt het venster dus bepaald.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from wflow_ijssel.operational.meteo import MODEL_X, MODEL_Y

logger = logging.getLogger(__name__)

# Instroom-randvoorwaarde: Westervoort, conform docs/WL-PROV-2_schematisatie.md
WESTERVOORT_LON = 6.154
WESTERVOORT_LAT = 51.987


def westervoort_cell(dst_y, dst_x) -> tuple[int, int]:
    """(rij, kolom) van de cel die het dichtst bij Westervoort ligt."""
    rij = int(np.argmin(np.abs(np.asarray(dst_y) - WESTERVOORT_LAT)))
    kol = int(np.argmin(np.abs(np.asarray(dst_x) - WESTERVOORT_LON)))
    return rij, kol


def write_forcing(path, dates, precip, pet, temp, inflow_series) -> Path:
    """Schrijf de forcing weg. Retourneert het pad."""
    path = Path(path)
    n = len(dates)
    vorm = (n, len(MODEL_Y), len(MODEL_X))

    for naam, veld in (("precip", precip), ("pet", pet), ("temp", temp)):
        if np.shape(veld) != vorm:
            raise ValueError(f"{naam} moet vorm {vorm} hebben, kreeg {np.shape(veld)}")
    if len(inflow_series) != n:
        raise ValueError(f"inflow_series moet {n} waarden hebben, kreeg {len(inflow_series)}")

    inflow = np.zeros(vorm, dtype="float32")
    rij, kol = westervoort_cell(MODEL_Y, MODEL_X)
    inflow[:, rij, kol] = np.asarray(inflow_series, dtype="float32")

    ds = xr.Dataset(
        {
            "precip": (("time", "y", "x"), np.asarray(precip, dtype="float32")),
            "temp":   (("time", "y", "x"), np.asarray(temp, dtype="float32")),
            "pet":    (("time", "y", "x"), np.asarray(pet, dtype="float32")),
            "inflow": (("time", "y", "x"), inflow),
        },
        coords={"time": pd.to_datetime(list(dates)), "y": MODEL_Y, "x": MODEL_X},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path)
    ds.close()
    logger.info("forcing geschreven: %s (%d dagen, %s .. %s)", path, n, dates[0], dates[-1])
    return path


def build_forcing(path, start: str, end: str) -> dict:
    """Haal meteo + randvoorwaarde op en schrijf de forcing voor [start, end]."""
    from wflow_ijssel.operational import boundary, meteo

    lats, lons = meteo.grid_points()
    data = meteo.fetch_daily(lats, lons, start, end)
    dates = data["dates"]

    precip = meteo.to_model_grid(data["precip"], lats, lons, MODEL_Y, MODEL_X)
    pet = meteo.to_model_grid(data["pet"], lats, lons, MODEL_Y, MODEL_X)
    temp = meteo.to_model_grid(data["temp"], lats, lons, MODEL_Y, MODEL_X)

    bnd = boundary.build_boundary(dates)
    write_forcing(path, dates, precip, pet, temp, bnd["values"])
    return {"path": str(path), "dates": dates, "sources": bnd["sources"],
            "ratio": bnd["ratio"]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/usr/bin/python3 -m pytest tests/test_operational_forcing.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Vergelijk het schema met de bestaande forcing**

Run:
```bash
/usr/bin/python3 -c "
import xarray as xr, numpy as np
oud = xr.open_dataset('wflow_ijssel/data/input/forcing-ijssel.nc')
from wflow_ijssel.operational.forcing import write_forcing
from wflow_ijssel.operational.meteo import MODEL_X, MODEL_Y
vorm=(2,240,300); z=np.zeros(vorm)
p=write_forcing('/tmp/schema_check.nc', ['2026-01-01','2026-01-02'], z, z, z, [1.0,2.0])
nieuw = xr.open_dataset(p)
print('vars gelijk:', set(oud.data_vars)==set(nieuw.data_vars), sorted(oud.data_vars), sorted(nieuw.data_vars))
print('dims gelijk:', oud.precip.dims==nieuw.precip.dims)
print('x gelijk:', np.allclose(oud.x.values, nieuw.x.values))
print('y gelijk:', np.allclose(oud.y.values, nieuw.y.values))
print('y-richting gelijk:', (oud.y.values[0]>oud.y.values[-1])==(nieuw.y.values[0]>nieuw.y.values[-1]))
"
```
Expected: vier keer `True` plus identieke variabelenlijsten. Wijkt iets af, stop en meld het — een afwijkend schema betekent dat wflow het bestand niet of verkeerd leest.

- [ ] **Step 6: Commit**

```bash
git add wflow_ijssel/operational/forcing.py tests/test_operational_forcing.py
git commit -m "feat(operational): forcing-NetCDF met het schema van forcing-ijssel.nc

y aflopend, inflow alleen in de Westervoort-cel. De tijdas van dit
bestand bepaalt het rekenvenster (wflow negeert de TOML).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Warme-state-cyclus en de nachtrun

**Files:**
- Create: `wflow_ijssel/operational/nowcast.py`
- Create: `wflow_ijssel/ijssel_config_operational.toml`
- Test: `tests/test_operational_nowcast.py`

**Interfaces:**
- Consumes: `forcing.build_forcing`.
- Produces:
  - `run_wflow(config_path, timeout=1800) -> int` — subprocess, retourneert de exitcode.
  - `promote_states(out_states, in_states) -> bool` — verplaatst de outstates naar de instates; doet niets en retourneert `False` als de bron ontbreekt.
  - `read_csv_output(path) -> dict` — leest `output_ijssel.csv` naar `{"dates": [...], "q_kampen": [...], "q_westervoort": [...]}`.
  - `write_latest(path, payload) -> Path` — atomair schrijven (`.tmp` + `os.replace`).
  - `run_nightly() -> dict` — de volledige cyclus.

**Contract dat de tests bewaken:** bij een niet-nul exitcode blijven de instates ongemoeid, en `latest.json` wordt nooit half gelezen.

- [ ] **Step 1: Write the failing test**

Maak `tests/test_operational_nowcast.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_operational_nowcast.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'wflow_ijssel.operational.nowcast'`

- [ ] **Step 3: Maak de operationele wflow-config**

Maak `wflow_ijssel/ijssel_config_operational.toml` door `wflow_ijssel/ijssel_config.toml` te kopiëren en precies drie dingen te wijzigen:

```toml
dir_input  = "data/operational"
dir_output = "data/output_operational"
```

en in `[input]`:

```toml
path_forcing = "forcing-operational.nc"
path_static  = "staticmaps-ijssel.nc"
```

Laat `[time]` staan zoals het is — die waarden worden door wflow genegeerd, maar `run_ijssel.jl` print ze wel. Voeg daarom boven `[time]` deze commentaarregel toe:

```toml
# LET OP: wflow negeert starttime/endtime (ARM-JIT-patches, zie
# tools/arm_patches/README.md). Het rekenvenster komt uit de tijdas van
# forcing-operational.nc. run_ijssel.jl print deze waarden wel — negeer die regel.
```

Maak daarna de operationele invoermap en vul hem met symlinks naar de gedeelde statische invoer, plus een kopie van de instates als startpunt:

```bash
mkdir -p wflow_ijssel/data/operational wflow_ijssel/data/output_operational
ln -sf ../input/staticmaps-ijssel.nc wflow_ijssel/data/operational/staticmaps-ijssel.nc
cp wflow_ijssel/data/input/instates-ijssel.nc wflow_ijssel/data/operational/instates-ijssel.nc
ls -la wflow_ijssel/data/operational/
```

`data/` staat in `.gitignore`, dus deze bestanden komen niet in git — dat is de bedoeling.

- [ ] **Step 4: Write minimal implementation**

Maak `wflow_ijssel/operational/nowcast.py`:

```python
"""Nachtelijke wflow-nowcast met warme state.

Cyclus:
  1. bouw forcing over [D-1, D+14]
  2. draai wflow vanaf de instates van gisteren
  3. ALLEEN bij exitcode 0: promoveer outstates -> instates
  4. schrijf latest.json atomair

Stap 3 is kritiek: één mislukte nacht mag de warme keten niet breken. Bij
falen blijven de oude instates staan en draait de volgende nacht met een dag
extra forcing.
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


def build_forcing_window(path, start: str, end: str) -> dict:
    from wflow_ijssel.operational.forcing import build_forcing
    return build_forcing(path, start, end)


def run_wflow(config_path=CONFIG, timeout: int = 1800) -> int:
    """Draai wflow via run_ijssel.jl. Retourneert de exitcode."""
    cmd = ["julia"]
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
    """Maak de outstates van deze run de instates van morgen."""
    out_states = Path(out_states or OUT_STATES)
    in_states = Path(in_states or IN_STATES)
    if not out_states.exists():
        logger.warning("outstates ontbreekt (%s) — instates blijven staan", out_states)
        return False
    shutil.copy2(out_states, in_states)
    return True


def read_csv_output(path) -> dict:
    """Lees output_ijssel.csv naar dagreeksen."""
    import csv as _csv

    dates, q_kampen, q_west = [], [], []
    with open(path, newline="") as f:
        for row in _csv.DictReader(f):
            dates.append(row["time"][:10])
            q_kampen.append(float(row["Q_kampen"]))
            q_west.append(float(row["Q_westervoort"]))
    return {"dates": dates, "q_kampen": q_kampen, "q_westervoort": q_west}


def write_latest(path, payload: dict) -> Path:
    """Schrijf atomair: nooit een half bestand voor de lezer."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1))
    os.replace(tmp, path)
    return path


def run_nightly() -> dict:
    """De volledige nachtelijke cyclus."""
    today = date.today()
    start = (today - timedelta(days=1)).isoformat()
    end = (today + timedelta(days=HORIZON)).isoformat()

    meta = build_forcing_window(FORCING, start, end)
    code = run_wflow()
    if code != 0:
        logger.error("nachtrun mislukt (exit %d) — instates ongemoeid gelaten", code)
        return {"status": "mislukt", "exit_code": code}

    promoted = promote_states()
    series = read_csv_output(OUT_DIR / "output_ijssel.csv")
    payload = {
        "status": "ok",
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "issue_date": today.isoformat(),
        "model": "wflow SBM 1.0.2 (kinematic wave)",
        "boundary_sources": meta.get("sources"),
        "lobith_ratio": meta.get("ratio"),
        "states_promoted": promoted,
        "series": series,
    }
    write_latest(LATEST, payload)
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    res = run_nightly()
    raise SystemExit(0 if res.get("status") == "ok" else 1)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `/usr/bin/python3 -m pytest tests/test_operational_nowcast.py -v`
Expected: PASS, 5 passed

- [ ] **Step 6: Draai de echte nachtrun één keer**

Run: `/usr/bin/python3 -m wflow_ijssel.operational.nowcast`

Dit duurt enkele minuten (forcing ophalen + wflow-run). Verwacht: exitcode 0 en een `latest.json`. Controleer daarna:

```bash
/usr/bin/python3 -c "
import json
d = json.load(open('wflow_ijssel/data/forecast/latest.json'))
s = d['series']
print('status:', d['status'], '| states gepromoveerd:', d['states_promoted'])
print('ratio Westervoort/Lobith:', d['lobith_ratio'])
print('dagen:', len(s['dates']), s['dates'][0], '..', s['dates'][-1])
print('Q_kampen bereik:', round(min(s['q_kampen']),1), '..', round(max(s['q_kampen']),1))
"
```
Expected: `status: ok`, ongeveer 15 dagen, en een Q_kampen in een plausibel bereik. **Toets dat laatste tegen de werkelijkheid:** de RWS-meting bij Olst was begin september 2026 ongeveer 116–154 m³/s, en Kampen ligt benedenstrooms van Olst, dus een orde van 100–200 m³/s is plausibel. Krijg je 1e-8 of 10 000, dan is er iets grondig mis met de forcing of de state — meld dat en ga niet door.

- [ ] **Step 7: Controleer dat de historische uitvoer onaangeroerd is**

Run: `ls -la wflow_ijssel/data/output/output_ijssel.nc wflow_ijssel/data/input/instates-ijssel.nc`
Expected: beide nog op hun oude datum (1 juni respectievelijk 31 mei 2026).

- [ ] **Step 8: Commit**

```bash
git add wflow_ijssel/operational/nowcast.py wflow_ijssel/ijssel_config_operational.toml tests/test_operational_nowcast.py
git commit -m "feat(operational): warme-state-cyclus en nachtelijke wflow-nowcast

Promoveert de outstates alleen bij exitcode 0, zodat een mislukte nacht
de warme keten niet breekt. latest.json wordt atomair geschreven.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Het dashboard leest `latest.json`

**Files:**
- Modify: `dashboard/forecast.py` (uitbreiden `build_forecast`)
- Test: `tests/test_forecast_wflow_block.py`

**Interfaces:**
- Consumes: `latest.json` uit taak 4.
- Produces: `read_wflow_forecast(path=None, today=None) -> dict` in `dashboard/forecast.py` — retourneert `{"available": bool, "status": str, "age_days": int|None, "dates": [...], "q_kampen": [...], "note": str}`. `build_forecast()` krijgt een extra sleutel `"wflow"` met die inhoud.

Statusregels, met `age_days = (vandaag − issue_date).days`:

| `age_days` | status | `available` |
|---|---|---|
| 0 of 1 | `vers` | `True` |
| 2 | `verouderd` | `True` |
| 3 of meer | `vervallen` | `False` |

Daarnaast `ontbreekt` (geen bestand), `onleesbaar` (kapotte JSON of ongeldige datum) en `mislukt` (de nachtrun schreef `status != "ok"`), alle drie met `available: False`. Bij `available: False` valt de tab terug op het statistische model.

- [ ] **Step 1: Write the failing test**

Maak `tests/test_forecast_wflow_block.py`:

```python
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


def test_ouder_dan_48_uur_vervalt(tmp_path):
    p = _schrijf(tmp_path, "2026-09-08")
    r = read_wflow_forecast(p, today=date(2026, 9, 11))
    assert r["available"] is False
    assert r["status"] == "vervallen"
    assert r["age_days"] == 3


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


def test_mislukte_nachtrun_is_niet_beschikbaar(tmp_path):
    p = _schrijf(tmp_path, "2026-09-08", status="mislukt")
    r = read_wflow_forecast(p, today=date(2026, 9, 8))
    assert r["available"] is False
    assert r["status"] == "mislukt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_forecast_wflow_block.py -v`
Expected: FAIL met `ImportError: cannot import name 'read_wflow_forecast'`

- [ ] **Step 3: Write minimal implementation**

Voeg aan `dashboard/forecast.py` toe, ná de bestaande imports:

```python
import json
from pathlib import Path

WFLOW_LATEST = (Path(__file__).resolve().parent.parent
                / "wflow_ijssel" / "data" / "forecast" / "latest.json")

MAX_AGE_DAYS = 2      # ouder dan 48 uur → vervallen, tab valt terug op statistisch
```

en onderaan de module:

```python
def read_wflow_forecast(path=None, today=None) -> dict:
    """Lees de nachtelijke wflow-nowcast uit latest.json.

    Het dashboard rekent niets: het leest wat de nachtrun heeft weggeschreven.
    Iedere degradatie is zichtbaar via `status` — stil terugvallen zou hier het
    ergste zijn wat we konden doen.
    """
    from datetime import date as _date

    path = Path(path) if path is not None else WFLOW_LATEST
    today = today or _date.today()
    leeg = {"available": False, "age_days": None, "dates": [], "q_kampen": [],
            "q_westervoort": []}

    if not path.exists():
        return {**leeg, "status": "ontbreekt",
                "note": "Nog geen wflow-nowcast beschikbaar."}
    try:
        data = json.loads(path.read_text())
    except Exception as e:
        logger.warning("latest.json onleesbaar: %s", e)
        return {**leeg, "status": "onleesbaar",
                "note": "De wflow-nowcast kon niet gelezen worden."}

    if data.get("status") != "ok":
        return {**leeg, "status": "mislukt",
                "note": "De laatste nachtrun is mislukt."}

    try:
        issue = _date.fromisoformat(data["issue_date"])
    except Exception:
        return {**leeg, "status": "onleesbaar",
                "note": "De wflow-nowcast heeft geen geldige uitgiftedatum."}

    age = (today - issue).days
    series = data.get("series", {})
    if age > MAX_AGE_DAYS:
        return {**leeg, "status": "vervallen", "age_days": age,
                "note": f"De wflow-nowcast is {age} dagen oud en wordt niet meer getoond; "
                        "de verwachting valt terug op het statistische model."}

    status = "vers" if age <= 1 else "verouderd"
    note = ("Nachtelijke wflow SBM-nowcast." if status == "vers"
            else f"De wflow-nowcast is van {issue.isoformat()} ({age} dagen oud).")
    return {
        "available": True, "status": status, "age_days": age,
        "issue_date": data["issue_date"],
        "dates": series.get("dates", []),
        "q_kampen": series.get("q_kampen", []),
        "q_westervoort": series.get("q_westervoort", []),
        "model": data.get("model"),
        "boundary_sources": data.get("boundary_sources"),
        "note": note,
    }
```

Voeg tot slot in `build_forecast()` de nieuwe sleutel toe aan het `result`-dict, direct ná `"forecast": {...}`:

```python
        "wflow": read_wflow_forecast(),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/usr/bin/python3 -m pytest tests/test_forecast_wflow_block.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Controleer het live endpoint**

Run:
```bash
sudo systemctl restart waterlab-dashboard.service && sleep 6
curl -s --max-time 90 http://127.0.0.1:8000/api/forecast | /usr/bin/python3 -c "
import json,sys
d=json.load(sys.stdin)['wflow']
print('status:', d['status'], '| beschikbaar:', d['available'], '| leeftijd:', d['age_days'])
print('note:', d['note'])
print('dagen:', len(d['dates']))
"
```
Expected: `status: vers`, `beschikbaar: True`, en evenveel dagen als de nachtrun schreef.

- [ ] **Step 6: Commit**

```bash
git add dashboard/forecast.py tests/test_forecast_wflow_block.py
git commit -m "feat(forecast): wflow-nowcast in /api/forecast met terugvalstatus

Het dashboard leest latest.json en rekent zelf niets. Ouder dan 48 uur
vervalt de lijn en valt de tab terug op het statistische model.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Systemd-timer en documentatie

**Files:**
- Create: `waterlab-nowcast.service`
- Create: `waterlab-nowcast.timer`
- Modify: `CLAUDE.md` (secties "Stack & poorten" en "Run")
- Modify: `README.md` (API-lijst)

**Interfaces:**
- Consumes: `wflow_ijssel/operational/nowcast.py` uit taak 4.
- Produces: geen code-interface.

- [ ] **Step 1: Maak de unit-bestanden**

Maak `waterlab-nowcast.service`:

```ini
[Unit]
Description=Waterlab — nachtelijke wflow SBM-nowcast
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=bob
WorkingDirectory=/mnt/nvme/workspaces/waterlab
ExecStart=/usr/bin/python3 -m wflow_ijssel.operational.nowcast
# De run haalt eerst meteo op en rekent daarna; ruim bemeten.
TimeoutStartSec=2400
StandardOutput=journal
StandardError=journal
```

Maak `waterlab-nowcast.timer`:

```ini
[Unit]
Description=Draai de Waterlab-nowcast elke nacht om 03:00

[Timer]
OnCalendar=*-*-* 03:00:00
# Als de machine om 03:00 uit stond, alsnog draaien bij de eerstvolgende start.
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 2: Installeer en test de timer**

Run:
```bash
sudo cp waterlab-nowcast.service waterlab-nowcast.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now waterlab-nowcast.timer
systemctl list-timers waterlab-nowcast.timer --no-pager
```
Expected: de timer staat actief met een volgende trigger om 03:00.

- [ ] **Step 3: Draai de service handmatig één keer**

Run:
```bash
sudo systemctl start waterlab-nowcast.service
sleep 5
systemctl status waterlab-nowcast.service --no-pager | head -20
journalctl -u waterlab-nowcast.service -n 30 --no-pager
```
Expected: de service loopt (of is klaar met `code=exited, status=0/SUCCESS`). Duurt enkele minuten; wacht hem af met `journalctl -u waterlab-nowcast.service -f` als hij nog bezig is. Bij een niet-nul exit: lees `wflow_ijssel/data/output_operational/run.log` en meld wat daar staat.

- [ ] **Step 4: Werk `CLAUDE.md` bij**

Voeg onder "## Stack & poorten" een regel toe ná de regel over het dashboard:

```markdown
- Nachtelijke wflow-nowcast: systemd `waterlab-nowcast.timer` (03:00) → `wflow_ijssel/operational/nowcast.py` → `wflow_ijssel/data/forecast/latest.json`; het dashboard leest dat bestand en rekent zelf niets.
```

Voeg onder "## Run" toe:

```markdown
- Nowcast handmatig: `/usr/bin/python3 -m wflow_ijssel.operational.nowcast` (enkele minuten) · log: `wflow_ijssel/data/output_operational/run.log`
- Timer: `systemctl list-timers waterlab-nowcast.timer` · `journalctl -u waterlab-nowcast.service -f`
```

Voeg onder "## Valkuilen (project)" toe:

```markdown
- **De operationele run schrijft naar `data/operational/` + `data/output_operational/`** en heeft een eigen `instates`. Raak `data/input/instates-ijssel.nc` en `data/output*/` van de historische proeven niet aan.
```

- [ ] **Step 5: Werk `README.md` bij**

Voeg in de API-lijst (bij `GET /api/forecast`) toe dat het antwoord sinds fase C een `wflow`-blok bevat met de nachtelijke nowcast en een `status`-veld (`vers` / `verouderd` / `vervallen` / `ontbreekt` / `onleesbaar` / `mislukt`).

- [ ] **Step 6: Draai de volledige suite**

Run: `/usr/bin/python3 -m pytest tests/ -q --ignore=tests/test_download_inflow.py`
Expected: 2 failed, 4 errors (de bekende pre-existente), en alle nieuwe tests groen — dat zijn er 7 + 10 + 5 + 5 + 7 = 34 bij, dus 83 passed.

- [ ] **Step 7: Commit**

```bash
git add waterlab-nowcast.service waterlab-nowcast.timer CLAUDE.md README.md
git commit -m "feat(operational): systemd-timer voor de nachtelijke nowcast

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Zelfcontrole op dit plan

**Spec-dekking (fase C uit §6 van de spec: forcing-bouw, warme-state-cyclus, cron, latest.json, dashboard leest het, fallback-banner).** Forcing-bouw = taken 1–3. Warme-state-cyclus + `latest.json` = taak 4. Dashboard leest het + terugvalstatus = taak 5. Cron = taak 6. Alle onderdelen hebben een taak.

**Bewust niet in dit plan**, met reden:
- **Het ensemble** (fase E). De API is in fase 0 wél al geverifieerd en de keuze is vastgelegd (`ecmwf_ifs025`, 50 leden, 14 dagen; níét `icon_eu`), zodat fase E daar niet opnieuw tegenaan loopt. Fase C draait één deterministische run.
- **De peil-laag** (fase D) en **de grafiek op de tab** (fase F). Taak 5 levert alleen het backend-blok; de frontend blijft ongemoeid.
- **Herkalibratie van de peil-relatie tegen wflow-Q** — hoort bij fase D.

**Grootste risico in dit plan:** de y-richting van het forcing-grid. Een oplopende as levert een gespiegeld stroomgebied op zonder dat wflow klaagt. Taak 1 en taak 3 toetsen dat allebei expliciet, en taak 4 stap 6 vangt het alsnog met een plausibiliteitstoets op de orde van grootte van Q_kampen.
