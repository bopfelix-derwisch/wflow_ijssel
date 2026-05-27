using Wflow
using Dates

toml_path = joinpath(@__DIR__, "ijssel_config.toml")

if !isfile(toml_path)
    error("Config niet gevonden: $toml_path — voer eerst de Python scripts uit.")
end

config = Wflow.Config(toml_path)

# Smoke test: overschrijf eindtijd voor snelle verificatie
# Verwijder deze regel voor de volledige jan-1995 simulatie
config.endtime = DateTime("1994-12-03T00:00:00")

println("Starten Wflow SBM simulatie IJssel ...")
println("  Periode: $(config.starttime) → $(config.endtime)")
println("  Input:   $(config.dir_input)")
println("  Output:  $(config.dir_output)")

Wflow.run(config)

println("\nKlaar. Output in: $(joinpath(@__DIR__, config.dir_output))")
