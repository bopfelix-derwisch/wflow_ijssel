"""Download IJssel-vaarwegassen van PDOK NWB Vaarwegen en sla op als GeoPackage.

Uitvoer: data/input/river_geom_ijssel.gpkg (EPSG:4326)
Gebruikt als river_geom_fn in build_staticmaps.py.
"""
import json
import logging
from pathlib import Path

import geopandas as gpd
import requests
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT    = Path(__file__).parent
OUTPUT  = ROOT / "data" / "input" / "river_geom_ijssel.gpkg"
WFS_URL = "https://service.pdok.nl/rws/nwbvaarwegen/wfs/v1_0"

# Bbox die de hele IJssel + zijrivieren dekt (RD New / EPSG:28992)
# xmin, ymin, xmax, ymax — van Rijn-splitsing bij Arnhem tot Ketelmeer + Twente
BBOX_RD = "120000,390000,280000,530000,EPSG:28992"

# Vaarwegen die relevant zijn voor het wflow IJssel-model
RELEVANT_NAMES = {
    "Geldersche IJssel",
    "Neder-Rijn",
    "Waal",
    "Zwarte Water",
    "Kanaal Zutphen-Enschede",
    "Zwolle-IJsselkanaal",
}


def fetch_all(bbox: str) -> list[dict]:
    """Paginerend downloaden van alle vaarwegvakken in de bbox."""
    features = []
    offset = 0
    while True:
        r = requests.get(WFS_URL, params={
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeName": "nwbvaarwegen:vaarwegvakken",
            "outputFormat": "application/json",
            "count": "200",
            "startIndex": str(offset),
            "bbox": bbox,
        }, timeout=30)
        r.raise_for_status()
        batch = r.json().get("features", [])
        features.extend(batch)
        logger.info("  batch offset=%d: %d features", offset, len(batch))
        if len(batch) < 200:
            break
        offset += 200
    return features


def rd_geom_to_wgs84(geometry: dict, transformer: Transformer) -> dict:
    """Converteer GeoJSON geometry van RD New (28992) naar WGS84 (4326)."""
    def transform_coords(coords):
        return [list(transformer.transform(x, y)) for x, y in coords]

    if geometry["type"] == "LineString":
        return {"type": "LineString", "coordinates": transform_coords(geometry["coordinates"])}
    elif geometry["type"] == "MultiLineString":
        return {"type": "MultiLineString",
                "coordinates": [transform_coords(line) for line in geometry["coordinates"]]}
    return geometry


def main() -> None:
    logger.info("Downloaden vaarwegvakken van PDOK NWB Vaarwegen ...")
    features = fetch_all(BBOX_RD)
    logger.info("Totaal ontvangen: %d features", len(features))

    t = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)

    selected = []
    for f in features:
        naam = f["properties"].get("vwgNaam", "")
        if not any(n in naam for n in RELEVANT_NAMES):
            continue
        geom_wgs = rd_geom_to_wgs84(f["geometry"], t)
        selected.append({
            "type": "Feature",
            "geometry": geom_wgs,
            "properties": {"naam": naam},
        })

    logger.info("Geselecteerde features (relevante vaarwegen): %d", len(selected))

    if not selected:
        raise RuntimeError("Geen features gevonden — check PDOK-verbinding")

    gdf = gpd.GeoDataFrame.from_features(selected, crs="EPSG:4326")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(OUTPUT, driver="GPKG")
    logger.info("Opgeslagen: %s (%d features)", OUTPUT, len(gdf))

    # Toon extent als controle
    bounds = gdf.total_bounds
    logger.info("Extent: lon %.3f-%.3f, lat %.3f-%.3f",
                bounds[0], bounds[2], bounds[1], bounds[3])

    # Toon meest noordelijke Geldersche IJssel-punten als sanity check
    ijssel = gdf[gdf["naam"].str.contains("Geldersche IJssel", na=False)]
    if not ijssel.empty:
        coords = []
        for geom in ijssel.geometry:
            if geom is not None:
                coords.extend(list(geom.coords) if hasattr(geom, 'coords')
                              else [c for line in geom.geoms for c in line.coords])
        coords.sort(key=lambda c: c[1], reverse=True)
        logger.info("Geldersche IJssel — %d segmenten, meest noordelijk:", len(ijssel))
        for lon, lat in coords[:4]:
            logger.info("  lat=%.4f  lon=%.4f", lat, lon)


if __name__ == "__main__":
    main()
