# Verwachting v2 — fase A + B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** De RWS-sentinelbug structureel oplossen via één gedeelde RWS-ingang, en de wflow-rekenkern reproduceerbaar maken (bouwscripts repareren, ARM-patches vastleggen, tijdvenster-gedrag documenteren) — zodat fase C erop kan bouwen.

**Architecture:** Fase A voegt `dashboard/rws_client.py` toe als enige plek die `rws_waterinfo.get_data` aanroept; `forecast.py` en `reservoir.py` gaan daar doorheen, waarbij `forecast._rws_daily` als dunne alias blijft bestaan omdat `assimilation.py` en `validation.py` die naam importeren. Fase B repareert de twee Julia-bouwscripts, legt de vier ARM-JIT-patches vast in `tools/arm_patches/` met een verifier, en documenteert dat wflow het tijdvenster uit de forcing haalt en niet uit de TOML.

**Tech Stack:** Python 3.10 (system python `/usr/bin/python3`, packages via `--user`), pytest 9.0.3, pandas, `rws_waterinfo`; Julia 1.12.5 met Wflow 1.0.2 en PackageCompiler.

## Global Constraints

- Tests draaien met `/usr/bin/python3 -m pytest` vanaf de repo-root; `conftest.py` zet de root op `sys.path`.
- **Committen mag zonder te vragen** (de gebruiker heeft dit op 2026-09-08 expliciet toegestaan voor dit werk). Voer de commit-stappen gewoon uit. **Pushen valt hier niet onder** — dat blijft op verzoek.
- Commit-trailer: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- We zitten op `master`, de hoofdbranch. Maak vóór taak 1 een werkbranch `feat/verwachting-v2-fase-ab` en commit daarop.
- **Raak `wflow_ijssel/data/output/` nooit aan** — dat is de Proef 4-output (1995), staat in `.gitignore`, is niet in git en kost uren om te herbouwen.
- Sentinel-constanten, exact: kwaliteitscode `"99"`, sentinelwaarde `999999999`, drempel `1e6`.
- Kolomnamen uit de RWS-API, exact: `"Meetwaarde.Waarde_Numeriek"`, `"WaarnemingMetadata.Kwaliteitswaardecode"`, `"Tijdstip"`.
- Nederlandse docstrings en commentaar, conform de rest van `dashboard/`.
- Geen versiebump van `app.js` in dit plan — fase A en B raken geen frontend-code.

---

### Task 1: `filter_sentinels` — de pure kern van de fix

**Files:**
- Create: `dashboard/rws_client.py`
- Test: `tests/test_rws_client.py`

**Interfaces:**
- Consumes: niets.
- Produces: `filter_sentinels(df: pd.DataFrame) -> tuple[pd.DataFrame, int]` — geeft (schone dataframe, aantal verwijderde rijen). Constanten `QUALITY_MISSING = "99"`, `SENTINEL_ABS = 1e6`, `VALUE_COL`, `QUALITY_COL`, `TIME_COL`.

- [ ] **Step 1: Write the failing test**

Maak `tests/test_rws_client.py`:

```python
"""Sentinel-filtering op RWS-ruwdata (fase A)."""
import pandas as pd
import pytest

from dashboard.rws_client import (
    QUALITY_COL, QUALITY_MISSING, TIME_COL, VALUE_COL, filter_sentinels,
)


def _df(rows):
    """rows = [(tijdstip, waarde, kwaliteitscode)]"""
    return pd.DataFrame({
        TIME_COL: [r[0] for r in rows],
        VALUE_COL: [r[1] for r in rows],
        QUALITY_COL: [r[2] for r in rows],
    })


def test_verwijdert_sentinel_op_kwaliteitscode():
    df = _df([
        ("2026-01-01T00:00:00.000+01:00", -30.0, "00"),
        ("2026-01-01T00:15:00.000+01:00", 999999999.0, QUALITY_MISSING),
        ("2026-01-01T00:30:00.000+01:00", -28.0, "00"),
    ])
    clean, removed = filter_sentinels(df)
    assert removed == 1
    assert list(clean[VALUE_COL]) == [-30.0, -28.0]


def test_verwijdert_sentinel_ook_zonder_kwaliteitskolom():
    # Sommige responses missen de kwaliteitskolom; de magnitude-drempel vangt het dan.
    df = pd.DataFrame({
        TIME_COL: ["2026-01-01T00:00:00.000+01:00", "2026-01-01T00:15:00.000+01:00"],
        VALUE_COL: [-30.0, 999999999.0],
    })
    clean, removed = filter_sentinels(df)
    assert removed == 1
    assert list(clean[VALUE_COL]) == [-30.0]


def test_behoudt_kwaliteitscode_25():
    # '25' is een geldige, afwijkende code — geen sentinel.
    df = _df([("2026-01-01T00:00:00.000+01:00", -27.0, "25")])
    clean, removed = filter_sentinels(df)
    assert removed == 0
    assert len(clean) == 1


def test_verwijdert_niet_numerieke_waarden():
    df = _df([
        ("2026-01-01T00:00:00.000+01:00", "geen getal", "00"),
        ("2026-01-01T00:15:00.000+01:00", -29.0, "00"),
    ])
    clean, removed = filter_sentinels(df)
    assert removed == 1
    assert list(clean[VALUE_COL]) == [-29.0]


def test_negatieve_waarden_blijven_staan():
    # Waterstanden bij Ketelhaven zijn structureel negatief (m NAP); die mogen
    # niet als sentinel wegvallen.
    df = _df([("2026-01-01T00:00:00.000+01:00", -55.4, "00")])
    clean, removed = filter_sentinels(df)
    assert removed == 0
    assert clean[VALUE_COL].iloc[0] == pytest.approx(-55.4)


def test_leeg_dataframe():
    clean, removed = filter_sentinels(pd.DataFrame())
    assert removed == 0
    assert len(clean) == 0


def test_none_dataframe():
    clean, removed = filter_sentinels(None)
    assert clean is None
    assert removed == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_rws_client.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'dashboard.rws_client'`

- [ ] **Step 3: Write minimal implementation**

Maak `dashboard/rws_client.py`:

```python
"""Enige ingang naar RWS Waterinfo.

RWS levert ontbrekende metingen als de sentinelwaarde 999999999, met
`WaarnemingMetadata.Kwaliteitswaardecode == "99"`. Wie die meemiddelt in een
dag-gemiddelde krijgt een dagwaarde van ~6,9 miljoen (999999999 / 144
kwartierwaarden). Gemeten besmetting over 2023-09 … 2026-09: kampen.ijssel
0,03 %, ketelhaven.ketelmeer 0,26 %, olst 0,18 %, westervoort 0,24 %.

Deze module filtert dat weg vóór het resamplen. Alle RWS-verkeer in het
dashboard loopt hier doorheen — voeg geen tweede `rw.get_data`-aanroep toe.

Zie docs/superpowers/specs/2026-09-08-verwachting-v2-wflow-design.md §2.5.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

QUALITY_MISSING = "99"
SENTINEL_ABS = 1e6

VALUE_COL = "Meetwaarde.Waarde_Numeriek"
QUALITY_COL = "WaarnemingMetadata.Kwaliteitswaardecode"
TIME_COL = "Tijdstip"


def filter_sentinels(df: "pd.DataFrame | None") -> tuple["pd.DataFrame | None", int]:
    """Gooi sentinel- en niet-numerieke rijen weg.

    Retourneert (schone dataframe, aantal verwijderde rijen). Filtert op de
    kwaliteitscode als die kolom er is, en altijd op magnitude — sommige
    responses leveren de kolom niet mee.
    """
    if df is None or len(df) == 0:
        return df, 0

    values = pd.to_numeric(df[VALUE_COL], errors="coerce")
    keep = values.notna() & (values.abs() < SENTINEL_ABS)
    if QUALITY_COL in df.columns:
        keep &= df[QUALITY_COL].astype(str) != QUALITY_MISSING

    return df[keep], int((~keep).sum())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/usr/bin/python3 -m pytest tests/test_rws_client.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**
```bash
git add dashboard/rws_client.py tests/test_rws_client.py
git commit -m "fix(rws): filter RWS-sentinelwaarden (999999999, kwaliteitscode 99)

De API levert ontbrekende metingen als 999999999. Meegemiddeld in een
dag-gemiddelde geeft dat ~6,9 miljoen. Besmetting gemeten over 3 jaar:
0,03-0,26% van de rijen, afhankelijk van het station.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `daily_series` — de gedeelde fetch, en `forecast.py` erdoorheen

**Files:**
- Modify: `dashboard/rws_client.py` (toevoegen aan bestaand bestand)
- Modify: `dashboard/forecast.py:21-26` (importblok), `dashboard/forecast.py:50-79` (`_rws_daily`)
- Test: `tests/test_rws_client.py` (toevoegen)

**Interfaces:**
- Consumes: `filter_sentinels` uit Task 1.
- Produces: `daily_series(locatie: str, grootheid: str, eenheid: str, start, end, proces_type: str = "meting") -> pd.Series | None` — daggemiddelden, index `DatetimeIndex`, dtype float, lege dagen verwijderd. `forecast._rws_daily` blijft bestaan met dezelfde signatuur en delegeert hierheen.

- [ ] **Step 1: Write the failing test**

Voeg toe aan `tests/test_rws_client.py`:

```python
def test_daily_series_middelt_per_dag_zonder_sentinels(monkeypatch):
    """Twee dagen, met op dag 1 een sentinel die het gemiddelde zou verzieken."""
    from dashboard import rws_client

    raw = pd.DataFrame({
        TIME_COL: [
            "2026-01-01T00:00:00.000+01:00",
            "2026-01-01T00:15:00.000+01:00",
            "2026-01-02T00:00:00.000+01:00",
        ],
        VALUE_COL: [10.0, 999999999.0, 30.0],
        QUALITY_COL: ["00", QUALITY_MISSING, "00"],
    })
    monkeypatch.setattr(rws_client, "_RWS_OK", True)
    monkeypatch.setattr(rws_client, "rw", type("F", (), {
        "get_data": staticmethod(lambda *a, **k: raw)})())

    s = rws_client.daily_series("x", "WATHTE", "cm", "2026-01-01", "2026-01-02")
    assert list(s.values) == [10.0, 30.0]
    assert [str(d.date()) for d in s.index] == ["2026-01-01", "2026-01-02"]


def test_daily_series_geeft_none_bij_lege_respons(monkeypatch):
    from dashboard import rws_client

    monkeypatch.setattr(rws_client, "_RWS_OK", True)
    monkeypatch.setattr(rws_client, "rw", type("F", (), {
        "get_data": staticmethod(lambda *a, **k: pd.DataFrame())})())
    assert rws_client.daily_series("x", "Q", "m3/s", "2026-01-01", "2026-01-02") is None


def test_daily_series_geeft_none_als_alles_sentinel_is(monkeypatch):
    from dashboard import rws_client

    raw = pd.DataFrame({
        TIME_COL: ["2026-01-01T00:00:00.000+01:00"],
        VALUE_COL: [999999999.0],
        QUALITY_COL: [QUALITY_MISSING],
    })
    monkeypatch.setattr(rws_client, "_RWS_OK", True)
    monkeypatch.setattr(rws_client, "rw", type("F", (), {
        "get_data": staticmethod(lambda *a, **k: raw)})())
    assert rws_client.daily_series("x", "Q", "m3/s", "2026-01-01", "2026-01-02") is None


def test_daily_series_slikt_uitzonderingen(monkeypatch):
    from dashboard import rws_client

    def boom(*a, **k):
        raise RuntimeError("netwerk stuk")

    monkeypatch.setattr(rws_client, "_RWS_OK", True)
    monkeypatch.setattr(rws_client, "rw", type("F", (), {
        "get_data": staticmethod(boom)})())
    assert rws_client.daily_series("x", "Q", "m3/s", "2026-01-01", "2026-01-02") is None


def test_forecast_rws_daily_delegeert_naar_client(monkeypatch):
    """forecast._rws_daily blijft bestaan (assimilation.py en validation.py
    importeren die naam) maar mag geen eigen fetch-logica meer hebben."""
    from dashboard import forecast, rws_client

    gezien = {}

    def nep(locatie, grootheid, eenheid, start, end, proces_type="meting"):
        gezien.update(locatie=locatie, proces_type=proces_type)
        return pd.Series([1.0], index=pd.to_datetime(["2026-01-01"]))

    monkeypatch.setattr(rws_client, "daily_series", nep)
    out = forecast._rws_daily("westervoort", "Q", "m3/s", "2026-01-01", "2026-01-02")
    assert gezien == {"locatie": "westervoort", "proces_type": "meting"}
    assert list(out.values) == [1.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_rws_client.py -v`
Expected: FAIL — `AttributeError: module 'dashboard.rws_client' has no attribute 'daily_series'`

- [ ] **Step 3: Write minimal implementation**

Voeg boven in `dashboard/rws_client.py`, direct ná `logger = logging.getLogger(__name__)`, het importblok toe:

```python
try:
    import rws_waterinfo as rw
    _RWS_OK = True
except ImportError:  # pragma: no cover
    rw = None
    _RWS_OK = False
    logger.warning("rws_waterinfo niet geïnstalleerd — RWS-data niet beschikbaar")
```

Voeg onderaan `dashboard/rws_client.py` toe:

```python
def daily_series(locatie: str, grootheid: str, eenheid: str,
                 start, end, proces_type: str = "meting") -> "pd.Series | None":
    """Daggemiddelde RWS-reeks, sentinelvrij.

    Retourneert None bij uitval, lege respons of als er na filtering niets
    overblijft — nooit een reeks met sentinelwaarden erin.
    """
    if not _RWS_OK:
        return None
    try:
        df = rw.get_data(
            [{
                "locatie_code":      locatie,
                "compartiment_code": "OW",
                "grootheid_code":    grootheid,
                "eenheid_code":      eenheid,
                "start_date":        str(start),
                "end_date":          str(end),
                "proces_type":       proces_type,
            }],
            return_df=True,
            parallel=False,
        )
        if df is None or len(df) == 0:
            return None

        clean, removed = filter_sentinels(df)
        if removed:
            logger.info("RWS %s/%s/%s: %d sentinel-rijen verwijderd",
                        locatie, grootheid, proces_type, removed)
        if clean is None or len(clean) == 0:
            return None

        idx = pd.to_datetime(clean[TIME_COL].str[:19])
        vals = pd.to_numeric(clean[VALUE_COL]).astype(float)
        s = pd.Series(vals.values, index=idx).sort_index()
        daily = s.resample("D").mean().dropna()
        if len(daily) == 0:
            return None
        logger.info("RWS %s/%s/%s: %d dagwaarden", locatie, grootheid, proces_type, len(daily))
        return daily
    except Exception as e:
        logger.warning("RWS %s/%s: %s", locatie, grootheid, e)
        return None
```

Vervang in `dashboard/forecast.py` het importblok op regel 21-26:

```python
try:
    import rws_waterinfo as rw
    _RWS_OK = True
except ImportError:
    _RWS_OK = False
    logger.warning("rws_waterinfo niet geïnstalleerd — RWS-data niet beschikbaar")
```

door:

```python
from dashboard import rws_client
```

Vervang vervolgens de hele functie `_rws_daily` (regel 50-79) door:

```python
def _rws_daily(locatie: str, grootheid: str, eenheid: str,
               start: "date", end: "date",
               proces_type: str = "meting") -> "pd.Series | None":
    """Dunne alias op rws_client.daily_series.

    Blijft bestaan omdat assimilation.py en validation.py deze naam importeren.
    Alle fetch- en filterlogica zit in dashboard/rws_client.py.
    """
    return rws_client.daily_series(locatie, grootheid, eenheid, start, end, proces_type)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/usr/bin/python3 -m pytest tests/test_rws_client.py -v`
Expected: PASS, 12 passed

- [ ] **Step 5: Verify geen tweede fetch-pad meer in forecast.py**

Run: `grep -n "rw.get_data\|rws_waterinfo" dashboard/forecast.py`
Expected: geen uitvoer (exitcode 1)

- [ ] **Step 6: Draai de bestaande suite — niets mag breken**

Run: `/usr/bin/python3 -m pytest tests/ -q`
Expected: PASS. Als `test_server.py` netwerk nodig heeft en faalt, noteer dat als vooraf-bestaand en vergelijk met `git stash`-uitvoer voordat je het jezelf aanrekent.

- [ ] **Step 7: Commit**

```bash
git add dashboard/rws_client.py dashboard/forecast.py tests/test_rws_client.py
git commit -m "refactor(rws): forecast._rws_daily via gedeelde rws_client

Eén ingang naar RWS Waterinfo, met sentinel-filtering. De naam
_rws_daily blijft als alias bestaan; assimilation.py en validation.py
importeren die.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `reservoir._river_series` via de gedeelde client

**Files:**
- Modify: `dashboard/reservoir.py:41-65`
- Test: `tests/test_rws_client.py` (toevoegen)

**Interfaces:**
- Consumes: `rws_client.daily_series` uit Task 2.
- Produces: `reservoir._river_series(years: int = RIVER_YEARS) -> dict` — ongewijzigde signatuur en retourvorm (`{"YYYY-MM-DD": meter}`), maar sentinelvrij.

Dit is de plek waar de bug het meeste kwaad deed: `_river_series` voedt de v2b-regressie met vier jaar Kampen-waterstand, waarvan 0,03 % van de rijen sentinel was.

- [ ] **Step 1: Write the failing test**

Voeg toe aan `tests/test_rws_client.py`:

```python
def test_river_series_gebruikt_client_en_rekent_cm_naar_meter(monkeypatch):
    from dashboard import reservoir, rws_client

    monkeypatch.setattr(rws_client, "daily_series", lambda *a, **k: pd.Series(
        [-30.0, -25.0], index=pd.to_datetime(["2026-01-01", "2026-01-02"])))
    reservoir._river_cache.clear()

    out = reservoir._river_series(years=1)
    assert out == {"2026-01-01": -0.30, "2026-01-02": -0.25}


def test_river_series_leeg_bij_uitval(monkeypatch):
    from dashboard import reservoir, rws_client

    monkeypatch.setattr(rws_client, "daily_series", lambda *a, **k: None)
    reservoir._river_cache.clear()

    assert reservoir._river_series(years=1) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_rws_client.py -k river -v`
Expected: FAIL — `_river_series` roept nu nog rechtstreeks `rw.get_data` aan, dus de monkeypatch heeft geen effect en de test probeert het netwerk op (of geeft `{}` terug waar `{...}` verwacht wordt).

- [ ] **Step 3: Write minimal implementation**

Vervang in `dashboard/reservoir.py` de body van `_river_series` (regel 41-65) door:

```python
def _river_series(years: int = RIVER_YEARS) -> dict:
    """v2b — Kampen waterstand (WATHTE, m+NAP) daggemiddeld over ~years jaar; gedeelde
    river-driver. Lege dict bij uitval → het model valt terug op recharge-only (v2)."""
    hit = _river_cache.get(years)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    out: dict = {}
    try:
        from dashboard import rws_client
        end = date.today()
        start = end - timedelta(days=365 * years)
        daily = rws_client.daily_series("kampen.ijssel", "WATHTE", "cm", start, end)
        if daily is not None and len(daily):
            out = {ts.strftime("%Y-%m-%d"): float(v) / 100.0 for ts, v in daily.items()}  # cm → m
    except Exception as e:
        logger.warning("v2b river-fetch faalde: %s", e)
    _river_cache[years] = (time.monotonic(), out)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/usr/bin/python3 -m pytest tests/test_rws_client.py -v`
Expected: PASS, 14 passed

- [ ] **Step 5: Verify geen enkele module meer rechtstreeks fetcht**

Run: `grep -rn "rw.get_data" dashboard/`
Expected: alleen `dashboard/rws_client.py`

- [ ] **Step 6: Commit**

```bash
git add dashboard/reservoir.py tests/test_rws_client.py
git commit -m "fix(reservoir): v2b river-driver via rws_client, sentinelvrij

De 4-jaars Kampen-reeks die de v2b-regressie voedt bevatte sentinelrijen.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Herbepaal de cijfers die op vervuilde data zijn vastgesteld

**Files:**
- Create: `docs/superpowers/notes/2026-09-08-cijfers-na-sentinelfix.md`
- Modify: geen code

**Interfaces:**
- Consumes: de schone fetch uit Task 2 en 3.
- Produces: een genoteerde voor/na-vergelijking; geen code-interface.

De VAL-2-hindcastcijfers (bias +11 → +92 m³/s, RMSE 18 → 99, banddekking ~99 %) en de reservoir-NSE's (0,84 / 0,52 / 0,22) zijn bepaald toen de reeksen nog sentinelrijen bevatten. Dit is een verificatietaak, geen TDD-taak: de deliverable is een vastgelegd cijfermatig verschil.

- [ ] **Step 1: Leg de bestaande cijfers vast vóór de herstart**

Run:
```bash
curl -s http://127.0.0.1:8000/api/validation/hindcast > /tmp/hindcast_voor.json
curl -s http://127.0.0.1:8000/api/grondwater/reservoir > /tmp/reservoir_voor.json
```
Noteer uit `hindcast_voor.json` de velden `summary` en de eerste/laatste `bias` per horizon; uit `reservoir_voor.json` de `nse` per put. Deze draaien nog op de oude code (cache van 6 uur), dus dit is de "voor"-meting.

- [ ] **Step 2: Herstart de dienst zodat de nieuwe code geladen wordt**

Run: `sudo systemctl restart waterlab-dashboard.service && sleep 5 && systemctl is-active waterlab-dashboard.service`
Expected: `active`

- [ ] **Step 3: Haal de nieuwe cijfers op**

Run:
```bash
curl -s http://127.0.0.1:8000/api/validation/hindcast > /tmp/hindcast_na.json
curl -s http://127.0.0.1:8000/api/grondwater/reservoir > /tmp/reservoir_na.json
```
Let op: de reservoir-call duurt de eerste keer 30–60 s (meerjarige fetch). Wacht die af, kap hem niet af.

- [ ] **Step 4: Noteer het verschil**

Maak `docs/superpowers/notes/2026-09-08-cijfers-na-sentinelfix.md` met een tabel:

```markdown
# Cijfers voor en na de sentinelfix (2026-09-08)

De sentinelfix (fase A) haalt RWS-waarden `999999999` uit de reeksen vóór het
dag-gemiddelde. Onderstaande cijfers waren eerder op vervuilde data bepaald.

## WL-VAL-2 hindcast (Westervoort, recessiemodel)

| grootheid | voor | na |
|---|---|---|
| bias dag 1 | … | … |
| bias dag 14 | … | … |
| RMSE dag 7 | … | … |
| RMSE dag 14 | … | … |
| banddekking | … | … |

## Reservoir-NSE per put

| put | voor | na |
|---|---|---|
| GLD000000008239 | 0,84 | … |
| GLD000000053138 | 0,52 | … |
| GLD000000008262 | 0,22 | … |

## Duiding

[Eén alinea: is het verschil verwaarloosbaar of niet? Bij Westervoort was
0,24 % van de rijen besmet, bij Kampen 0,03 % — een klein aandeel, maar één
besmet kwartier verpest een hele dagwaarde, en die dag telt in de hindcast
even zwaar mee als elke andere. Als het verschil groot is, moet de
memory-notitie waterlab-graphql-and-data-state.md worden bijgewerkt.]
```

Vul de echte waarden in uit de vier JSON-bestanden. Laat geen `…` staan.

- [ ] **Step 5: Werk de projectmemory bij als de cijfers wezenlijk verschillen**

Als bias/RMSE/NSE meer dan ~5 % afwijken, werk dan de betreffende regels bij in
`/home/bob/.claude/projects/-mnt-nvme-workspaces-waterlab/memory/waterlab-graphql-and-data-state.md`
(secties "WL-VAL-2" en "Grondwater-voorspelling"), met een korte noot dat de oude
cijfers op vervuilde data rustten. Wijken ze niet wezenlijk af, noteer dán expliciet
in de notitie dat de oude cijfers houdbaar blijven.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/notes/2026-09-08-cijfers-na-sentinelfix.md
git commit -m "docs: cijfers voor/na de sentinelfix vastgelegd

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: De Julia-bouwscripts repareren

**Files:**
- Modify: `build_sysimage.jl:1-8`
- Modify: `precompile_wflow.jl:1-6`
- Create: `wflow_ijssel/ijssel_config_precompile.toml` (bestaat al untracked — nu in git brengen)

**Interfaces:**
- Consumes: niets.
- Produces: een werkende `julia --project=. build_sysimage.jl` die `wflow_sysimage.so` in de repo-root schrijft.

Beide scripts beginnen met een losse `"""…"""` boven een `using`. Julia leest dat als docstring en `using` is niet documenteerbaar → beide falen binnen een seconde met `ERROR: LoadError: cannot document the following expression`. Daarom zijn ze nooit gedraaid, en daarom stond WL-FC-1 als "geblokkeerd op de sysimage".

Daarnaast wijst `precompile_wflow.jl` naar `ijssel_config.toml` in de repo-root, waarvan `dir_input = "data/input"` naar een niet-bestaande top-level `data/`-map wijst. Het moet naar de geïsoleerde precompile-config in `wflow_ijssel/`.

- [ ] **Step 1: Verify de huidige scripts inderdaad falen**

Run: `julia --project=. precompile_wflow.jl 2>&1 | head -3`
Expected: `ERROR: LoadError: cannot document the following expression:` gevolgd door `using Wflow`

- [ ] **Step 2: Repareer `precompile_wflow.jl`**

Vervang de volledige inhoud van `precompile_wflow.jl` door:

```julia
# Precompile execution file voor PackageCompiler.
#
# Draait de wflow SBM-pijplijn op de IJssel-data zodat de zware methoden
# (Clock, Domain, LandHydrologySBM, Routing, update!) in de sysimage belanden.
#
# LET OP: geen `"""..."""` bovenaan dit bestand. Julia leest een losse string
# boven een `using` als docstring, en `using` is niet documenteerbaar — dat
# liet dit script jarenlang binnen een seconde falen.
#
# Schrijft naar wflow_ijssel/data/output_precompile/ en laat de Proef 4-output
# in wflow_ijssel/data/output/ met rust.
using Wflow
using Dates

toml_path = joinpath(@__DIR__, "wflow_ijssel", "ijssel_config_precompile.toml")

println("[precompile] start ", now())
flush(stdout)

config = Wflow.Config(toml_path)
Wflow.run(config)

println("[precompile] klaar ", now())
flush(stdout)
```

- [ ] **Step 3: Repareer `build_sysimage.jl`**

Vervang de volledige inhoud van `build_sysimage.jl` door:

```julia
# Bouwt een PackageCompiler-sysimage met Wflow erin.
#
# Gemeten op orin3 (Jetson AGX Orin, 2026-09-08):
#   bouwen                                  11,2 min  -> 486 MB
#   koude start zonder sysimage              2 min 15 s
#   koude start met sysimage, 62-daagse run 16,7 s
#
# Draaien:  julia --project=. build_sysimage.jl
# Gebruik:  julia --sysimage wflow_sysimage.so --project=. run_ijssel.jl
#
# PackageCompiler wordt in een tijdelijke omgeving geinstalleerd, zodat de
# Manifest.toml van het project schoon blijft.
#
# LET OP: geen `"""..."""` bovenaan dit bestand — zie precompile_wflow.jl.
using Pkg
using Dates

project_dir = @__DIR__

build_env = mktempdir()
Pkg.activate(build_env)
Pkg.add("PackageCompiler")

using PackageCompiler

println("[build] start ", now(), " — dit duurt ruim tien minuten op ARM")
flush(stdout)

t0 = time()

create_sysimage(
    ["Wflow"];
    sysimage_path             = joinpath(project_dir, "wflow_sysimage.so"),
    precompile_execution_file = joinpath(project_dir, "precompile_wflow.jl"),
    project                   = project_dir,
)

println("[build] klaar ", now(), " — ", round((time() - t0) / 60, digits = 1), " minuten")
println("Gebruik: julia --sysimage wflow_sysimage.so --project=. run_ijssel.jl")
flush(stdout)
```

- [ ] **Step 4: Verify dat het precompile-script nu draait**

Run: `julia --project=. precompile_wflow.jl 2>&1 | grep -E "precompile\]|Simulation duration"`
Expected: `[precompile] start …`, `[ Info: Simulation duration: …`, `[precompile] klaar …`

- [ ] **Step 5: Verify dat de Proef 4-output onaangeroerd is**

Run: `ls -la wflow_ijssel/data/output/output_ijssel.nc`
Expected: de bestaande datum (1 juni 2026), niet vandaag. Als dit bestand vandaag is aangeraakt, is er iets grondig mis — stop en meld het.

- [ ] **Step 6: Commit**

```bash
git add build_sysimage.jl precompile_wflow.jl wflow_ijssel/ijssel_config_precompile.toml
git commit -m "fix(build): Julia-bouwscripts draaien weer

Een losse docstring boven een 'using' is een harde Julia-fout; beide
scripts faalden binnen een seconde en zijn daardoor nooit gedraaid.
precompile_wflow.jl wees bovendien naar een config met een niet-bestaand
data/input-pad in de repo-root.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: De ARM-JIT-patches vastleggen en verifieerbaar maken

**Files:**
- Create: `tools/arm_patches/README.md`
- Create: `tools/arm_patches/verify_arm_patches.py`
- Create: `tools/arm_patches/patched/` (vier referentiekopieën)
- Test: `tests/test_arm_patches.py`

**Interfaces:**
- Consumes: niets.
- Produces: `verify_arm_patches.check(julia_depot: Path | None = None) -> list[dict]` — per patch een dict met `name`, `package`, `path`, `marker`, `present` (bool), `found_at` (Path of None). En `main()` die non-zero exit geeft als er een patch ontbreekt.

De vier patches staan in `~/.julia/packages/`, buiten git. Eén `Pkg.update` en de rekenkern is kapot of traag. Automatisch her-patchen is **bewust buiten scope**: daarvoor is de ongepatchte bronversie nodig, en een half-geslaagde automatische patch op andermans broncode is gevaarlijker dan een luide foutmelding. Deze taak levert een verifier plus referentiekopieën, zodat herstel een diff is in plaats van archeologie.

- [ ] **Step 1: Write the failing test**

Maak `tests/test_arm_patches.py`:

```python
"""Verificatie van de ARM-JIT-patches op Wflow en CFTime."""
from pathlib import Path

import pytest

from tools.arm_patches.verify_arm_patches import PATCHES, check


def test_alle_vier_de_patches_zijn_gedefinieerd():
    namen = {p["name"] for p in PATCHES}
    assert namen == {"clock-bypass", "endtime-concrete", "period-typestable",
                     "advance-nospecialize"}


def test_check_vindt_de_patches_in_een_nagebouwd_depot(tmp_path):
    """Bouw een minimaal depot na met de markerteksten erin."""
    for patch in PATCHES:
        f = tmp_path / "packages" / patch["package"] / "XXXXX" / patch["path"]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"# voorloop\n{patch['marker']}\n# naloop\n")

    resultaat = check(tmp_path)
    assert all(r["present"] for r in resultaat)
    assert len(resultaat) == 4


def test_check_meldt_een_ontbrekende_patch(tmp_path):
    for patch in PATCHES[1:]:
        f = tmp_path / "packages" / patch["package"] / "XXXXX" / patch["path"]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(patch["marker"])
    # PATCHES[0] bewust weggelaten
    f = tmp_path / "packages" / PATCHES[0]["package"] / "XXXXX" / PATCHES[0]["path"]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# ongepatchte upstream-versie\n")

    resultaat = check(tmp_path)
    ontbrekend = [r for r in resultaat if not r["present"]]
    assert len(ontbrekend) == 1
    assert ontbrekend[0]["name"] == PATCHES[0]["name"]


def test_check_op_leeg_depot_meldt_alles_ontbrekend(tmp_path):
    resultaat = check(tmp_path)
    assert not any(r["present"] for r in resultaat)


@pytest.mark.skipif(not (Path.home() / ".julia" / "packages").exists(),
                    reason="geen Julia-depot op deze machine")
def test_de_echte_installatie_is_gepatcht():
    """Op orin3 moeten alle vier de patches aanwezig zijn. Faalt deze test,
    dan is de wflow-rekenkern traag of stuk — zie tools/arm_patches/README.md."""
    resultaat = check()
    ontbrekend = [r["name"] for r in resultaat if not r["present"]]
    assert not ontbrekend, f"ontbrekende ARM-patches: {ontbrekend}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_arm_patches.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'tools.arm_patches'`

- [ ] **Step 3: Write minimal implementation**

Maak lege `tools/__init__.py` en `tools/arm_patches/__init__.py` (beide leeg), en maak `tools/arm_patches/verify_arm_patches.py`:

```python
"""Controleert of de ARM-JIT-patches op Wflow en CFTime nog aanwezig zijn.

Zonder deze patches loopt de eerste wflow-run op ARM vast in een LLVM-cascade
van 30+ minuten per fix. Ze staan in ~/.julia/packages/, buiten git: één
`Pkg.update` en ze zijn weg.

Draaien:  /usr/bin/python3 tools/arm_patches/verify_arm_patches.py
Exitcode: 0 als alles aanwezig is, 1 als er iets ontbreekt.

Zie tools/arm_patches/README.md voor wat elke patch doet en hoe je hem
terugzet met de referentiekopieën in tools/arm_patches/patched/.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Elke patch wordt herkend aan een markertekst die alleen in de gepatchte
# versie voorkomt. Zo hoeven we geen versienummers of regelnummers te volgen.
PATCHES = [
    {
        "name": "clock-bypass",
        "package": "Wflow",
        "path": "src/sbm_model.jl",
        "marker": "Fix 6 (ARM JIT)",
        "waarom": "Clock(config, reader) triggert een 30+ min LLVM-cascade via "
                  "CFTime-constructors; nctimes[1] wordt direct als starttime gebruikt.",
    },
    {
        "name": "endtime-concrete",
        "package": "Wflow",
        "path": "src/Wflow.jl",
        "marker": "Fix 7 (ARM JIT)",
        "waarom": "cftime() geeft een abstracte UnionAll terug; last(dataset_times) "
                  "wordt als endtime gebruikt. GEVOLG: starttime/endtime uit de TOML "
                  "worden genegeerd — het rekenvenster komt uit de forcing.",
    },
    {
        "name": "period-typestable",
        "package": "CFTime",
        "path": "src/period.jl",
        "marker": "_factor_type",
        "waarom": "Period's returntype hing van runtime-waarden af; _factor_type/"
                  "_exponent_type maken het type-stabiel.",
    },
    {
        "name": "advance-nospecialize",
        "package": "Wflow",
        "path": "src/io.jl",
        "marker": "@nospecialize(clock)",
        "waarom": "voorkomt een aparte specialisatie van advance!/rewind! per "
                  "concreet Clock-type.",
    },
]


def _depot_root(julia_depot: "Path | None" = None) -> Path:
    return Path(julia_depot) if julia_depot else Path.home() / ".julia"


def check(julia_depot: "Path | None" = None) -> list[dict]:
    """Zoek elke patch in alle geïnstalleerde kopieën van zijn pakket.

    Julia kan meerdere versies van een pakket naast elkaar hebben staan (op
    orin3 staan er drie CFTime-kopieën, waarvan er één gepatcht is). Een patch
    geldt als aanwezig zodra één kopie hem heeft.
    """
    packages = _depot_root(julia_depot) / "packages"
    resultaat = []
    for patch in PATCHES:
        found_at = None
        pkg_dir = packages / patch["package"]
        if pkg_dir.is_dir():
            for versie_dir in sorted(pkg_dir.iterdir()):
                bestand = versie_dir / patch["path"]
                if bestand.is_file() and patch["marker"] in bestand.read_text(errors="replace"):
                    found_at = bestand
                    break
        resultaat.append({**patch, "present": found_at is not None, "found_at": found_at})
    return resultaat


def main() -> int:
    resultaat = check()
    breedte = max(len(r["name"]) for r in resultaat)
    for r in resultaat:
        vlag = "OK  " if r["present"] else "WEG "
        plek = r["found_at"] or f"(niet gevonden in ~/.julia/packages/{r['package']})"
        print(f"{vlag} {r['name']:<{breedte}}  {plek}")

    ontbrekend = [r for r in resultaat if not r["present"]]
    if ontbrekend:
        print()
        print("ONTBREKENDE ARM-PATCHES — de wflow-rekenkern is nu traag of stuk.")
        print("Herstel: zie tools/arm_patches/README.md en de referentiekopieën")
        print("in tools/arm_patches/patched/.")
        return 1
    print("\nAlle ARM-patches aanwezig.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/usr/bin/python3 -m pytest tests/test_arm_patches.py -v`
Expected: PASS, 5 passed (inclusief `test_de_echte_installatie_is_gepatcht`)

- [ ] **Step 5: Draai de verifier tegen de echte installatie**

Run: `/usr/bin/python3 tools/arm_patches/verify_arm_patches.py`
Expected: vier `OK`-regels en `Alle ARM-patches aanwezig.`, exitcode 0

- [ ] **Step 6: Leg de referentiekopieën vast**

Run:
```bash
mkdir -p tools/arm_patches/patched
cp /home/bob/.julia/packages/Wflow/mJ7Ug/src/sbm_model.jl tools/arm_patches/patched/Wflow__sbm_model.jl
cp /home/bob/.julia/packages/Wflow/mJ7Ug/src/Wflow.jl      tools/arm_patches/patched/Wflow__Wflow.jl
cp /home/bob/.julia/packages/Wflow/mJ7Ug/src/io.jl         tools/arm_patches/patched/Wflow__io.jl
cp /home/bob/.julia/packages/CFTime/1IA4b/src/period.jl    tools/arm_patches/patched/CFTime__period.jl
cp /home/bob/.julia/packages/CFTime/1IA4b/src/datetime.jl  tools/arm_patches/patched/CFTime__datetime.jl
ls -la tools/arm_patches/patched/
```
Expected: vijf bestanden (Fix C raakt twee CFTime-bestanden).

- [ ] **Step 7: Schrijf de README**

Maak `tools/arm_patches/README.md`:

```markdown
# ARM-JIT-patches op Wflow en CFTime

Op ARM (Jetson AGX Orin) liep de eerste wflow-run vast in een LLVM-cascade van
uren. De oorzaak is type-instabiliteit: `cftime()` geeft een abstracte
`UnionAll` terug, waarna Julia honderden specialisaties compileert voor
codepaden die nooit worden gebruikt. Vier patches lossen dat op. Volledige
analyse: `LESSONS_LEARNED.md` §2.1.

**Deze patches staan in `~/.julia/packages/`, buiten git.** Eén `Pkg.update`
en ze zijn weg. Draai daarom `verify_arm_patches.py` voordat je op de
rekenkern vertrouwt.

| patch | pakket | bestand | marker |
|---|---|---|---|
| `clock-bypass` | Wflow | `src/sbm_model.jl` | `Fix 6 (ARM JIT)` |
| `endtime-concrete` | Wflow | `src/Wflow.jl` | `Fix 7 (ARM JIT)` |
| `period-typestable` | CFTime | `src/period.jl` | `_factor_type` |
| `advance-nospecialize` | Wflow | `src/io.jl` | `@nospecialize(clock)` |

`period-typestable` raakt ook `CFTime/src/datetime.jl` (de tweede
`unwrap`-overload); die wordt niet apart geverifieerd omdat `period.jl` en
`datetime.jl` altijd samen gepatcht zijn.

## Gevolg dat je moet kennen

`endtime-concrete` neemt `last(reader.dataset_times)` als eindtijd. Daardoor
**negeert wflow `starttime` en `endtime` uit de TOML**; het rekenvenster komt
volledig uit de tijdas van het forcing-bestand. Wie een kortere run wil, moet
de forcing slicen. Geverifieerd op 2026-09-08: een config met een venster van
10 dagen leverde 61 dagstappen op.

## Herstellen

Automatisch her-patchen doen we bewust niet — dat vereist de ongepatchte
bronversie, en een half-geslaagde patch op andermans broncode is gevaarlijker
dan een luide foutmelding. In `patched/` staan verbatim kopieën van de
gepatchte bestanden. Herstel is dus:

1. `/usr/bin/python3 tools/arm_patches/verify_arm_patches.py` — welke ontbreekt?
2. `diff patched/Wflow__io.jl ~/.julia/packages/Wflow/<hash>/src/io.jl`
3. Neem de ontbrekende wijziging met de hand over.
4. Verifieer opnieuw, en bouw de sysimage opnieuw met `julia --project=. build_sysimage.jl`
   (de sysimage bakt de gepatchte code in).

De kopieën in `patched/` horen bij Wflow 1.0.2 en de CFTime-versie met
git-tree-sha1 `912c24c352c4167df4ebdacb96a432a2e3dbaf7a`. Bij een andere
versie zijn ze een leidraad, geen kant-en-klare vervanging.
```

- [ ] **Step 8: Commit**

```bash
git add tools/__init__.py tools/arm_patches/ tests/test_arm_patches.py
git commit -m "chore(arm): ARM-JIT-patches vastgelegd met verifier

De vier patches op Wflow en CFTime stonden alleen in ~/.julia/packages/,
buiten git. Nu een verifier plus referentiekopieen, zodat herstel een
diff is in plaats van archeologie.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Het tijdvenster-gedrag documenteren waar mensen kijken

**Files:**
- Modify: `LESSONS_LEARNED.md` (sectie §2.1, na Fix B)
- Modify: `CLAUDE.md` (sectie "Valkuilen (project)")

**Interfaces:**
- Consumes: de bevinding uit Task 6.
- Produces: geen code-interface.

`LESSONS_LEARNED.md` beschrijft Fix B wel, maar nergens staat dat de patch de config-sleutels buiten werking stelt. Dat is precies de val waar fase C in loopt.

- [ ] **Step 1: Vul `LESSONS_LEARNED.md` aan**

Zoek in `LESSONS_LEARNED.md` het blok van Fix B dat eindigt met:

```julia
endtime = last(model.reader.dataset_times)
```

Voeg direct ná dat codeblok toe:

```markdown
**Gevolg voor operationeel gebruik (vastgesteld 2026-09-08):** omdat Fix A
`nctimes[1]` als starttime neemt en Fix B `last(dataset_times)` als endtime,
**negeert wflow de sleutels `starttime` en `endtime` uit de TOML volledig**.
Het rekenvenster komt uitsluitend uit de tijdas van het forcing-bestand.
Geverifieerd: een config met `starttime = 1994-12-15` en `endtime = 1994-12-25`
leverde 61 dagstappen op, tot het einde van de forcing. Wie het venster wil
sturen, moet de forcing slicen — niet de TOML aanpassen.
```

- [ ] **Step 2: Vul `CLAUDE.md` aan**

Voeg in `CLAUDE.md` onder "## Valkuilen (project)" twee bullets toe, ná de bestaande `app.js`-bullet:

```markdown
- **wflow negeert `starttime`/`endtime` uit de TOML** (gevolg van de ARM-JIT-patches): het rekenvenster komt uit de tijdas van het forcing-bestand. Venster sturen = forcing slicen. Zie `tools/arm_patches/README.md`.
- **ARM-patches op Wflow/CFTime staan buiten git** (`~/.julia/packages/`). Draai `/usr/bin/python3 tools/arm_patches/verify_arm_patches.py` voordat je op de rekenkern vertrouwt; zonder de patches duurt een koude start uren.
- **Alle RWS-verkeer via `dashboard/rws_client.py`** — die filtert de sentinel `999999999` (kwaliteitscode `99`). Voeg nooit een tweede `rw.get_data`-aanroep toe.
```

- [ ] **Step 3: Verify de documentatie klopt met de code**

Run: `grep -n "starttime" tools/arm_patches/README.md LESSONS_LEARNED.md CLAUDE.md | head`
Expected: de nieuwe passages staan er, en spreken elkaar niet tegen.

- [ ] **Step 4: Draai de volledige suite een laatste keer**

Run: `/usr/bin/python3 -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add LESSONS_LEARNED.md CLAUDE.md
git commit -m "docs: wflow negeert het TOML-tijdvenster; RWS via rws_client

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Zelfcontrole op dit plan

**Spec-dekking.** Fase A uit §6 van de spec: sentinel-fix (Task 1-3), `rws_client.py` als enige ingang (Task 2 stap 5, Task 3 stap 5), VAL-2 en reservoir-NSE's herbepaald (Task 4). Fase B: bouwscripts repareren (Task 5), ARM-patches vendoren (Task 6), §2.2 documenteren (Task 7). Alle zes onderdelen hebben een taak.

**Bewust niet in dit plan**, met reden:
- Automatisch her-patchen van upstream-broncode (Task 6) — vereist de ongepatchte bron; een verifier plus referentiekopieën is veiliger.
- De peil-laag, forcing-bouw, cron en ensembleband — dat is fase C tot en met F en krijgt een eigen plan.
