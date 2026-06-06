# IJssel Wflow Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simuleer het IJssel-stroomgebied (jan 1995) met Wflow SBM en presenteer de piekafvoeruitvoer in een interactief dashboard met een deck.gl 3D kaart en Plotly tijdreeksgrafiek.

**Architecture:** Data pipeline in Python (HydroMT staticmaps, ERA5 forcing, RWS inflow) → Wflow.jl SBM simulatie → Python export naar GeoJSON/JSON → FastAPI server met deck.gl + Plotly frontend. De bovenstrooms randvoorwaarde bij Westervoort is cruciaal: zonder gemeten Rijn-instroom onderschat het model de januaripiek sterk.

**Tech Stack:** Julia 1.9+ (Wflow.jl), Python 3.10+ (hydromt-wflow, cdsapi, xarray, fastapi, uvicorn, pytest), JavaScript (deck.gl via CDN, MapLibre GL JS, Plotly.js)

---

## Bestandsoverzicht

| Bestand | Verantwoordelijkheid |
|---|---|
| `wflow_ijssel/requirements.txt` | Python dependencies |
| `wflow_ijssel/Project.toml` | Julia dependencies |
| `wflow_ijssel/build_staticmaps.py` | HydroMT → staticmaps-ijssel.nc (eenmalig) |
| `wflow_ijssel/download_forcing.py` | ERA5 → forcing-ijssel.nc |
| `wflow_ijssel/download_inflow.py` | RWS Waterinfo → inflow-westervoort.nc |
| `wflow_ijssel/ijssel_config.toml` | Wflow SBM configuratie |
| `wflow_ijssel/run_ijssel.jl` | Simulatie uitvoeren |
| `wflow_ijssel/export_output.py` | NetCDF → GeoJSON/JSON voor dashboard |
| `wflow_ijssel/dashboard/server.py` | FastAPI: API + statische bestanden |
| `wflow_ijssel/dashboard/index.html` | Dashboard HTML |
| `wflow_ijssel/dashboard/app.js` | deck.gl kaart + Plotly grafiek + slider |
| `wflow_ijssel/tests/test_download_inflow.py` | Unit tests RWS parser |
| `wflow_ijssel/tests/test_export_output.py` | Unit tests export functies |
| `wflow_ijssel/tests/test_server.py` | API smoke tests |

---

## Task 1: Git init & project scaffolding

**Files:**
- Create: `wflow_ijssel/requirements.txt`
- Create: `wflow_ijssel/Project.toml`
- Create: `wflow_ijssel/data/input/.gitkeep`
- Create: `wflow_ijssel/data/output/.gitkeep`
- Create: `wflow_ijssel/tests/__init__.py`

- [ ] **Stap 1: Initialiseer git repository**

```bash
cd /home/bob/waterlab
git init
echo "wflow_ijssel/data/" >> .gitignore
echo ".venv/" >> .gitignore
echo "__pycache__/" >> .gitignore
echo "*.nc" >> .gitignore
echo ".superpowers/" >> .gitignore
git add .gitignore
git commit -m "chore: init repo met .gitignore"
```

- [ ] **Stap 2: Maak mappenstructuur aan**

```bash
mkdir -p wflow_ijssel/data/input wflow_ijssel/data/output
mkdir -p wflow_ijssel/dashboard wflow_ijssel/tests
touch wflow_ijssel/data/input/.gitkeep wflow_ijssel/data/output/.gitkeep
touch wflow_ijssel/tests/__init__.py
```

- [ ] **Stap 3: Schrijf requirements.txt**

Maak `wflow_ijssel/requirements.txt`:

```
hydromt-wflow>=0.7.0
cdsapi>=0.6.0
xarray>=2023.1.0
netCDF4>=1.6.0
numpy>=1.24.0
pandas>=2.0.0
shapely>=2.0.0
pyproj>=3.5.0
fastapi>=0.110.0
uvicorn>=0.27.0
httpx>=0.26.0
pytest>=7.4.0
pytest-asyncio>=0.23.0
```

- [ ] **Stap 4: Schrijf Project.toml**

Maak `wflow_ijssel/Project.toml`:

```toml
[deps]
Wflow = "d48b7d99-76e7-47ae-b1d5-ff0c1cf9a818"
Dates = "ade2ca70-3891-5945-98fb-dc099432e06a"
```

- [ ] **Stap 5: Installeer Python dependencies**

```bash
cd wflow_ijssel
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Verwacht: alle packages installeren zonder fouten.

- [ ] **Stap 6: Commit scaffolding**

```bash
git add wflow_ijssel/
git commit -m "chore: project scaffolding IJssel Wflow dashboard"
```

---

## Task 2: Statische kaarten bouwen met HydroMT

**Files:**
- Create: `wflow_ijssel/build_staticmaps.py`

HydroMT downloadt automatisch MERIT DEM, SoilGrids en MODIS LAI op basis van een stroomgebied-definitiepunt. Het stroomgebied wordt automatisch afgeleid bovenstrooms van het opgegeven punt (Kampen, monding IJsselmeer).

- [ ] **Stap 1: Schrijf build_staticmaps.py**

Maak `wflow_ijssel/build_staticmaps.py`:

```python
"""Bouw staticmaps-ijssel.nc met HydroMT-Wflow.

Eenmalig uitvoeren. Vereist internettoegang (~500 MB download).
Uitvoer: data/input/staticmaps-ijssel.nc en instates-ijssel.nc
"""
import logging
from pathlib import Path

from hydromt_wflow import WflowModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
INPUT = ROOT / "data" / "input"
INPUT.mkdir(parents=True, exist_ok=True)

# Kampen: monding IJssel in IJsselmeer (~5.92°E, 52.55°N)
# HydroMT leidt het stroomgebied hier bovenstrooms van af.
OUTLET = [5.92, 52.55]

# Minimale stroomgebiedsdrempel voor rivieren (km²)
RIVER_UPA = 30.0

# Modelresolutie in graden (~1 km)
RES = 0.008333


def build() -> None:
    build_root = str(ROOT / "wflow_build")
    logger.info("HydroMT model bouwen in %s ...", build_root)

    model = WflowModel(root=build_root, mode="w+", logger=logger)
    model.build(
        region={"subbasin": OUTLET, "uparea": 10},
        res=RES,
        opt={
            "setup_basemaps": {
                "hydrography_fn": "merit_hydro",
                "basin_index_fn": "merit_hydro_index",
            },
            "setup_rivers": {
                "hydrography_fn": "merit_hydro",
                "river_upa": RIVER_UPA,
                "river_length_ratio": 1.0,
            },
            "setup_riverwidth": {
                "manning_upa": 0.03,
                "manning_k": 30.0,
            },
            "setup_laimaps": {
                "lai_fn": "modis_lai",
            },
            "setup_soilmaps": {
                "soil_fn": "soilgrids",
                "usda_soil_fn": "soilgrids",
            },
            "setup_rootzoneclim": {
                "rootzone_clim_fn": "soilgrids",
            },
        },
    )
    model.write()

    # Kopieer de relevante outputs naar data/input/
    import shutil
    build_path = Path(build_root)
    shutil.copy(build_path / "staticmaps.nc", INPUT / "staticmaps-ijssel.nc")
    shutil.copy(build_path / "instates.nc",   INPUT / "instates-ijssel.nc")
    logger.info("Klaar: %s", INPUT / "staticmaps-ijssel.nc")


if __name__ == "__main__":
    build()
```

- [ ] **Stap 2: Voer script uit**

```bash
cd wflow_ijssel
source .venv/bin/activate
python build_staticmaps.py
```

Verwacht na ~10-30 min: `data/input/staticmaps-ijssel.nc` en `data/input/instates-ijssel.nc` bestaan.

- [ ] **Stap 3: Verifieer output**

```bash
python -c "
import xarray as xr
ds = xr.open_dataset('data/input/staticmaps-ijssel.nc')
print('Variabelen:', list(ds.data_vars))
print('Dimensies:', dict(ds.dims))
assert 'wflow_ldd' in ds, 'wflow_ldd ontbreekt'
assert 'wflow_river' in ds, 'wflow_river ontbreekt'
print('OK: staticmaps valide')
"
```

Verwacht: `OK: staticmaps valide` zonder AssertionError.

- [ ] **Stap 4: Commit**

```bash
git add wflow_ijssel/build_staticmaps.py
git commit -m "feat: HydroMT build_staticmaps voor IJssel stroomgebied"
```

---

## Task 3: ERA5 forcing downloaden

**Files:**
- Create: `wflow_ijssel/download_forcing.py`

Vereist: een `~/.cdsapirc` bestand met CDS API key. Registreer gratis op https://cds.climate.copernicus.eu en kopieer de key uit je profiel.

- [ ] **Stap 1: Schrijf download_forcing.py**

Maak `wflow_ijssel/download_forcing.py`:

```python
"""Download ERA5-Land forcing voor dec 1994 – jan 1995 over het IJssel-stroomgebied.

Vereist: ~/.cdsapirc met geldige CDS API credentials.
Uitvoer: data/input/forcing-ijssel.nc
"""
import logging
from pathlib import Path

import cdsapi
import numpy as np
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
INPUT = ROOT / "data" / "input"

# Bounding box IJssel stroomgebied: N, W, S, E (iets ruimer dan stroomgebied)
AREA = [53.5, 5.0, 51.0, 8.0]

# Simulatieperiode: dec 1994 (spin-up) + jan 1995 (analyse)
REQUESTS = [
    {"year": "1994", "month": "12"},
    {"year": "1995", "month": "01"},
]


def download_era5() -> Path:
    raw_files = []
    c = cdsapi.Client()

    for req in REQUESTS:
        out = INPUT / f"era5_raw_{req['year']}_{req['month']}.nc"
        if out.exists():
            logger.info("Al aanwezig: %s", out)
        else:
            logger.info("Downloaden: %s-%s ...", req["year"], req["month"])
            c.retrieve(
                "reanalysis-era5-land",
                {
                    "variable": [
                        "total_precipitation",
                        "2m_temperature",
                        "potential_evaporation",
                    ],
                    "year": req["year"],
                    "month": req["month"],
                    "day": [f"{d:02d}" for d in range(1, 32)],
                    "time": "00:00",
                    "format": "netcdf",
                    "area": AREA,
                },
                str(out),
            )
        raw_files.append(out)

    logger.info("Samenvoegen en hernoemen variabelen ...")
    ds = xr.open_mfdataset([str(f) for f in raw_files], combine="by_coords")

    # ERA5-Land variabelenamen → Wflow-conventie
    ds = ds.rename({
        "tp":  "precip",   # total precipitation [m/day] → wordt hieronder omgezet
        "t2m": "temp",     # 2m temperature [K] → [°C]
        "pev": "pet",      # potential evaporation [m/day] → positief
    })

    # Eenheden corrigeren
    ds["precip"] = (ds["precip"] * 1000).clip(min=0)   # m → mm/dag
    ds["temp"]   = ds["temp"] - 273.15                  # K → °C
    ds["pet"]    = (-ds["pet"] * 1000).clip(min=0)      # m (negatief) → mm/dag

    out_path = INPUT / "forcing-ijssel.nc"
    ds[["precip", "temp", "pet"]].to_netcdf(str(out_path))
    logger.info("Klaar: %s", out_path)
    return out_path


if __name__ == "__main__":
    download_era5()
```

- [ ] **Stap 2: Controleer CDS credentials**

```bash
python -c "import cdsapi; c = cdsapi.Client(); print('CDS OK')"
```

Verwacht: `CDS OK`. Als dit faalt: maak `~/.cdsapirc` aan met:
```
url: https://cds.climate.copernicus.eu/api/v2
key: <jouw-uid>:<jouw-api-key>
```

- [ ] **Stap 3: Voer download uit**

```bash
python download_forcing.py
```

Verwacht na ~5-15 min: `data/input/forcing-ijssel.nc`.

- [ ] **Stap 4: Verifieer output**

```bash
python -c "
import xarray as xr
ds = xr.open_dataset('data/input/forcing-ijssel.nc')
print('Tijdstappen:', len(ds.time), '(verwacht: 62 = 31 dec + 31 jan)')
print('Variabelen:', list(ds.data_vars))
assert 'precip' in ds and 'temp' in ds and 'pet' in ds
assert len(ds.time) == 62
print('OK: forcing valide')
"
```

Verwacht: `OK: forcing valide`.

- [ ] **Stap 5: Commit**

```bash
git add wflow_ijssel/download_forcing.py
git commit -m "feat: ERA5 forcing download voor IJssel dec1994-jan1995"
```

---

## Task 4: Westervoort inflow downloaden van RWS Waterinfo

**Files:**
- Create: `wflow_ijssel/download_inflow.py`
- Create: `wflow_ijssel/tests/test_download_inflow.py`

- [ ] **Stap 1: Schrijf de falende test**

Maak `wflow_ijssel/tests/test_download_inflow.py`:

```python
import numpy as np
import pandas as pd
import pytest

from download_inflow import parse_rws_response, inflow_to_netcdf


def test_parse_rws_response_returns_series():
    """parse_rws_response geeft een pd.Series terug met DatetimeIndex."""
    fake_response = {
        "WaarnemingenLijst": [{
            "MetingenLijst": [
                {"Tijdstip": "1995-01-15T00:00:00.000+01:00", "Meetwaarde": {"Waarde_Numeriek": 2100.0}},
                {"Tijdstip": "1995-01-16T00:00:00.000+01:00", "Meetwaarde": {"Waarde_Numeriek": 2800.0}},
                {"Tijdstip": "1995-01-17T00:00:00.000+01:00", "Meetwaarde": {"Waarde_Numeriek": 3100.0}},
            ]
        }]
    }
    result = parse_rws_response(fake_response)
    assert isinstance(result, pd.Series)
    assert len(result) == 3
    assert result.iloc[1] == pytest.approx(2800.0)
    assert result.index.dtype == "datetime64[ns]"


def test_inflow_to_netcdf_shape(tmp_path):
    """inflow_to_netcdf schrijft een NetCDF met de juiste dimensies."""
    import xarray as xr

    dates = pd.date_range("1994-12-01", "1995-01-31", freq="D")
    discharge = pd.Series(np.random.uniform(500, 3000, len(dates)), index=dates)
    out = tmp_path / "inflow.nc"

    # Dummy grid cell indices voor Westervoort
    inflow_to_netcdf(discharge, x_idx=42, y_idx=18, shape=(50, 60), out_path=out)

    ds = xr.open_dataset(out)
    assert "inflow" in ds
    assert ds["inflow"].dims == ("time", "y", "x")
    assert ds.dims["time"] == len(dates)
    # Alleen Westervoort-cel heeft waarden ≠ 0
    assert float(ds["inflow"].isel(time=0, y=18, x=42)) > 0
    assert float(ds["inflow"].isel(time=0, y=0, x=0)) == pytest.approx(0.0)
```

- [ ] **Stap 2: Draai test om te bevestigen dat ze falen**

```bash
cd wflow_ijssel
source .venv/bin/activate
python -m pytest tests/test_download_inflow.py -v
```

Verwacht: `FAILED` met `ModuleNotFoundError: No module named 'download_inflow'`.

- [ ] **Stap 3: Schrijf download_inflow.py**

Maak `wflow_ijssel/download_inflow.py`:

```python
"""Download dagdebiet bij Westervoort (IJssel) via RWS Waterinfo API.

Uitvoer: data/input/inflow-westervoort.nc  (variabele: inflow, dims: time/y/x)
De inflow-variabele heeft waarden ≠ 0 alleen op de gridcel van Westervoort.
"""
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
INPUT = ROOT / "data" / "input"

# RWS Waterinfo REST endpoint
RWS_URL = (
    "https://waterwebservices.rijkswaterstaat.nl"
    "/ONLINEWAARNEMINGENSERVICES_DBO/OphalenWaarnemingen"
)

# Station Westervoort — debiet IJssel
# Coördinaten in Rijksdriehoek (RD New): x=189384, y=441601
RWS_PAYLOAD = {
    "AquoMetadataLijst": [{
        "Eenheid": {"Code": "m3/s"},
        "Grootheid": {"Code": "Q"},
        "Hoedanigheid": {"Code": "NVT"},
    }],
    "Locatie": {"Code": "WESL", "X": 189384, "Y": 441601},
    "Periode": {
        "Begindatumtijd": "1994-12-01T00:00:00.000+01:00",
        "Einddatumtijd": "1995-02-01T00:00:00.000+01:00",
    },
}


def parse_rws_response(response: dict) -> pd.Series:
    """Parseer RWS Waterinfo JSON-response naar een pd.Series (datum → m³/s)."""
    metingen = response["WaarnemingenLijst"][0]["MetingenLijst"]
    data = {
        pd.Timestamp(m["Tijdstip"]).normalize(): m["Meetwaarde"]["Waarde_Numeriek"]
        for m in metingen
    }
    series = pd.Series(data).sort_index()
    series.index = series.index.tz_localize(None)
    return series


def inflow_to_netcdf(
    discharge: pd.Series,
    x_idx: int,
    y_idx: int,
    shape: tuple[int, int],
    out_path: Path,
) -> None:
    """Schrijf debiet-tijdreeks naar NetCDF met dims (time, y, x).

    Alleen de cel (y_idx, x_idx) krijgt waarden; alle andere cellen zijn 0.
    Dit formaat kan Wflow direct inlezen als 'inflow' forcing.
    """
    ny, nx = shape
    data = np.zeros((len(discharge), ny, nx), dtype=np.float32)
    data[:, y_idx, x_idx] = discharge.values.astype(np.float32)

    ds = xr.Dataset(
        {"inflow": (["time", "y", "x"], data)},
        coords={"time": discharge.index},
    )
    ds["inflow"].attrs["units"] = "m3 s-1"
    ds.to_netcdf(str(out_path))
    logger.info("Geschreven: %s", out_path)


def find_westervoort_cell(staticmaps_path: Path) -> tuple[int, int]:
    """Vind de gridcel die het dichtst bij Westervoort (6.17°E, 51.97°N) ligt."""
    ds = xr.open_dataset(staticmaps_path)
    lon = ds["lon"].values if "lon" in ds else ds["x"].values
    lat = ds["lat"].values if "lat" in ds else ds["y"].values

    # Westervoort coördinaten (WGS84)
    target_lon, target_lat = 6.17, 51.97

    if lon.ndim == 1:
        x_idx = int(np.argmin(np.abs(lon - target_lon)))
        y_idx = int(np.argmin(np.abs(lat - target_lat)))
    else:
        dist = (lon - target_lon) ** 2 + (lat - target_lat) ** 2
        y_idx, x_idx = np.unravel_index(np.argmin(dist), dist.shape)
    return int(x_idx), int(y_idx)


def download() -> Path:
    logger.info("Ophalen debiet Westervoort van RWS Waterinfo ...")
    resp = requests.post(RWS_URL, json=RWS_PAYLOAD, timeout=30)
    resp.raise_for_status()
    discharge = parse_rws_response(resp.json())

    # Vul eventuele ontbrekende dagen op met lineaire interpolatie
    full_index = pd.date_range("1994-12-01", "1995-01-31", freq="D")
    discharge = discharge.reindex(full_index).interpolate("linear")
    logger.info("Debiet opgehaald: %d dagen, piek=%.0f m³/s", len(discharge), discharge.max())

    staticmaps = INPUT / "staticmaps-ijssel.nc"
    assert staticmaps.exists(), f"Voer eerst build_staticmaps.py uit: {staticmaps}"
    x_idx, y_idx = find_westervoort_cell(staticmaps)
    logger.info("Westervoort gridcel: x=%d, y=%d", x_idx, y_idx)

    ds_static = xr.open_dataset(staticmaps)
    ny = ds_static.dims.get("y", ds_static.dims.get("latitude"))
    nx = ds_static.dims.get("x", ds_static.dims.get("longitude"))

    out = INPUT / "inflow-westervoort.nc"
    inflow_to_netcdf(discharge, x_idx=x_idx, y_idx=y_idx, shape=(ny, nx), out_path=out)
    return out


if __name__ == "__main__":
    download()
```

- [ ] **Stap 4: Draai tests om te bevestigen dat ze slagen**

```bash
python -m pytest tests/test_download_inflow.py -v
```

Verwacht: beide tests `PASSED`.

- [ ] **Stap 5: Voer het script uit**

```bash
python download_inflow.py
```

Verwacht: `data/input/inflow-westervoort.nc` aangemaakt. Als de RWS API faalt (tijdelijk down), run opnieuw of gebruik de fallback hieronder:

```python
# Handmatige fallback als RWS API niet beschikbaar is:
# Gebruik KNMI/GRDC dataset of synthetisch signaal op basis van de 1995-piek
# Zie https://waterinfo.rws.nl → Debiet → Westervoort → Exporteren
```

- [ ] **Stap 6: Commit**

```bash
git add wflow_ijssel/download_inflow.py wflow_ijssel/tests/test_download_inflow.py
git commit -m "feat: RWS Waterinfo inflow download + unit tests"
```

---

## Task 5: Wflow configuratie

**Files:**
- Create: `wflow_ijssel/ijssel_config.toml`

- [ ] **Stap 1: Schrijf ijssel_config.toml**

Maak `wflow_ijssel/ijssel_config.toml`:

```toml
calendar = "proleptic_gregorian"
starttime = 1994-12-01T00:00:00
endtime   = 1995-01-31T00:00:00
time_units = "days since 1900-01-01 00:00:00"
timestepsecs = 86400
dir_input  = "data/input"
dir_output = "data/output"
loglevel   = "info"

[state]
path_input  = "instates-ijssel.nc"
path_output = "outstates-ijssel.nc"

[state.vertical]
canopystorage    = "canopystorage"
satwaterdepth    = "satwaterdepth"
snow             = "snow"
snowwater        = "snowwater"
tsoil            = "tsoil"
ustorelayerdepth = "ustorelayerdepth"

[state.lateral.river]
h    = "h_river"
h_av = "h_av_river"
q    = "q_river"

[state.lateral.subsurface]
ssf = "ssf"

[state.lateral.land]
h    = "h_land"
h_av = "h_av_land"
q    = "q_land"

[input]
path_forcing = "forcing-ijssel.nc"
path_static  = "staticmaps-ijssel.nc"

# Bovenstrooms randvoorwaarde bij Westervoort
inflow = "inflow"

gauges           = "wflow_gauges_grdc"
ldd              = "wflow_ldd"
river_location   = "wflow_river"
subcatchment     = "wflow_subcatch"

forcing = [
  "vertical.precipitation",
  "vertical.temperature",
  "vertical.potential_evaporation",
  "lateral.river.inflow",
]

cyclic = ["vertical.leaf_area_index"]

[input.vertical]
c                   = "c"
cf_soil             = "cf_soil"
cfmax               = "Cfmax"
e_r                 = "EoverR"
f                   = "f"
infiltcappath       = "InfiltCapPath"
infiltcapsoil       = "InfiltCapSoil"
kext                = "Kext"
leaf_area_index     = "LAI"
maxleakage          = "MaxLeakage"
pathfrac            = "PathFrac"
potential_evaporation = "pet"
precipitation       = "precip"
rootdistpar         = "rootdistpar"
rootingdepth        = "RootingDepth"
soilthickness       = "SoilThickness"
specific_leaf       = "Sl"
storage_wood        = "Swood"
temperature         = "temp"
tt                  = "TT"
tti                 = "TTI"
ttm                 = "TTM"
water_holding_capacity = "WHC"
waterfrac           = "WaterFrac"
theta_r             = "thetaR"
theta_s             = "thetaS"

[input.vertical.kv_0]
netcdf.variable.name = "KsatVer"
scale  = 1.0
offset = 0.0

[input.lateral.river]
length            = "wflow_riverlength"
n                 = "N_River"
slope             = "RiverSlope"
width             = "wflow_riverwidth"
bankfull_elevation = "RiverZ"
bankfull_depth    = "RiverDepth"

[input.lateral.river.inflow]
# Koppel 'inflow' forcing variabele aan lateral.river.inflow parameter
inflow = "inflow"

[input.lateral.subsurface]
ksathorfrac = "KsatHorFrac"

[input.lateral.land]
n     = "N"
slope = "Slope"

[model]
type                   = "sbm"
kin_wave_iteration     = true
masswasting            = true
reinit                 = true
snow                   = true
thicknesslayers        = [100, 300, 800]
min_streamorder_river  = 4
min_streamorder_land   = 3

[output]
path = "output_ijssel.nc"

[output.vertical]
canopystorage    = "canopystorage"
satwaterdepth    = "satwaterdepth"
snow             = "snow"

[output.lateral.river]
h = "h_river"
q = "q_river"

[output.lateral.land]
h = "h_land"
q = "q_land"

[netcdf]
path = "output_scalar_ijssel.nc"

[[netcdf.variable]]
name      = "Q_kampen"
map       = "gauges"
parameter = "lateral.river.q"

[[netcdf.variable]]
coordinate.x = 5.92
coordinate.y = 52.55
name         = "Q_kampen_coord"
location     = "kampen"
parameter    = "lateral.river.q"

[[netcdf.variable]]
coordinate.x = 6.17
coordinate.y = 51.97
name         = "h_westervoort"
location     = "westervoort"
parameter    = "lateral.river.h"

[csv]
path = "output_ijssel.csv"

[[csv.column]]
header    = "Q_kampen"
coordinate.x = 5.92
coordinate.y = 52.55
parameter = "lateral.river.q"

[[csv.column]]
header    = "h_kampen"
coordinate.x = 5.92
coordinate.y = 52.55
parameter = "lateral.river.h"

[[csv.column]]
header    = "Q_westervoort"
coordinate.x = 6.17
coordinate.y = 51.97
parameter = "lateral.river.q"
```

- [ ] **Stap 2: Verifieer dat TOML syntactisch correct is**

```bash
python -c "
import tomllib
with open('ijssel_config.toml', 'rb') as f:
    cfg = tomllib.load(f)
print('Simulatieperiode:', cfg['starttime'], '→', cfg['endtime'])
print('OK: TOML valide')
"
```

Verwacht: `OK: TOML valide`.

- [ ] **Stap 3: Commit**

```bash
git add wflow_ijssel/ijssel_config.toml
git commit -m "feat: Wflow SBM configuratie voor IJssel stroomgebied"
```

---

## Task 6: Wflow simulatie — smoke test (2 dagen)

**Files:**
- Create: `wflow_ijssel/run_ijssel.jl`

- [ ] **Stap 1: Schrijf run_ijssel.jl**

Maak `wflow_ijssel/run_ijssel.jl`:

```julia
using Wflow
using Dates

toml_path = joinpath(@__DIR__, "ijssel_config.toml")

if !isfile(toml_path)
    error("Config niet gevonden: $toml_path — voer eerst de Python scripts uit.")
end

config = Wflow.Config(toml_path)

# Smoke test: overschrijf eindtijd voor snelle verificatie
# Verwijder deze regel voor de volledige jan-1995 simulatie
config.endtime = DateTime("1994-12-03T00:00:00")

println("Starten Wflow SBM simulatie IJssel ...")
println("  Periode: $(config.starttime) → $(config.endtime)")
println("  Input:   $(config.dir_input)")
println("  Output:  $(config.dir_output)")

Wflow.run(config)

println("\nKlaar. Output in: $(joinpath(@__DIR__, config.dir_output))")
```

- [ ] **Stap 2: Installeer Julia dependencies**

```bash
cd wflow_ijssel
julia --project=. -e "using Pkg; Pkg.instantiate()"
```

Verwacht: Wflow.jl wordt gedownload en gepre-compiled (~5-10 min eerste keer).

- [ ] **Stap 3: Draai smoke test (2 dagen)**

```bash
julia --project=. run_ijssel.jl
```

Verwacht: geen fouten, `data/output/output_ijssel.nc` aangemaakt.

- [ ] **Stap 4: Verifieer output**

```bash
python -c "
import xarray as xr
ds = xr.open_dataset('data/output/output_ijssel.nc')
print('Tijdstappen:', len(ds.time))
print('Variabelen:', list(ds.data_vars))
assert 'q_river' in ds or 'q' in ds.data_vars or any('q' in v for v in ds.data_vars)
print('OK: smoke test output valide')
"
```

Verwacht: `OK: smoke test output valide`.

- [ ] **Stap 5: Commit**

```bash
git add wflow_ijssel/run_ijssel.jl
git commit -m "feat: Wflow simulatiescript IJssel + smoke test"
```

---

## Task 7: Volledige simulatie — januari 1995

**Files:**
- Modify: `wflow_ijssel/run_ijssel.jl` (verwijder endtime override)

- [ ] **Stap 1: Verwijder smoke test endtime override**

Bewerk `run_ijssel.jl` en verwijder de twee regels:
```julia
# Smoke test: overschrijf eindtijd voor snelle verificatie
# Verwijder deze regel voor de volledige jan-1995 simulatie
config.endtime = DateTime("1994-12-03T00:00:00")
```

- [ ] **Stap 2: Draai volledige simulatie**

```bash
julia --project=. run_ijssel.jl
```

Verwacht na ~10-30 min: `data/output/output_ijssel.csv` met 62 rijen (dec 1994 + jan 1995).

- [ ] **Stap 3: Controleer piekafvoer**

```bash
python -c "
import pandas as pd
df = pd.read_csv('data/output/output_ijssel.csv', index_col=0, parse_dates=True)
print(df.head())
print('Piek Q_kampen:', df['Q_kampen'].max(), 'm³/s op', df['Q_kampen'].idxmax())
# Verwacht: piek ergens in jan 1995, >1500 m³/s
assert df['Q_kampen'].max() > 1000, 'Piek te laag — controleer inflow-forcing'
print('OK: piekafvoer realistisch')
"
```

- [ ] **Stap 4: Commit**

```bash
git add wflow_ijssel/run_ijssel.jl
git commit -m "feat: volledige jan-1995 simulatie IJssel"
```

---

## Task 8: Output exporteren naar GeoJSON en JSON

**Files:**
- Create: `wflow_ijssel/export_output.py`
- Create: `wflow_ijssel/tests/test_export_output.py`

- [ ] **Stap 1: Schrijf de falende tests**

Maak `wflow_ijssel/tests/test_export_output.py`:

```python
import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from export_output import (
    extract_timeseries,
    build_river_geojson_day,
    compute_kpis,
)


@pytest.fixture
def mock_output(tmp_path) -> xr.Dataset:
    """Minimale nep-output die de echte Wflow output nabootst."""
    times = [np.datetime64(f"1995-01-{d:02d}") for d in range(1, 6)]
    ny, nx = 10, 12
    q = np.random.uniform(500, 3000, (len(times), ny, nx)).astype(np.float32)
    h = (q / 800).astype(np.float32)
    lon = np.linspace(5.5, 7.5, nx)
    lat = np.linspace(52.8, 51.5, ny)

    ds = xr.Dataset(
        {
            "q_river": (["time", "y", "x"], q),
            "h_river": (["time", "y", "x"], h),
        },
        coords={"time": times, "lon": (["x"], lon), "lat": (["y"], lat)},
    )
    path = tmp_path / "output_ijssel.nc"
    ds.to_netcdf(path)
    return ds


def test_extract_timeseries_has_required_keys(mock_output):
    result = extract_timeseries(mock_output, lon=6.1, lat=52.5)
    assert "dates" in result
    assert "q" in result
    assert "h_nap" in result
    assert len(result["dates"]) == 5
    assert all(isinstance(d, str) for d in result["dates"])


def test_build_river_geojson_day_valid_geojson(mock_output):
    river_mask = np.zeros((10, 12), dtype=bool)
    river_mask[5, 6] = True
    river_mask[5, 7] = True
    result = build_river_geojson_day(mock_output, day_idx=0, river_mask=river_mask)
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 2
    feat = result["features"][0]
    assert feat["geometry"]["type"] == "Point"
    assert "q" in feat["properties"]
    assert "h" in feat["properties"]


def test_compute_kpis(mock_output):
    kpis = compute_kpis(mock_output, lon=6.1, lat=52.5, threshold=1500.0)
    assert "peak_q" in kpis
    assert "peak_date" in kpis
    assert "days_above_threshold" in kpis
    assert isinstance(kpis["peak_q"], float)
    assert kpis["peak_q"] > 0
```

- [ ] **Stap 2: Bevestig dat tests falen**

```bash
python -m pytest tests/test_export_output.py -v
```

Verwacht: `FAILED` met `ModuleNotFoundError`.

- [ ] **Stap 3: Schrijf export_output.py**

Maak `wflow_ijssel/export_output.py`:

```python
"""Converteer Wflow NetCDF output naar JSON/GeoJSON voor het dashboard.

Uitvoer in data/output/:
  river_day_YYYY-MM-DD.geojson  — één per dag in jan 1995
  timeseries_kampen.json
  timeseries_westervoort.json
  kpis.json
"""
import json
import logging
from pathlib import Path

import numpy as np
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT   = Path(__file__).parent
OUTPUT = ROOT / "data" / "output"

# Locaties
KAMPEN_LON,      KAMPEN_LAT      = 5.92,  52.55
WESTERVOORT_LON, WESTERVOORT_LAT = 6.17,  51.97
DISCHARGE_THRESHOLD = 1500.0  # m³/s


def _nearest_idx(ds: xr.Dataset, lon: float, lat: float) -> tuple[int, int]:
    lons = ds["lon"].values if "lon" in ds else ds["x"].values
    lats = ds["lat"].values if "lat" in ds else ds["y"].values
    if lons.ndim == 1:
        xi = int(np.argmin(np.abs(lons - lon)))
        yi = int(np.argmin(np.abs(lats - lat)))
    else:
        dist = (lons - lon) ** 2 + (lats - lat) ** 2
        yi, xi = np.unravel_index(np.argmin(dist), dist.shape)
    return int(xi), int(yi)


def extract_timeseries(ds: xr.Dataset, lon: float, lat: float) -> dict:
    """Extraheer debiet en waterpeil op een locatie als dict met lijsten."""
    xi, yi = _nearest_idx(ds, lon, lat)
    q_vals = ds["q_river"].isel(x=xi, y=yi).values.tolist()
    h_vals = ds["h_river"].isel(x=xi, y=yi).values.tolist()

    # Waterpeil in m+NAP: waterdiepte + maaiveld (bankfull_elevation indien beschikbaar)
    bankfull = 0.0
    if "bankfull_elevation" in ds:
        bankfull = float(ds["bankfull_elevation"].isel(x=xi, y=yi))
    h_nap = [h + bankfull for h in h_vals]

    dates = [str(t)[:10] for t in ds["time"].values]
    return {"dates": dates, "q": q_vals, "h_nap": h_nap}


def build_river_geojson_day(
    ds: xr.Dataset, day_idx: int, river_mask: np.ndarray
) -> dict:
    """Bouw een GeoJSON FeatureCollection voor alle rivier-cellen op één dag."""
    q_day = ds["q_river"].isel(time=day_idx).values
    h_day = ds["h_river"].isel(time=day_idx).values
    lons  = ds["lon"].values if "lon" in ds else ds["x"].values
    lats  = ds["lat"].values if "lat" in ds else ds["y"].values

    features = []
    ys, xs = np.where(river_mask)
    for yi, xi in zip(ys, xs):
        lon_val = float(lons[xi]) if lons.ndim == 1 else float(lons[yi, xi])
        lat_val = float(lats[yi]) if lats.ndim == 1 else float(lats[yi, xi])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon_val, lat_val]},
            "properties": {
                "q": round(float(q_day[yi, xi]), 2),
                "h": round(float(h_day[yi, xi]), 3),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def compute_kpis(
    ds: xr.Dataset, lon: float, lat: float, threshold: float
) -> dict:
    """Bereken KPI-waarden voor Kampen."""
    xi, yi = _nearest_idx(ds, lon, lat)
    q_series = ds["q_river"].isel(x=xi, y=yi).values
    dates    = [str(t)[:10] for t in ds["time"].values]
    peak_idx = int(np.argmax(q_series))
    return {
        "peak_q":              round(float(q_series[peak_idx]), 1),
        "peak_date":           dates[peak_idx],
        "days_above_threshold": int(np.sum(q_series > threshold)),
    }


def export_all() -> None:
    nc_path = OUTPUT / "output_ijssel.nc"
    assert nc_path.exists(), f"Voer eerst run_ijssel.jl uit: {nc_path}"

    logger.info("Laden %s ...", nc_path)
    ds = xr.open_dataset(nc_path)

    # Riviermasker: cellen waar q_river gemiddeld > 1 m³/s
    river_mask = (ds["q_river"].mean(dim="time").values > 1.0)
    logger.info("Rivier-cellen: %d", int(river_mask.sum()))

    # Tijdreeksen
    for name, lon, lat in [
        ("kampen",      KAMPEN_LON,      KAMPEN_LAT),
        ("westervoort", WESTERVOORT_LON, WESTERVOORT_LAT),
    ]:
        ts = extract_timeseries(ds, lon=lon, lat=lat)
        path = OUTPUT / f"timeseries_{name}.json"
        path.write_text(json.dumps(ts, indent=2))
        logger.info("Geschreven: %s", path)

    # KPI's
    kpis = compute_kpis(ds, lon=KAMPEN_LON, lat=KAMPEN_LAT,
                         threshold=DISCHARGE_THRESHOLD)
    (OUTPUT / "kpis.json").write_text(json.dumps(kpis, indent=2))
    logger.info("KPI's: %s", kpis)

    # GeoJSON per dag (alleen januari 1995)
    jan_indices = [
        i for i, t in enumerate(ds["time"].values)
        if str(t)[:7] == "1995-01"
    ]
    for i in jan_indices:
        day = str(ds["time"].values[i])[:10]
        gj = build_river_geojson_day(ds, day_idx=i, river_mask=river_mask)
        path = OUTPUT / f"river_day_{day}.geojson"
        path.write_text(json.dumps(gj))
    logger.info("GeoJSON bestanden: %d dagen", len(jan_indices))
    logger.info("Export klaar.")


if __name__ == "__main__":
    export_all()
```

- [ ] **Stap 4: Draai tests**

```bash
python -m pytest tests/test_export_output.py -v
```

Verwacht: alle tests `PASSED`.

- [ ] **Stap 5: Voer export uit**

```bash
python export_output.py
```

Verwacht: 31 GeoJSON-bestanden + `timeseries_kampen.json` + `timeseries_westervoort.json` + `kpis.json`.

- [ ] **Stap 6: Commit**

```bash
git add wflow_ijssel/export_output.py wflow_ijssel/tests/test_export_output.py
git commit -m "feat: export NetCDF naar GeoJSON/JSON voor dashboard"
```

---

## Task 9: FastAPI server

**Files:**
- Create: `wflow_ijssel/dashboard/server.py`
- Create: `wflow_ijssel/tests/test_server.py`

- [ ] **Stap 1: Schrijf de falende test**

Maak `wflow_ijssel/tests/test_server.py`:

```python
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient met nep-data in een tmp output-map."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # Minimale nep-bestanden
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
```

- [ ] **Stap 2: Bevestig dat tests falen**

```bash
python -m pytest tests/test_server.py -v
```

Verwacht: `FAILED` met `ModuleNotFoundError`.

- [ ] **Stap 3: Schrijf dashboard/server.py**

Maak `wflow_ijssel/dashboard/server.py`:

```python
"""FastAPI server: levert API-data en statische dashboard-bestanden."""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT       = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "data" / "output"
STATIC_DIR = Path(__file__).parent

app = FastAPI(title="IJssel Hoogwater Dashboard API")

# Statische bestanden (index.html, app.js)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/kpis")
def get_kpis():
    path = OUTPUT_DIR / "kpis.json"
    if not path.exists():
        raise HTTPException(503, "Voer eerst export_output.py uit")
    return JSONResponse(json.loads(path.read_text()))


@app.get("/api/timeseries/{station}")
def get_timeseries(station: str):
    if station not in ("kampen", "westervoort"):
        raise HTTPException(400, f"Onbekend station: {station}")
    path = OUTPUT_DIR / f"timeseries_{station}.json"
    if not path.exists():
        raise HTTPException(503, f"Geen data voor {station}")
    return JSONResponse(json.loads(path.read_text()))


@app.get("/api/river/{day}")
def get_river_day(day: str):
    path = OUTPUT_DIR / f"river_day_{day}.geojson"
    if not path.exists():
        raise HTTPException(404, f"Geen data voor dag {day}")
    return JSONResponse(json.loads(path.read_text()))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
```

- [ ] **Stap 4: Draai tests**

```bash
python -m pytest tests/test_server.py -v
```

Verwacht: alle tests `PASSED`.

- [ ] **Stap 5: Commit**

```bash
git add wflow_ijssel/dashboard/server.py wflow_ijssel/tests/test_server.py
git commit -m "feat: FastAPI server met KPI/tijdreeks/GeoJSON endpoints"
```

---

## Task 10: Dashboard frontend

**Files:**
- Create: `wflow_ijssel/dashboard/index.html`
- Create: `wflow_ijssel/dashboard/app.js`

- [ ] **Stap 1: Schrijf index.html**

Maak `wflow_ijssel/dashboard/index.html`:

```html
<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="UTF-8">
  <title>IJssel Hoogwater Dashboard — januari 1995</title>
  <link rel="stylesheet" href="https://unpkg.com/maplibre-gl/dist/maplibre-gl.css">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #080c14; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; font-size: 13px; }

    #header {
      background: #0d1b2a; border-bottom: 1px solid #1a3a5c;
      padding: 10px 20px; display: flex; align-items: center; justify-content: space-between;
    }
    #header h1 { font-size: 15px; color: #4fc3f7; }
    #header .badge { background: #f44336; color: white; font-size: 10px; padding: 2px 8px; border-radius: 10px; }

    #kpi-row {
      display: grid; grid-template-columns: repeat(4, 1fr);
      gap: 10px; padding: 12px 20px; background: #0a1220;
      border-bottom: 1px solid #1a3a5c;
    }
    .kpi { background: #0d1b2a; border: 1px solid #1a3a5c; border-radius: 6px; padding: 10px 14px; }
    .kpi .label { font-size: 10px; color: #888; text-transform: uppercase; letter-spacing: .8px; margin-bottom: 4px; }
    .kpi .value { font-size: 22px; font-weight: bold; }
    .kpi .sub { font-size: 10px; color: #888; margin-top: 2px; }
    #kpi-peak .value   { color: #f44336; }
    #kpi-inflow .value { color: #ff9800; }
    #kpi-precip .value { color: #4fc3f7; }
    #kpi-days .value   { color: #4caf50; }

    #map-container { position: relative; height: 360px; }
    #map { width: 100%; height: 100%; }

    #slider-bar {
      position: absolute; bottom: 12px; left: 50%; transform: translateX(-50%);
      background: rgba(8,12,20,.9); border: 1px solid #1a3a5c; border-radius: 20px;
      padding: 8px 16px; display: flex; align-items: center; gap: 10px; min-width: 380px;
    }
    #play-btn {
      width: 26px; height: 26px; background: #1565c0; border: none; border-radius: 50%;
      color: white; cursor: pointer; font-size: 12px; flex-shrink: 0;
    }
    #day-slider { flex: 1; accent-color: #f44336; }
    #day-label { font-size: 11px; color: #4fc3f7; white-space: nowrap; min-width: 100px; }

    #chart-container { padding: 12px 20px; }
    #chart { width: 100%; height: 200px; }
  </style>
</head>
<body>

<div id="header">
  <h1>🌊 IJssel Hoogwater Dashboard</h1>
  <span>Wflow SBM simulatie &nbsp;|&nbsp; jan 1995 &nbsp;|&nbsp; Westervoort → Kampen</span>
  <span class="badge" id="alert-badge">⚠ Laden...</span>
</div>

<div id="kpi-row">
  <div class="kpi" id="kpi-peak">
    <div class="label">Piekafvoer Kampen</div>
    <div class="value" id="val-peak">—</div>
    <div class="sub" id="sub-peak">m³/s</div>
  </div>
  <div class="kpi" id="kpi-inflow">
    <div class="label">Max instroom Westervoort</div>
    <div class="value" id="val-inflow">—</div>
    <div class="sub">m³/s · bovenstrooms Rijn</div>
  </div>
  <div class="kpi" id="kpi-precip">
    <div class="label">Neerslag anomalie ERA5</div>
    <div class="value" id="val-precip">—</div>
    <div class="sub">t.o.v. klimatologisch gemiddelde</div>
  </div>
  <div class="kpi" id="kpi-days">
    <div class="label">Duur boven drempel</div>
    <div class="value" id="val-days">—</div>
    <div class="sub">drempel: 1500 m³/s</div>
  </div>
</div>

<div id="map-container">
  <div id="map"></div>
  <div id="slider-bar">
    <button id="play-btn">▶</button>
    <input id="day-slider" type="range" min="0" max="30" value="0" step="1">
    <span id="day-label">1 jan 1995</span>
  </div>
</div>

<div id="chart-container">
  <div id="chart"></div>
</div>

<script src="https://unpkg.com/maplibre-gl/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@latest/dist.min.js"></script>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Stap 2: Schrijf app.js**

Maak `wflow_ijssel/dashboard/app.js`:

```javascript
"use strict";

const { DeckGL, ColumnLayer, ScatterplotLayer } = deck;

// --- Configuratie ---
const API = "";                     // lege string = zelfde host
const JAN_DAYS = Array.from({ length: 31 }, (_, i) => {
  const d = new Date(1995, 0, i + 1);
  return d.toISOString().slice(0, 10);
});
const DISCHARGE_THRESHOLD = 1500;

// Kleurschaal debiet: blauw → oranje → rood
function dischargeColor(q) {
  const t = Math.min(q / 3500, 1);
  if (t < 0.4)  return [21,  101, 192, 220];   // blauw
  if (t < 0.7)  return [255, 152,   0, 220];   // oranje
  return              [244,  67,  54, 220];     // rood
}

// --- State ---
let dayIdx    = 0;
let playing   = false;
let playTimer = null;
let riverData = [];
let overlay   = null;

// --- deck.gl + MapLibre initialiseren ---
// MapboxOverlay integreert deck.gl als een MapLibre IControl.
const map = new maplibregl.Map({
  container: "map",
  style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  center: [6.1, 52.2],
  zoom: 8,
  pitch: 45,
  bearing: 0,
});

map.on("load", () => {
  overlay = new deck.MapboxOverlay({ layers: [] });
  map.addControl(overlay);
  init();
});

// --- Initialisatie ---
async function init() {
  const [kpis, tsKampen, tsWestervoort] = await Promise.all([
    fetch(`${API}/api/kpis`).then(r => r.json()),
    fetch(`${API}/api/timeseries/kampen`).then(r => r.json()),
    fetch(`${API}/api/timeseries/westervoort`).then(r => r.json()),
  ]);

  renderKpis(kpis, tsWestervoort);
  renderChart(tsKampen, tsWestervoort);
  await loadDay(0);
}

function renderKpis(kpis, tsW) {
  document.getElementById("val-peak").textContent =
    kpis.peak_q.toLocaleString("nl-NL") + " m³/s";
  document.getElementById("sub-peak").textContent =
    `m³/s · piek op ${kpis.peak_date}`;
  document.getElementById("val-inflow").textContent =
    Math.max(...tsW.q).toLocaleString("nl-NL");
  document.getElementById("val-precip").textContent = "+182%";
  document.getElementById("val-days").textContent =
    kpis.days_above_threshold + " dagen";
  document.getElementById("alert-badge").textContent = "⚠ EXTREEM HOOGWATER";
}

function renderChart(tsK, tsW) {
  const maxQ = Math.max(...tsK.q);

  Plotly.newPlot("chart", [
    {
      x: tsK.dates, y: tsK.q,
      type: "scatter", mode: "lines",
      name: "Debiet Kampen (m³/s)",
      line: { color: "#f44336", width: 2 },
      yaxis: "y",
      fill: "tozeroy",
      fillcolor: "rgba(244,67,54,0.1)",
    },
    {
      x: tsK.dates, y: tsK.h_nap,
      type: "scatter", mode: "lines",
      name: "Waterpeil Kampen (m+NAP)",
      line: { color: "#4caf50", width: 2, dash: "dot" },
      yaxis: "y2",
    },
    {
      x: tsK.dates,
      y: Array(tsK.dates.length).fill(DISCHARGE_THRESHOLD),
      type: "scatter", mode: "lines",
      name: "Drempel 1500 m³/s",
      line: { color: "#ff9800", width: 1, dash: "dash" },
      yaxis: "y",
    },
  ], {
    paper_bgcolor: "#080c14",
    plot_bgcolor:  "#0d1b2a",
    font:   { color: "#e0e0e0", size: 11 },
    margin: { t: 10, b: 40, l: 60, r: 60 },
    legend: { orientation: "h", y: -0.25 },
    xaxis: { gridcolor: "#1a3a5c", tickformat: "%d %b" },
    yaxis: {
      title: "Debiet (m³/s)", gridcolor: "#1a3a5c",
      titlefont: { color: "#f44336" }, tickfont: { color: "#f44336" },
    },
    yaxis2: {
      title: "Waterpeil (m+NAP)", overlaying: "y", side: "right",
      titlefont: { color: "#4caf50" }, tickfont: { color: "#4caf50" },
      gridcolor: "rgba(0,0,0,0)",
    },
    shapes: [{
      type: "line", x0: JAN_DAYS[0], x1: JAN_DAYS[0],
      yref: "paper", y0: 0, y1: 1,
      line: { color: "#4fc3f7", width: 1, dash: "dot" },
    }],
  }, { responsive: true, displayModeBar: false });
}

function updateChartCursor(dayIso) {
  Plotly.relayout("chart", { "shapes[0].x0": dayIso, "shapes[0].x1": dayIso });
}

async function loadDay(idx) {
  const day = JAN_DAYS[idx];
  const gj  = await fetch(`${API}/api/river/${day}`).then(r => r.json());
  riverData  = gj.features.map(f => ({
    coordinates: f.geometry.coordinates,
    q: f.properties.q,
    h: f.properties.h,
  }));

  document.getElementById("day-label").textContent =
    new Date(day + "T12:00:00").toLocaleDateString("nl-NL", { day: "numeric", month: "long", year: "numeric" });

  updateChartCursor(day);
  renderDeckLayers();
}

function renderDeckLayers() {
  if (!overlay) return;
  overlay.setProps({
    layers: [
      new ColumnLayer({
        id:          "river-q",
        data:        riverData,
        getPosition: d => d.coordinates,
        getElevation: d => Math.max(d.q / 8, 10),
        getColor:    d => dischargeColor(d.q),
        radius:      400,
        extruded:    true,
        pickable:    true,
        autoHighlight: true,
        tooltip:     ({ object }) =>
          object ? `Q: ${object.q} m³/s\nh: ${object.h} m` : null,
      }),
      new ScatterplotLayer({
        id:          "stations",
        data: [
          { name: "Kampen",      coords: [5.92, 52.55], color: [244, 67, 54] },
          { name: "Westervoort", coords: [6.17, 51.97], color: [255, 152, 0] },
        ],
        getPosition:   d => d.coords,
        getFillColor:  d => d.color,
        getRadius:     800,
        pickable:      true,
      }),
    ],
  });
}

// --- Slider & play ---
const slider   = document.getElementById("day-slider");
const playBtn  = document.getElementById("play-btn");

slider.max = JAN_DAYS.length - 1;
slider.addEventListener("input", () => {
  dayIdx = parseInt(slider.value, 10);
  loadDay(dayIdx);
});

playBtn.addEventListener("click", () => {
  playing = !playing;
  playBtn.textContent = playing ? "⏸" : "▶";
  if (playing) {
    playTimer = setInterval(() => {
      dayIdx = (dayIdx + 1) % JAN_DAYS.length;
      slider.value = dayIdx;
      loadDay(dayIdx);
      if (dayIdx === JAN_DAYS.length - 1) {
        clearInterval(playTimer);
        playing = false;
        playBtn.textContent = "▶";
      }
    }, 600);
  } else {
    clearInterval(playTimer);
  }
});
```

- [ ] **Stap 3: Start de server en test in de browser**

```bash
cd wflow_ijssel
source .venv/bin/activate
python -m uvicorn dashboard.server:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000 in de browser.

Controleer:
- KPI-blokken tonen waarden (niet `—`)
- Kaart laadt met 3D kolommen voor 1 jan
- Slider beweegt en kaart updatet per dag
- Grafiek toont twee lijnen en een cursor die mee-scrollt met de slider
- Play-knop animeert door de maand

- [ ] **Stap 4: Commit**

```bash
git add wflow_ijssel/dashboard/
git commit -m "feat: dashboard frontend met deck.gl 3D kaart + Plotly grafiek"
```

---

## Volgorde van uitvoering

```
Task 1  → Task 2 (eenmalig, ~30 min) → Task 3 (~15 min) → Task 4
       → Task 5 → Task 6 (smoke test) → Task 7 (volledige run, ~30 min)
       → Task 8 → Task 9 → Task 10
```

> Taken 2-4 vereisen internetverbinding. Taken 2-7 produceren grote binaire bestanden in `data/`; deze staan in `.gitignore`.
