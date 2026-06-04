using Wflow
using Dates

toml = joinpath(@__DIR__, "ijssel_config.toml")
println("Stap 1: Config laden...")
@time config = Wflow.Config(toml)
println("  OK: ", config.time.starttime, " → ", config.time.endtime)

println("Stap 2: Static dataset openen...")
static_path = joinpath(@__DIR__, string(config.dir_input), string(config.input.path_static))
@time ds = Wflow.NCDatasets.NCDataset(static_path)
println("  Variabelen: ", length(keys(ds)))

println("Stap 3: Domain bouwen (LDD + netwerk)...")
@time domain = Wflow.Domain(ds, config, Wflow.SbmModel())
println("  Land cellen:  ", length(domain.land.network.indices))
println("  Rivier cellen:", length(domain.river.network.indices))
close(ds)
println("Klaar.")
