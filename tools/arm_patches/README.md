# ARM-JIT-patches op Wflow en CFTime

Op ARM (Jetson AGX Orin) liep de eerste wflow-run vast in een LLVM-cascade van
uren. De oorzaak is type-instabiliteit: `cftime()` geeft een abstracte
`UnionAll` terug, waarna Julia honderden specialisaties compileert voor
codepaden die nooit worden gebruikt. Vier patches lossen dat op. Volledige
analyse: `LESSONS_LEARNED.md` §2.1.

**Deze patches staan in `~/.julia/packages/`, buiten git.** Eén `Pkg.update`
en ze zijn weg. Draai daarom `verify_arm_patches.py` voordat je op de
rekenkern vertrouwt.

| patch | pakket | bestand | marker |
|---|---|---|---|
| `clock-bypass` | Wflow | `src/sbm_model.jl` | `Fix 6 (ARM JIT)` |
| `endtime-concrete` | Wflow | `src/Wflow.jl` | `Fix 7 (ARM JIT)` |
| `period-typestable` | CFTime | `src/period.jl` | `_factor_type` |
| `advance-nospecialize` | Wflow | `src/io.jl` | `@nospecialize(clock)` |

`period-typestable` raakt ook `CFTime/src/datetime.jl` (de tweede
`unwrap`-overload); die wordt niet apart geverifieerd omdat `period.jl` en
`datetime.jl` altijd samen gepatcht zijn.

## Gevolg dat je moet kennen

`endtime-concrete` neemt `last(reader.dataset_times)` als eindtijd. Daardoor
**negeert wflow `starttime` en `endtime` uit de TOML**; het rekenvenster komt
volledig uit de tijdas van het forcing-bestand. Wie een kortere run wil, moet
de forcing slicen. Geverifieerd op 2026-09-08: een config met een venster van
10 dagen leverde 61 dagstappen op.

## Herstellen

Automatisch her-patchen doen we bewust niet — dat vereist de ongepatchte
bronversie, en een half-geslaagde patch op andermans broncode is gevaarlijker
dan een luide foutmelding. In `patched/` staan verbatim kopieën van de
gepatchte bestanden. Herstel is dus:

1. `/usr/bin/python3 tools/arm_patches/verify_arm_patches.py` — welke ontbreekt?
2. `diff patched/Wflow__io.jl ~/.julia/packages/Wflow/<hash>/src/io.jl`
3. Neem de ontbrekende wijziging met de hand over.
4. Verifieer opnieuw, en bouw de sysimage opnieuw met `julia --project=. build_sysimage.jl`
   (de sysimage bakt de gepatchte code in).

De kopieën in `patched/` horen bij Wflow 1.0.2 en de CFTime-versie met
git-tree-sha1 `912c24c352c4167df4ebdacb96a432a2e3dbaf7a`. Bij een andere
versie zijn ze een leidraad, geen kant-en-klare vervanging.
