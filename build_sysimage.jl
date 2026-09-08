# Bouwt een PackageCompiler-sysimage met Wflow erin.
#
# Gemeten op orin3 (Jetson AGX Orin, 2026-09-08):
#   bouwen                                  11,2 min  -> 486 MB
#   koude start zonder sysimage              2 min 15 s
#   koude start met sysimage, 62-daagse run 16,7 s
#
# Draaien:  julia --project=. build_sysimage.jl
# Gebruik:  julia --sysimage wflow_sysimage.so --project=. run_ijssel.jl
#
# PackageCompiler wordt in een tijdelijke omgeving geinstalleerd, zodat de
# Manifest.toml van het project schoon blijft.
#
# LET OP: geen `"""..."""` bovenaan dit bestand — zie precompile_wflow.jl.
using Pkg
using Dates

project_dir = @__DIR__

build_env = mktempdir()
Pkg.activate(build_env)
Pkg.add("PackageCompiler")

using PackageCompiler

println("[build] start ", now(), " — dit duurt ruim tien minuten op ARM")
flush(stdout)

t0 = time()

create_sysimage(
    ["Wflow"];
    sysimage_path             = joinpath(project_dir, "wflow_sysimage.so"),
    precompile_execution_file = joinpath(project_dir, "precompile_wflow.jl"),
    project                   = project_dir,
)

println("[build] klaar ", now(), " — ", round((time() - t0) / 60, digits = 1), " minuten")
println("Gebruik: julia --sysimage wflow_sysimage.so --project=. run_ijssel.jl")
flush(stdout)
