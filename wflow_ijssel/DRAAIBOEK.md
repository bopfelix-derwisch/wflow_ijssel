# IJssel Wflow Dashboard — Draaiboek

Stap-voor-stap instructies om de simulatie te draaien en het dashboard te starten.

Voer alle commando's uit vanuit `/home/bob/waterlab/wflow_ijssel` met de venv actief:

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
```

---

## Stap 1 — Statische kaarten bouwen (HydroMT)

Eenmalig, duurt 10–30 minuten. Vereist internetverbinding naar Deltares data servers.

```bash
python build_staticmaps.py
```

Verwachte output:
```
INFO: Staticmaps geschreven: data/input/staticmaps-ijssel.nc
INFO: Instates geschreven:   data/input/instates-ijssel.nc
```

**Bij HTTP 429 (rate limit):** wacht 10–15 minuten en probeer opnieuw.

**Bij `KeyError: 'merit_hydro'`:** controleer HydroMT-versie:
```bash
pip show hydromt-wflow | grep Version   # verwacht: 0.8.x
```

Resultaat: `data/input/staticmaps-ijssel.nc` en `data/input/instates-ijssel.nc`.

---

## Stap 2 — CDS API-sleutel configureren + ERA5 forcing downloaden

### 2a. CDS-account (eenmalig)

1. Maak een gratis account aan op https://cds.climate.copernicus.eu
2. Ga na inloggen naar **Your profile** (rechtsboven) → scroll naar **API key**
3. Noteer je **UID** en **API key**

### 2b. ~/.cdsapirc aanmaken

```bash
cat > ~/.cdsapirc << 'EOF'
url: https://cds.climate.copernicus.eu/api/v2
key: <UID>:<API-sleutel>
verify: 1
EOF
```

Vervang `<UID>:<API-sleutel>` door jouw waarden, bijv. `123456:abcdef12-3456-...`.

### 2c. ERA5 downloaden

```bash
python download_forcing.py
```

Verwachte output:
```
INFO: CDS request ingediend voor dec 1994 ...
INFO: CDS request ingediend voor jan 1995 ...
INFO: Forcing geschreven: data/input/forcing-ijssel.nc
```

**Let op:** CDS-requests gaan in een wachtrij; bij drukte kan dit 5–30 minuten duren.

**Bij `Authentication failed`:** controleer `~/.cdsapirc` — formaat is exact `UID:sleutel` zonder spaties.

Resultaat: `data/input/forcing-ijssel.nc`.

---

## Stap 3 — Westervoort inflow downloaden (RWS Waterinfo)

Vereist dat stap 1 klaar is.

```bash
python download_inflow.py
```

Verwachte output:
```
INFO: Ophalen debiet Westervoort van RWS Waterinfo ...
INFO: Debiet opgehaald: 62 dagen, piek=3124 m3/s
INFO: Westervoort gridcel: x=87, y=34
INFO: Geschreven: data/input/inflow-westervoort.nc
```

**Bij verbindingsfout:** de RWS API is openbaar maar soms tijdelijk onbeschikbaar — wacht enkele minuten en probeer opnieuw.

**Bij `KeyError: WaarnemingenLijst`:** controleer de API-response:
```bash
python -c "
import requests, json
from download_inflow import RWS_URL, RWS_PAYLOAD
r = requests.post(RWS_URL, json=RWS_PAYLOAD, timeout=30)
print(r.status_code)
print(json.dumps(r.json(), indent=2)[:500])
"
```

Resultaat: `data/input/inflow-westervoort.nc`.

---

## Stap 4 — Wflow SBM simulatie draaien

Vereist dat stappen 1–3 klaar zijn.

```bash
julia --project=. run_ijssel.jl
```

Verwachte output:
```
Starten Wflow SBM simulatie IJssel ...
  Periode: 1994-12-01T00:00:00 → 1995-01-31T00:00:00
  Input:   data/input
  Output:  data/output
[ Info: run from 1994-12-01T00:00:00 until 1995-01-31T00:00:00
  ...
Klaar. Output in: data/output
```

Looptijd: 5–20 minuten afhankelijk van CPU.

**Bij `FileNotFoundError` voor een NetCDF:** controleer of alle inputs aanwezig zijn:
```bash
ls data/input/
# verwacht: staticmaps-ijssel.nc  instates-ijssel.nc  forcing-ijssel.nc  inflow-westervoort.nc
```

**Bij een Julia package error:**
```bash
julia --project=. -e "import Pkg; Pkg.instantiate()"
```

Resultaat: `data/output/output_ijssel.nc` met variabelen `q_river` en `h_river` voor elke dag.

---

## Stap 5 — Output exporteren naar dashboard-formaat

```bash
python export_output.py
```

Verwachte output:
```
INFO: Laden data/output/output_ijssel.nc ...
INFO: Rivier-cellen: 847
INFO: Geschreven: data/output/timeseries_kampen.json
INFO: Geschreven: data/output/timeseries_westervoort.json
INFO: KPI's: {'peak_q': 3241.5, 'peak_date': '1995-01-31', 'days_above_threshold': 18}
INFO: GeoJSON bestanden: 31 dagen
INFO: Export klaar.
```

Resultaat: `data/output/` bevat `kpis.json`, `timeseries_kampen.json`, `timeseries_westervoort.json`, en `river_day_1995-01-01.geojson` t/m `river_day_1995-01-31.geojson`.

---

## Stap 6 — Dashboard starten

```bash
python -m uvicorn dashboard.server:app --host 127.0.0.1 --port 8000
```

Open in je browser: **http://127.0.0.1:8000**

Het dashboard toont:
- 4 KPI-blokken: piekafvoer Kampen, maximale instroom Westervoort, neerslaganomalie, duur boven drempel
- 3D kaart (deck.gl): rivierdebiet als kolommen — hoogte = debiet, kleur blauw → oranje → rood
- Tijdslider: scrub door 1–31 januari 1995 (dag-resolutie), met ▶ play-knop
- Tijdreeksgrafiek (Plotly): debiet m³/s (rood, links) + waterpeil m+NAP (groen gestippeld, rechts) + drempellijn 1500 m³/s

Stoppen: `Ctrl+C`.

---

## Snel overzicht — alle commando's achter elkaar

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate

python build_staticmaps.py          # stap 1  (~10-30 min, eenmalig)
python download_forcing.py          # stap 2c (~5-30 min, CDS wachtrij)
python download_inflow.py           # stap 3  (~1 min)
julia --project=. run_ijssel.jl     # stap 4  (~5-20 min)
python export_output.py             # stap 5  (~1 min)
python -m uvicorn dashboard.server:app --host 127.0.0.1 --port 8000  # stap 6
```
