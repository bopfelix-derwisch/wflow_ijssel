using Wflow
using Downloads
using Dates

# Gebruik een versie-tag (master verandert; tags blijven bestaan)
toml_url = "https://raw.githubusercontent.com/Deltares/Wflow.jl/v0.8.1/test/sbm_config.toml"

# Moselle artifacts
staticmaps = "https://github.com/visr/wflow-artifacts/releases/download/v0.2.9/staticmaps-moselle.nc"
forcing    = "https://github.com/visr/wflow-artifacts/releases/download/v0.2.6/forcing-moselle.nc"
instates   = "https://github.com/visr/wflow-artifacts/releases/download/v0.2.6/instates-moselle.nc"

inputdir  = joinpath(@__DIR__, "data", "input")
outputdir = joinpath(@__DIR__, "data", "output")
mkpath(inputdir)
mkpath(outputdir)

toml_path = joinpath(@__DIR__, "sbm_config.toml")

function get_if_missing(url, path)
    if !isfile(path)
        println("Downloading $(basename(path)) …")
        Downloads.download(url, path)
    end
end

get_if_missing(staticmaps, joinpath(inputdir, "staticmaps-moselle.nc"))
get_if_missing(forcing,    joinpath(inputdir, "forcing-moselle.nc"))
get_if_missing(instates,   joinpath(inputdir, "instates-moselle.nc"))
get_if_missing(toml_url,   toml_path)

# Kort smoke-testje: 2 dagen i.p.v. een maand
config = Wflow.Config(toml_path)
config.endtime = DateTime("2000-01-03T00:00:00")
Wflow.run(config)

println("\nDone. Kijk in: $(outputdir)")
println("Verwacht o.a.: data/output/output_moselle.csv en/of output_moselle.nc")
