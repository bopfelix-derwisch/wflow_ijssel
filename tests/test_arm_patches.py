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


def test_check_doorzoekt_alle_versiemappen_niet_alleen_de_eerste(tmp_path):
    """Julia heeft vaak meerdere versiemappen per pakket naast elkaar (op
    orin3 bijv. drie CFTime-kopieen, waarvan er een gepatcht is). check()
    moet ze allemaal doorzoeken, niet alleen de eerste of de laatste in
    sorteervolgorde.

    De mapnamen "aaaa"/"mmmm"/"zzzz" zijn bewust zo gekozen dat de gepatchte
    kopie ("mmmm") noch eerst, noch laatst gesorteerd wordt: een implementatie
    die alleen de eerste of alleen de laatste map bekijkt, faalt hierop.
    """
    for patch in PATCHES:
        for versie in ("aaaa", "mmmm", "zzzz"):
            f = tmp_path / "packages" / patch["package"] / versie / patch["path"]
            f.parent.mkdir(parents=True, exist_ok=True)
            if versie == "mmmm":
                f.write_text(f"# voorloop\n{patch['marker']}\n# naloop\n")
            else:
                f.write_text("# ongepatchte upstream-versie\n")

    resultaat = check(tmp_path)
    assert all(r["present"] for r in resultaat)
    for r in resultaat:
        assert r["found_at"] is not None
        # r["found_at"] = tmp_path / "packages" / package / versie / <patch["path"]>
        # patch["path"] bevat zelf een submap ("src/..."), dus de versiemap
        # is twee niveaus boven het bestand, niet de directe parent.
        versiemap = r["found_at"].relative_to(tmp_path / "packages" / r["package"]).parts[0]
        assert versiemap == "mmmm"


def test_check_meldt_ontbrekend_als_geen_van_de_versiemappen_de_marker_heeft(tmp_path):
    """Spiegelvariant: meerdere versiemappen per pakket, maar geen enkele
    bevat de marker. De patch moet dan als ontbrekend gelden."""
    for patch in PATCHES:
        for versie in ("aaaa", "mmmm", "zzzz"):
            f = tmp_path / "packages" / patch["package"] / versie / patch["path"]
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("# ongepatchte upstream-versie\n")

    resultaat = check(tmp_path)
    assert not any(r["present"] for r in resultaat)
    assert all(r["found_at"] is None for r in resultaat)


@pytest.mark.skipif(not (Path.home() / ".julia" / "packages").exists(),
                    reason="geen Julia-depot op deze machine")
def test_de_echte_installatie_is_gepatcht():
    """Op orin3 moeten alle vier de patches aanwezig zijn. Faalt deze test,
    dan is de wflow-rekenkern traag of stuk — zie tools/arm_patches/README.md."""
    resultaat = check()
    ontbrekend = [r["name"] for r in resultaat if not r["present"]]
    assert not ontbrekend, f"ontbrekende ARM-patches: {ontbrekend}"
