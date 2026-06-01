"""Bouw staticmaps-ijssel.nc van Copernicus DEM (AWS S3) via pyflwdir.

Alternatief voor build_staticmaps.py wanneer MERIT Hydro niet beschikbaar is.
Geen registratie of licentie vereist. Download ~180 MB DEM-tegels.

Uitvoer: data/input/staticmaps-ijssel.nc en instates-ijssel.nc
"""
import io
import logging
from pathlib import Path

import numpy as np
import requests
import rasterio
from rasterio.merge import merge
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
import pyflwdir
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT  = Path(__file__).parent
INPUT = ROOT / "data" / "input"
INPUT.mkdir(parents=True, exist_ok=True)

# Modelresolutie (°) en bereik voor IJssel stroomgebied
RES          = 0.008333   # ~1 km
BBOX         = (5.0, 51.5, 7.5, 53.5)     # xmin,ymin,xmax,ymax (EPSG:4326)
OUTLET_LON   = 5.92
OUTLET_LAT   = 52.55
RIVER_UPA_KM2 = 50.0     # minimale bovenstroomse oppervlakte voor riviercel (km²)
MIN_STREAMORDER = 4      # min stroomorde voor rivier

# Copernicus DEM 90m tiles op AWS S3
COPDEM_BASE = "https://copernicus-dem-90m.s3.amazonaws.com"

# Tiles die het IJssel stroomgebied dekken (N51-53, E05-07)
TILES = [
    (51, 5), (51, 6), (51, 7),
    (52, 5), (52, 6), (52, 7),
]

# --- Uniforme bodem- en vegetatieparameters (redelijke defaults voor gematigd klimaat) ---
DEFAULTS = {
    "thetaS":         0.60,   # verzadigde vochtinhoud [-]
    "thetaR":         0.01,   # residuele vochtinhoud [-]
    "KsatVer":        50.0,   # verticale Ksat [mm/dag]
    "KsatHorFrac":    100.0,  # horizontale/verticale Ksat verhouding [-]
    "f":              3.0,    # SBM schaalparameter [-]
    "c":              10.0,   # opslagcoefficient onverzadigde zone [mm]
    "cf_soil":        0.038,  # compactiefactor [-]
    "SoilThickness":  1200.0, # totale bodemdikte [mm]
    "MaxLeakage":     0.0,    # max dieplekking [mm/dag]
    "InfiltCapSoil":  100.0,  # infiltratiecapaciteit bodem [mm/uur]
    "InfiltCapPath":  2.0,    # infiltratiecapaciteit verhard [-]
    "PathFrac":       0.05,   # verhard oppervlakfractie [-]
    "WaterFrac":      0.0,    # open waterfractie [-]
    "rootdistpar":   -500.0,  # wortelzoneparameter [-]
    "RootingDepth":   750.0,  # bewortelingsdiepte [mm]
    "Kext":           0.6,    # lichtextinctiecoefficient [-]
    "Sl":             0.003,  # specifieke bladopslag [m]
    "Swood":          0.1,    # houtopslag [m]
    "EoverR":         0.1,    # E/R verhouding [-]
    "N":              0.072,  # Manning ruwheid land [-]
    "N_River":        0.036,  # Manning ruwheid rivier [-]
    # Sneeuwparameters
    "Cfmax":          3.75,   # graaddagfactor [mm/°C/dag]
    "TT":             0.0,    # drempeltemperatuur sneeuw [°C]
    "TTI":            1.0,    # interval smeltdrempel [°C]
    "TTM":            0.0,    # smelttemperatuur [°C]
    "WHC":            0.1,    # watervasthoudcapaciteit sneeuw [-]
}

# Maandelijkse LAI-klimatologie (gematigd gemengd bos, 12 maanden, jan=idx0)
LAI_MONTHLY = [0.5, 0.6, 1.2, 2.5, 3.8, 4.5, 4.5, 4.2, 3.0, 1.8, 0.8, 0.5]


def download_tile(lat: int, lon: int) -> bytes:
    """Download een Copernicus DEM 90m tegel van AWS S3."""
    name = f"Copernicus_DSM_COG_30_N{lat:02d}_00_E{lon:03d}_00_DEM"
    url  = f"{COPDEM_BASE}/{name}/{name}.tif"
    logger.info("Downloaden %s ...", url)
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content


def load_and_merge_tiles() -> tuple[np.ndarray, rasterio.transform.Affine, dict]:
    """Download en samenvoegen van DEM-tegels."""
    datasets = []
    for lat, lon in TILES:
        data = download_tile(lat, lon)
        ds = rasterio.open(io.BytesIO(data))
        datasets.append(ds)

    mosaic, transform = merge(datasets)
    profile = datasets[0].profile.copy()
    profile.update(
        height=mosaic.shape[1],
        width=mosaic.shape[2],
        transform=transform,
    )
    for ds in datasets:
        ds.close()
    return mosaic[0].astype(np.float32), transform, profile


def resample_to_model_grid(
    dem: np.ndarray,
    src_transform: rasterio.transform.Affine,
    src_crs,
) -> tuple[np.ndarray, rasterio.transform.Affine, int, int]:
    """Hersampel DEM naar modelresolutie (~1 km)."""
    xmin, ymin, xmax, ymax = BBOX
    ncols = int(round((xmax - xmin) / RES))
    nrows = int(round((ymax - ymin) / RES))
    dst_transform = from_bounds(xmin, ymin, xmax, ymax, ncols, nrows)

    dst = np.zeros((nrows, ncols), dtype=np.float32)
    reproject(
        source=dem,
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs="EPSG:4326",
        resampling=Resampling.average,
    )
    return dst, dst_transform, nrows, ncols


def build_flow_network(
    dem: np.ndarray,
    transform: rasterio.transform.Affine,
    nrows: int,
    ncols: int,
) -> tuple:
    """Leid afvoernetwerk af met pyflwdir."""
    logger.info("Afvoerrichtingen afleiden met pyflwdir ...")
    # Stel nodata in op NaN-gebieden (zee/buiten gebied)
    dem_filled = dem.copy()
    dem_filled[dem_filled < -100] = np.nan
    dem_filled[dem_filled > 5000]  = np.nan

    flwdir = pyflwdir.from_dem(
        data=dem_filled,
        nodata=np.nan,
        latlon=True,
        transform=transform,
    )

    logger.info("Bovenstroomse oppervlakte berekenen ...")
    uparea = flwdir.upstream_area(unit="km2")

    logger.info("Stroomorde berekenen ...")
    strord = flwdir.stream_order()

    logger.info("Stroomgebied delineëren vanuit Kampen (%s, %s) ...",
                OUTLET_LON, OUTLET_LAT)
    lons = np.array([transform.c + (j + 0.5) * transform.a for j in range(ncols)])
    lats = np.array([transform.f + (i + 0.5) * transform.e for i in range(nrows)])

    # Snap uitlaat naar dichtstbijzijnde cel met grote uparea (straal 0.8°)
    dist = np.sqrt((lons[None, :] - OUTLET_LON) ** 2 + (lats[:, None] - OUTLET_LAT) ** 2)
    snap_mask = dist < 0.8
    uparea_snap = np.where(snap_mask, uparea, 0.0)
    flat_best = int(np.argmax(uparea_snap.ravel()))
    yi, xi = np.unravel_index(flat_best, uparea.shape)
    idx_outlet = yi * ncols + xi
    logger.info("Uitlaat gesnapped naar: lon=%.3f lat=%.3f uparea=%.0f km²",
                lons[xi], lats[yi], uparea[yi, xi])

    # Stroomgebied als boolean masker
    basins = flwdir.basins(idxs=np.array([idx_outlet]))
    basin_mask = (basins == 1).astype(np.float32)

    # Riviernetwerk: cellen met uparea > drempel
    river = (uparea > RIVER_UPA_KM2) & (basin_mask > 0)

    # Rivierlengte per cel (m): None → celgrootte
    rivlen = flwdir.subgrid_rivlen(
        idxs_out=None,
        mask=river.astype(bool),
    ).astype(np.float32)
    rivlen = np.where(river, np.maximum(rivlen, RES * 111000 * 0.5), 0.0)

    # Rivierhelling (m/m): DEM-gradient in stroomrichting
    elevtn_safe = np.where(np.isnan(dem_filled), 0.0, dem_filled).astype(np.float32)
    dy_gy, dy_gx = np.gradient(elevtn_safe)
    cell_size_m  = RES * 111000  # m per cel (gemiddeld voor 52°N)
    rivslp = np.sqrt(
        (dy_gy / cell_size_m) ** 2 + (dy_gx / cell_size_m) ** 2
    ).astype(np.float32)
    rivslp = np.where(river, np.maximum(rivslp, 1e-5), 0.0)

    # Landhelling (m/m)
    slope_grad  = np.gradient(elevtn_safe)
    slope_land  = np.sqrt((slope_grad[0] / cell_size_m) ** 2 + (slope_grad[1] / cell_size_m) ** 2)
    slope_land  = np.clip(slope_land, 1e-5, 1.0).astype(np.float32)

    # LDD-formaat (PCRaster): d8_to_ldd converteert
    ldd_d8 = flwdir.to_array(ftype="d8")
    ldd    = pyflwdir.d8_to_ldd(ldd_d8)
    ldd    = ldd.astype(np.float32)

    # Bankful breedte: empirische relatie W = 2 * A^0.4 (m), A in km²
    rivwth = np.where(river, 2.0 * np.maximum(uparea, 1) ** 0.4, 0.0).astype(np.float32)

    # Bankful diepte: D = 0.4 * A^0.2 (m)
    rivdepth = np.where(river, 0.4 * np.maximum(uparea, 1) ** 0.2, 0.0).astype(np.float32)

    # Bankful hoogte (RiverZ): terreinhoogte + bankful diepte
    riverz = (elevtn_safe + rivdepth).astype(np.float32)

    return (
        ldd, uparea.astype(np.float32), strord.astype(np.float32),
        basin_mask, river.astype(np.float32),
        elevtn_safe, slope_land, rivlen, rivslp, rivwth, rivdepth, riverz,
        lons, lats, xi, yi,
    )


def build_staticmaps(
    ldd, uparea, strord, basin_mask, river,
    elevtn, slope_land, rivlen, rivslp, rivwth, rivdepth, riverz,
    lons, lats, xi, yi,
    nrows, ncols,
) -> xr.Dataset:
    """Stel staticmaps.nc samen met alle variabelen die Wflow SBM nodig heeft."""
    coords = {"y": lats, "x": lons}
    shape  = (nrows, ncols)

    def field(arr, name="", units=""):
        da = xr.DataArray(arr, dims=["y", "x"], coords=coords)
        if units:
            da.attrs["units"] = units
        return da

    def uniform(val, units=""):
        return field(np.full(shape, val, dtype=np.float32), units=units)

    # LAI: 12 maanden als extra dimensie
    lai = np.stack(
        [np.full(shape, v, dtype=np.float32) for v in LAI_MONTHLY], axis=0
    )
    lai_da = xr.DataArray(
        lai, dims=["time", "y", "x"],
        coords={"time": np.arange(1, 13), "y": lats, "x": lons},
    )
    lai_da.attrs["units"] = "m2/m2"

    # Gaaugemask: Kampen (ID=1) en Westervoort (ID=2)
    gauges = np.zeros(shape, dtype=np.float32)
    gauges[yi, xi] = 1  # Kampen outlet
    wlat  = 51.97; wlon = 6.17
    wxi = int(np.argmin(np.abs(lons - wlon)))
    wyi = int(np.argmin(np.abs(lats - wlat)))
    gauges[wyi, wxi] = 2

    ds = xr.Dataset(
        {
            # Hydrografie
            "wflow_ldd":         field(ldd,                "wflow_ldd"),
            "wflow_subcatch":    field(basin_mask,         "wflow_subcatch"),
            "wflow_river":       field(river,              "wflow_river"),
            "wflow_uparea":      field(uparea,             "wflow_uparea",     "km2"),
            "wflow_dem":         field(elevtn,             "wflow_dem",        "m"),
            "wflow_riverlength": field(rivlen,             "wflow_riverlength","m"),
            "wflow_riverwidth":  field(rivwth,             "wflow_riverwidth", "m"),
            "wflow_gauges_grdc": field(gauges,             "wflow_gauges_grdc"),
            "Slope":             field(slope_land,         "Slope",            "m/m"),
            "RiverSlope":        field(rivslp,             "RiverSlope",       "m/m"),
            "RiverDepth":        field(rivdepth,           "RiverDepth",       "m"),
            "RiverZ":            field(riverz,             "RiverZ",           "m+datum"),
            # Bodemparameters
            "thetaS":            uniform(DEFAULTS["thetaS"],            "m3/m3"),
            "thetaR":            uniform(DEFAULTS["thetaR"],            "m3/m3"),
            "KsatVer":           uniform(DEFAULTS["KsatVer"],           "mm/day"),
            "KsatHorFrac":       uniform(DEFAULTS["KsatHorFrac"],       "-"),
            "f":                 uniform(DEFAULTS["f"],                  "-"),
            "c":                 uniform(DEFAULTS["c"],                  "mm"),
            "cf_soil":           uniform(DEFAULTS["cf_soil"],            "-"),
            "SoilThickness":     uniform(DEFAULTS["SoilThickness"],      "mm"),
            "MaxLeakage":        uniform(DEFAULTS["MaxLeakage"],          "mm/day"),
            "InfiltCapSoil":     uniform(DEFAULTS["InfiltCapSoil"],      "mm/hr"),
            "InfiltCapPath":     uniform(DEFAULTS["InfiltCapPath"],      "mm/hr"),
            "PathFrac":          uniform(DEFAULTS["PathFrac"],            "-"),
            "WaterFrac":         uniform(DEFAULTS["WaterFrac"],           "-"),
            "rootdistpar":       uniform(DEFAULTS["rootdistpar"],        "-"),
            "RootingDepth":      uniform(DEFAULTS["RootingDepth"],       "mm"),
            # Vegetatieparameters
            "Kext":              uniform(DEFAULTS["Kext"],               "-"),
            "Sl":                uniform(DEFAULTS["Sl"],                 "m"),
            "Swood":             uniform(DEFAULTS["Swood"],              "m"),
            "EoverR":            uniform(DEFAULTS["EoverR"],             "-"),
            "N":                 uniform(DEFAULTS["N"],                  "s/m^(1/3)"),
            "N_River":           uniform(DEFAULTS["N_River"],            "s/m^(1/3)"),
            # Sneeuw
            "Cfmax":             uniform(DEFAULTS["Cfmax"],             "mm/degC/day"),
            "TT":                uniform(DEFAULTS["TT"],                "degC"),
            "TTI":               uniform(DEFAULTS["TTI"],               "degC"),
            "TTM":               uniform(DEFAULTS["TTM"],               "degC"),
            "WHC":               uniform(DEFAULTS["WHC"],               "-"),
            # LAI (cyclic, 12 maanden)
            "LAI":               lai_da,
        },
        coords=coords,
        attrs={"crs": "EPSG:4326", "source": "Copernicus DEM 90m + pyflwdir"},
    )
    return ds


def build_instates(ds: xr.Dataset) -> xr.Dataset:
    """Maak lege beginstoestand (Wflow model begint met reinit=true)."""
    shape = (ds.dims["y"], ds.dims["x"])
    coords = {"y": ds["y"], "x": ds["x"]}
    zero = np.zeros(shape, dtype=np.float32)
    nly  = 3   # thicknesslayers=[100,300,800]

    layer_dim = np.arange(nly)
    return xr.Dataset(
        {
            "canopystorage":    xr.DataArray(zero.copy(), dims=["y","x"], coords=coords),
            "satwaterdepth":    xr.DataArray(zero.copy(), dims=["y","x"], coords=coords),
            "snow":             xr.DataArray(zero.copy(), dims=["y","x"], coords=coords),
            "snowwater":        xr.DataArray(zero.copy(), dims=["y","x"], coords=coords),
            "tsoil":            xr.DataArray(np.full(shape, 5.0, np.float32), dims=["y","x"], coords=coords),
            "ustorelayerdepth": xr.DataArray(
                np.zeros((nly, *shape), dtype=np.float32),
                dims=["layer","y","x"],
                coords={"layer": layer_dim, "y": ds["y"], "x": ds["x"]},
            ),
            "h_river":          xr.DataArray(zero.copy(), dims=["y","x"], coords=coords),
            "h_av_river":       xr.DataArray(zero.copy(), dims=["y","x"], coords=coords),
            "q_river":          xr.DataArray(zero.copy(), dims=["y","x"], coords=coords),
            "ssf":              xr.DataArray(zero.copy(), dims=["y","x"], coords=coords),
            "h_land":           xr.DataArray(zero.copy(), dims=["y","x"], coords=coords),
            "h_av_land":        xr.DataArray(zero.copy(), dims=["y","x"], coords=coords),
            "q_land":           xr.DataArray(zero.copy(), dims=["y","x"], coords=coords),
        },
        attrs={"source": "nullstatus — reinit=true in ijssel_config.toml"},
    )


def main() -> None:
    logger.info("=== build_staticmaps_copernicus.py ===")

    logger.info("Stap 1/4: DEM-tegels downloaden van AWS Copernicus ...")
    dem_raw, src_transform, src_profile = load_and_merge_tiles()
    logger.info("Samengevoegd DEM: %s, shape=%s", src_profile["crs"], dem_raw.shape)

    logger.info("Stap 2/4: Hersampelen naar %.6f° (~1 km) ...", RES)
    dem, transform, nrows, ncols = resample_to_model_grid(dem_raw, src_transform, src_profile["crs"])
    logger.info("Modelgrid: %d rijen × %d kolommen", nrows, ncols)

    logger.info("Stap 3/4: Afvoernetwerk afleiden met pyflwdir ...")
    result = build_flow_network(dem, transform, nrows, ncols)
    (ldd, uparea, strord, basin_mask, river,
     elevtn, slope_land, rivlen, rivslp, rivwth, rivdepth, riverz,
     lons, lats, xi, yi) = result
    logger.info("Stroomgebied: %d cellen, rivieren: %d cellen",
                int(basin_mask.sum()), int(river.sum()))

    logger.info("Stap 4/4: staticmaps.nc en instates.nc schrijven ...")
    ds = build_staticmaps(
        ldd, uparea, strord, basin_mask, river,
        elevtn, slope_land, rivlen, rivslp, rivwth, rivdepth, riverz,
        lons, lats, xi, yi, nrows, ncols,
    )
    out_static = INPUT / "staticmaps-ijssel.nc"
    ds.to_netcdf(str(out_static))
    logger.info("Geschreven: %s (%.1f MB)", out_static, out_static.stat().st_size / 1e6)

    instates = build_instates(ds)
    out_states = INPUT / "instates-ijssel.nc"
    instates.to_netcdf(str(out_states))
    logger.info("Geschreven: %s", out_states)
    logger.info("=== Klaar ===")


if __name__ == "__main__":
    main()
