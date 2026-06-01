# IJssel Wflow Dashboard — Draaiboek

Stap-voor-stap instructies om de simulatie te draaien en het dashboard te starten.

Voer alle commando's uit vanuit `/home/bob/waterlab/wflow_ijssel` met de venv actief:

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate
```

---

## Stap 1 — Statische kaarten bouwen

Kies de aanpak die bij je situatie past:

### Optie A — Copernicus DEM (aanbevolen, geen registratie)

Downloadt ~180 MB DEM-tegels van AWS en leidt afvoernetwerk af met pyflwdir.
Duurt 5–10 minuten. Geen account vereist.

```bash
python build_staticmaps_copernicus.py
```

Verwachte output:
```
INFO: Stap 1/4: DEM-tegels downloaden van AWS Copernicus ...
INFO: Stap 2/4: Hersampelen naar 0.008333° (~1 km) ...
INFO: Stap 3/4: Afvoernetwerk afleiden met pyflwdir ...
INFO: Uitlaat gesnapped naar: lon=5.496 lat=53.221 uparea=10231 km²
INFO: Stroomgebied: 19490 cellen, rivieren: 1517 cellen
INFO: Stap 4/4: staticmaps.nc en instates.nc schrijven ...
INFO: Geschreven: data/input/staticmaps-ijssel.nc (14.4 MB)
INFO: Geschreven: data/input/instates-ijssel.nc
```

**Beperking:** Copernicus DEM bevat geen poldercorecties — het stroomgebied is iets ruimer dan de echte IJssel-grens. Voor een demo-/leerproject is dit acceptabel.

### Optie B — MERIT Hydro via HydroMT (wetenschappelijk correct)

Vereist toegang tot MERIT Hydro-tiles (registratie bij Deltares of Tokyo-server).

```bash
python build_staticmaps.py
```

**Bij `FileNotFoundError: No such file found: merit_hydro`:** MERIT Hydro is niet geconfigureerd. Gebruik Optie A of vraag een Deltares-account.

Resultaat (beide opties): `data/input/staticmaps-ijssel.nc` en `data/input/instates-ijssel.nc`.

---

## Stap 1b — LDD-routing corrigeren (Zwolle→Kampen)

De D8-routing uit MERIT Hydro stuurde de IJssel na Zwolle ten onrechte naar het noordoosten (richting Meppel) in plaats van naar het noordwesten (Kampen). Dit script burned de correcte PDOK NWB-centerline in `wflow_ldd`, `wflow_river` en `wflow_subcatch`.

**Vereisten:** `data/input/staticmaps-ijssel.nc` (stap 1) en `data/input/river_geom_ijssel.gpkg`.

```bash
# river_geom downloaden (eenmalig; vereist internet)
python download_river_geom.py

# LDD-fix toepassen (maakt backup als staticmaps-ijssel.nc.bak)
python fix_staticmaps.py
```

Verwachte output:
```
INFO: Junctiecel: lat=52.4708, lon=6.1708 → ldd wordt W
INFO: Brugcellen: 8  (lon 6.1708→6.1042 op lat 52.4708)
INFO: Totale nieuwe keten: 57 cellen
INFO: Cellen die parameter-fill nodig hebben: 40 nieuw-subcatch + 15 nieuw-river
INFO: Parameter-fill (NN): 55 cellen ingevuld
INFO: Terminus: lat=52.5792, lon=5.8375 (pit)
INFO: Opgeslagen: data/input/staticmaps-ijssel.nc
```

**Wat het doet:**
- Junctiecel (lat 52.47°N, lon 6.17°E) omgeleid van NE→W
- 8 brugcellen westwaarts naar PDOK-startpunt
- 49 PDOK-gecorrigeerde cellen tot aan Ketelmeer (nieuwe pit)
- `wflow_subcatch` uitgebreid met 40 cellen buiten het originele stroomgebied
- Alle statische parameters ingevuld via nearest-neighbour (land + rivier-specifiek)

**Zonder deze stap** lopen de rivierbalken in het dashboard na Zwolle ten onrechte naar het noordoosten.

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
INFO: Rivier-cellen: 140 (max_q>150 m³/s, lon 5.8–6.25°E, lat<52.65°N)
INFO: Geschreven: data/output/timeseries_kampen.json
INFO: Geschreven: data/output/timeseries_westervoort.json
INFO: KPI's: {'peak_q': 849.0, 'peak_date': '1995-01-30', 'days_above_threshold': 0}
INFO: GeoJSON bestanden: 31 dagen
INFO: Export klaar.
```

**Noot:** De piekafvoer van ~849 m³/s bij Kampen (echt Kampen, 5.921°E/52.555°N) is realistisch voor de gecorrigeerde route — de instromende Westervoort-grensconditie bepaalt het maximum. De 2021-simulatie (synthetische forcering) geeft 3058 m³/s.

Resultaat: `data/output/` bevat `kpis.json`, `timeseries_kampen.json`, `timeseries_westervoort.json`, en `river_day_1995-01-01.geojson` t/m `river_day_1995-01-31.geojson`.

---

## Stap 6 — Dashboard starten

```bash
python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8000
```

Open in je browser: **http://127.0.0.1:8000** of via de publieke URL **https://waterlab.felixisfelix.com**

Het dashboard toont:
- 4 KPI-blokken: piekafvoer Kampen, maximale instroom Westervoort, neerslaganomalie, duur boven drempel
- 3D kaart (deck.gl): rivierdebiet als kolommen — hoogte = debiet, kleur blauw → oranje → rood
- Tijdslider: scrub door 1–31 januari 1995 (dag-resolutie), met ▶ play-knop
- Tijdreeksgrafiek (Plotly): debiet m³/s (rood, links) + waterpeil m+NAP (groen gestippeld, rechts) + drempellijn 1500 m³/s

Stoppen: `Ctrl+C`.

---

## Stap 7 — Publieke URL via Cloudflare Tunnel

Het dashboard is bereikbaar via **https://waterlab.felixisfelix.com** dankzij een Cloudflare Tunnel die als systemd-service draait.

**Configuratie (eenmalig gedaan, geen actie vereist):**
- Cloudflare Tunnel ID: `ca12e4f6-fa0d-4f39-8868-e729d9369c5c`
- Systemd-service: `cloudflared.service` (autostart bij boot)
- Config: `~/.cloudflared/config.yml` — ingress `waterlab.felixisfelix.com` → `http://localhost:8000`
- DNS: CNAME `waterlab.felixisfelix.com` → `<tunnel-id>.cfargotunnel.com` (proxied)

**Service beheren:**
```bash
sudo systemctl status cloudflared    # status controleren
sudo systemctl restart cloudflared   # herstarten na config-wijziging
sudo systemctl stop cloudflared      # stoppen
```

**Let op:** uvicorn moet draaien op `--host 0.0.0.0` (niet `127.0.0.1`) zodat cloudflared er bij kan.

---

## Snel overzicht — alle commando's achter elkaar

```bash
cd /home/bob/waterlab/wflow_ijssel
source .venv/bin/activate

python build_staticmaps_copernicus.py   # stap 1   (~5-10 min, eenmalig)
python download_river_geom.py           # stap 1b  (~1 min, eenmalig)
python fix_staticmaps.py                # stap 1b  (~1 min, eenmalig)
python download_forcing.py              # stap 2c  (~5-30 min, CDS wachtrij)
python download_inflow.py               # stap 3   (~1 min)
julia --project=. run_ijssel.jl         # stap 4   (~5-20 min)
python export_output.py                 # stap 5   (~1 min)
python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8000  # stap 6
# Dashboard: http://127.0.0.1:8000  of  https://waterlab.felixisfelix.com
```
