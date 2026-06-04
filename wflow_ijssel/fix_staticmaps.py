"""Correct wflow_ldd routing voor de Geldersche IJssel Zwolle→Kampen bocht.

Het D8-MERIT-raster stuurde de IJssel ten onrechte NE/N na Zwolle.
Dit script burned de correcte PDOK-centerline in wflow_ldd en wflow_river.

Uitvoer: data/input/staticmaps-ijssel.nc (overschreven, backup al aanwezig als .bak)
"""
import logging
import shutil
from pathlib import Path

import numpy as np
import xarray as xr
import geopandas as gpd
from shapely.ops import unary_union, linemerge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT  = Path(__file__).parent
NC_IN = ROOT / "data" / "input" / "staticmaps-ijssel.nc"
GPKG  = ROOT / "data" / "input" / "river_geom_ijssel.gpkg"

# PCRaster LDD numpad (y-as dalend: yi-1 = meer noord)
# 7=NW 8=N 9=NE / 4=W 5=pit 6=E / 1=SW 2=S 3=SE
LDD_OF = {
    (-1, -1): 7, (-1,  0): 8, (-1, +1): 9,
    ( 0, -1): 4, ( 0,  0): 5, ( 0, +1): 6,
    (+1, -1): 1, (+1,  0): 2, (+1, +1): 3,
}
LDD_NAME = {7:'NW',8:'N',9:'NE',4:'W',5:'pit',6:'E',1:'SW',2:'S',3:'SE'}


def snap(lon: float, lat: float, x_vals, y_vals) -> tuple[int, int]:
    xi = int(np.argmin(np.abs(x_vals - lon)))
    yi = int(np.argmin(np.abs(y_vals - lat)))
    return yi, xi


def ldd_direction(yi: int, xi: int, yi_ds: int, xi_ds: int) -> int:
    dyi = max(-1, min(1, yi_ds - yi))
    dxi = max(-1, min(1, xi_ds - xi))
    return LDD_OF.get((dyi, dxi), 5)


def main() -> None:
    assert NC_IN.exists(), f"Niet gevonden: {NC_IN}"
    assert GPKG.exists(),  f"Niet gevonden: {GPKG}"

    ds      = xr.open_dataset(NC_IN)
    ldd     = ds["wflow_ldd"].values.copy()      # (y, x)
    river   = ds["wflow_river"].values.copy()    # (y, x)
    subcatch = ds["wflow_subcatch"].values.copy() # (y, x)
    y_vals  = ds.y.values   # descending N→S
    x_vals  = ds.x.values   # ascending  W→E
    ds.close()

    # ── PDOK centerline → modelcellen ────────────────────────────────────────

    gdf    = gpd.read_file(GPKG)
    ijssel = gdf[gdf["naam"].str.contains("Geldersche IJssel", na=False)]
    merged = linemerge(unary_union(ijssel.geometry))
    coords = list(merged.coords)  # (lon, lat)

    # Upstream→downstream volgorde (S→N, stijgende lat)
    if coords[0][1] > coords[-1][1]:
        coords = list(reversed(coords))

    # Snappen: alleen Zwolle→Kampen segment (lat 52.43–52.62°N)
    LAT_S, LAT_N = 52.43, 52.62

    snapped: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for lon_v, lat_v in coords:
        if not (LAT_S <= lat_v <= LAT_N):
            continue
        cell = snap(lon_v, lat_v, x_vals, y_vals)
        if cell not in seen:
            snapped.append(cell)
            seen.add(cell)

    # Zoek het snapped-cel op dezelfde lat als de junctie (52.4708°N)
    # = het eerste snapped-punt noordelijk van lat 52.46°N
    JCT_LAT = 52.4708
    JCT_LON = 6.1708   # bestaande model-junctiecel (q springt hier naar ~850 m³/s)
    yi_jct, xi_jct = snap(JCT_LON, JCT_LAT, x_vals, y_vals)

    # Zoek het dichtstbijzijnde snapped-punt op ~dezelfde lat
    pdok_start_idx = 0
    min_lat_diff = 999.0
    for i, (yi_p, xi_p) in enumerate(snapped):
        diff = abs(y_vals[yi_p] - JCT_LAT)
        if diff < min_lat_diff:
            min_lat_diff = diff
            pdok_start_idx = i

    yi_bridge_end, xi_bridge_end = snapped[pdok_start_idx]
    logger.info("Junctiecel: lat=%.4f, lon=%.4f → ldd wordt W",
                y_vals[yi_jct], x_vals[xi_jct])
    logger.info("PDOK-startpunt: idx=%d, lat=%.4f, lon=%.4f",
                pdok_start_idx,
                y_vals[yi_bridge_end], x_vals[xi_bridge_end])

    # ── brugcellen (horizontaal westwaarts op junctie-lat) ────────────────────

    bridge: list[tuple[int, int]] = []
    if xi_jct > xi_bridge_end:
        for xi_b in range(xi_jct, xi_bridge_end - 1, -1):
            cell = (yi_jct, xi_b)
            if cell not in seen:
                bridge.append(cell)
                seen.add(cell)
    elif xi_jct < xi_bridge_end:
        for xi_b in range(xi_jct, xi_bridge_end + 1):
            cell = (yi_jct, xi_b)
            if cell not in seen:
                bridge.append(cell)
                seen.add(cell)

    logger.info("Brugcellen: %d  (lon %.4f→%.4f op lat %.4f)",
                len(bridge),
                x_vals[xi_jct], x_vals[xi_bridge_end], y_vals[yi_jct])

    # ── volledige nieuwe keten = brug + PDOK-deel vanaf pdok_start_idx ───────
    pdok_tail = snapped[pdok_start_idx:]
    full_chain = bridge + pdok_tail
    logger.info("Totale nieuwe keten: %d cellen", len(full_chain))

    # ── LDD, wflow_river én wflow_subcatch bijwerken ─────────────────────────
    # Alle chain-cellen moeten in de subcatch zitten (subcatch=1), anders
    # maakt Wflow's searchsortedfirst valse edges die cycli veroorzaken.
    SUBCATCH_ID = 1.0  # enige subcatch-ID in dit model
    updated = 0
    for i in range(len(full_chain) - 1):
        yi, xi       = full_chain[i]
        yi_ds, xi_ds = full_chain[i + 1]
        ldd_new = ldd_direction(yi, xi, yi_ds, xi_ds)
        ldd[yi, xi]      = ldd_new
        river[yi, xi]    = 1
        subcatch[yi, xi] = SUBCATCH_ID
        updated += 1

    # Terminus: pit bij monding Ketelmeer
    yi_t, xi_t = full_chain[-1]
    ldd[yi_t, xi_t]      = 5
    river[yi_t, xi_t]    = 1
    subcatch[yi_t, xi_t] = SUBCATCH_ID
    updated += 1

    logger.info("LDD/river/subcatch bijgewerkt voor %d cellen", updated)
    logger.info("Terminus: lat=%.4f, lon=%.4f (pit)", y_vals[yi_t], x_vals[xi_t])

    # Toon nieuwe keten
    logger.info("Nieuwe keten (iedere 5e cel):")
    for i in range(0, len(full_chain), max(1, len(full_chain)//15)):
        yi, xi = full_chain[i]
        lv = int(ldd[yi, xi])
        logger.info("  [%3d] lat=%.4f lon=%.4f ldd=%s",
                    i, y_vals[yi], x_vals[xi], LDD_NAME.get(lv, str(lv)))

    # ── parameterwaarden invullen voor nieuwe subcatch-cellen ────────────────
    # Nieuwe cellen (buiten originele subcatch) hebben NaN voor alle
    # statische parameters. Vul op met nearest-neighbour uit bestaande cellen.
    SKIP_VARS = {"wflow_ldd", "wflow_river", "wflow_subcatch",
                 "wflow_uparea", "wflow_gauges_grdc"}
    RIVER_VARS = {"wflow_riverlength", "wflow_riverwidth",
                  "RiverSlope", "RiverDepth", "RiverZ", "N_River", "RiverLength"}
    ds_orig = xr.open_dataset(NC_IN)  # original (backup restored) — read all vars
    subcatch_orig = ds_orig["wflow_subcatch"].values.astype(float)
    river_orig    = ds_orig["wflow_river"].values.astype(float)

    # NN from all original subcatch cells (for land parameters)
    orig_rows, orig_cols = np.where(~np.isnan(subcatch_orig))
    orig_pts = np.column_stack([orig_rows, orig_cols]).astype(float)

    # Separate NN from original RIVER cells (for river-specific parameters)
    riv_rows, riv_cols = np.where(
        (~np.isnan(subcatch_orig)) & (~np.isnan(river_orig)) & (river_orig == 1)
    )
    riv_pts = np.column_stack([riv_rows, riv_cols]).astype(float)

    # Find new cells (in expanded subcatch but not in original)
    new_rows, new_cols = np.where(
        ~np.isnan(subcatch) & np.isnan(subcatch_orig)
    )
    # Also fill chain cells that were already in the original subcatch but
    # had river=0 (riverlength=0) and are now river=1.
    rl_orig = ds_orig["wflow_riverlength"].values.astype(float)
    chain_needing_river_fill = [
        (yi, xi) for (yi, xi) in full_chain
        if not np.isnan(subcatch_orig[yi, xi])      # already in orig subcatch
        and rl_orig[yi, xi] == 0                    # had no river length
    ]
    fill_targets = list(zip(new_rows, new_cols)) + chain_needing_river_fill
    logger.info("Cellen die parameter-fill nodig hebben: %d nieuw-subcatch + %d nieuw-river",
                len(new_rows), len(chain_needing_river_fill))

    filled = 0
    for yi, xi in fill_targets:
        is_river_cell = True  # all targets are now river=1

        # Land NN
        dists = np.sqrt((orig_pts[:, 0] - yi)**2 + (orig_pts[:, 1] - xi)**2)
        nn_idx = int(np.argmin(dists))
        nn_yi, nn_xi = int(orig_rows[nn_idx]), int(orig_cols[nn_idx])

        # River NN
        if len(riv_pts) > 0:
            dists_r = np.sqrt((riv_pts[:, 0] - yi)**2 + (riv_pts[:, 1] - xi)**2)
            rnn_idx = int(np.argmin(dists_r))
            rnn_yi, rnn_xi = int(riv_rows[rnn_idx]), int(riv_cols[rnn_idx])

        for vname, da in ds_orig.data_vars.items():
            if vname in SKIP_VARS:
                continue
            if vname in RIVER_VARS and len(riv_pts) > 0:
                src_yi, src_xi = rnn_yi, rnn_xi
            else:
                src_yi, src_xi = nn_yi, nn_xi
            if da.values.ndim == 2:
                da.values[yi, xi] = da.values[src_yi, src_xi]
            elif da.values.ndim == 3:
                da.values[:, yi, xi] = da.values[:, src_yi, src_xi]
        filled += 1
    logger.info("Parameter-fill (NN): %d cellen ingevuld", filled)

    # ── opslaan ──────────────────────────────────────────────────────────────
    tmp = NC_IN.parent / "_tmp_staticmaps.nc"
    ds_orig["wflow_ldd"].values[...]      = ldd
    ds_orig["wflow_river"].values[...]    = river
    ds_orig["wflow_subcatch"].values[...] = subcatch
    ds_orig.to_netcdf(tmp)
    ds_orig.close()
    shutil.move(tmp, NC_IN)
    logger.info("Opgeslagen: %s", NC_IN)


if __name__ == "__main__":
    main()
