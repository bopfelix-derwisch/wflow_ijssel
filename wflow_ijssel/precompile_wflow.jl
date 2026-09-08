# LET OP: dit is een kopie voor wie vanuit wflow_ijssel/ werkt. De canonieke
# versie staat in de repo-root (precompile_wflow.jl) — wijzig die eerst en
# synchroniseer deze kopie mee.
#
# Precompile execution file voor PackageCompiler.
#
# Draait de wflow SBM-pijplijn op de IJssel-data zodat de zware methoden
# (Clock, Domain, LandHydrologySBM, Routing, update!) in de sysimage belanden.
#
# LET OP: geen `"""..."""` bovenaan dit bestand. Julia leest een losse string
# boven een `using` als docstring, en `using` is niet documenteerbaar — dat
# liet dit script jarenlang binnen een seconde falen.
#
# Schrijft naar data/output_precompile/ (relatief aan wflow_ijssel/) en laat
# de Proef 4-output in data/output/ met rust.
using Wflow
using Dates

toml_path = joinpath(@__DIR__, "ijssel_config_precompile.toml")

println("[precompile] start ", now())
flush(stdout)

config = Wflow.Config(toml_path)
Wflow.run(config)

println("[precompile] klaar ", now())
flush(stdout)
