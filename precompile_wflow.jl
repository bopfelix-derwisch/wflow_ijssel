"""
Precompile execution file for PackageCompiler.
Exercises the full Wflow SBM pipeline using the IJssel data so all heavy
methods (Clock, Domain, LandHydrologySBM, Routing, update!) end up in the sysimage.
"""
using Wflow
using Dates

toml_path = joinpath(@__DIR__, "ijssel_config.toml")
config = Wflow.Config(toml_path)
Wflow.run(config)
