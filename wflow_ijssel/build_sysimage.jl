"""
Bouw een PackageCompiler sysimage voor Wflow.
Na het bouwen: julia --sysimage wflow_sysimage.so --project=. run_ijssel.jl
"""
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
