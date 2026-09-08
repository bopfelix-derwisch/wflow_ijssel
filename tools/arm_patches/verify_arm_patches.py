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
