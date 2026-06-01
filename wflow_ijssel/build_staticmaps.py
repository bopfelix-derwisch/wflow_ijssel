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
OUTLET = [5.92, 52.55]
RIVER_UPA = 30.0
RES = 0.008333


def build() -> None:
    build_root = str(ROOT / "wflow_build")
    logger.info("HydroMT model bouwen in %s ...", build_root)

    model = WflowModel(root=build_root, mode="w+", data_libs=["artifact_data"], logger=logger)
    model.build(
        region={"subbasin": OUTLET, "uparea": 10},
        opt={
            "setup_basemaps": {
                "hydrography_fn": "merit_hydro",
                "basin_index_fn": "merit_hydro_index",
                "res": RES,
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

    import shutil
    build_path = Path(build_root)
    shutil.copy(build_path / "staticmaps.nc", INPUT / "staticmaps-ijssel.nc")
    shutil.copy(build_path / "instates.nc",   INPUT / "instates-ijssel.nc")
    logger.info("Klaar: %s", INPUT / "staticmaps-ijssel.nc")


if __name__ == "__main__":
    build()
