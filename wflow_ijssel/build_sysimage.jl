# LET OP: dit is een kopie voor wie vanuit wflow_ijssel/ werkt. De canonieke
# versie staat in de repo-root (build_sysimage.jl) — wijzig die eerst en
# synchroniseer deze kopie mee.
#
# Bouwt een PackageCompiler sysimage voor Wflow.
# Na het bouwen: julia --sysimage wflow_sysimage.so --project=. run_ijssel.jl
#
# LET OP: geen `"""..."""` bovenaan dit bestand — zie precompile_wflow.jl.
# De precompile_execution_file hieronder verwijst naar het (eveneens
# gerepareerde) precompile_wflow.jl in deze map, dat op zijn beurt naar
# ijssel_config_precompile.toml wijst — niet naar de Proef 4-config.
using PackageCompiler

project_dir = @__DIR__

println("Bouwen Wflow sysimage (eenmalig, kan lang duren op ARM)...")
flush(stdout)

create_sysimage(
    ["Wflow"],
    sysimage_path = joinpath(project_dir, "wflow_sysimage.so"),
    precompile_execution_file = joinpath(project_dir, "precompile_wflow.jl"),
    project = project_dir,
)

println("Sysimage klaar: wflow_sysimage.so")
println("Gebruik: julia --sysimage wflow_sysimage.so --project=. run_ijssel.jl")
