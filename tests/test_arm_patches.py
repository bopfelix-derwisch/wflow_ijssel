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
