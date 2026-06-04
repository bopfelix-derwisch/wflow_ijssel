using Wflow
using Dates
using Logging

struct FlushLogger <: AbstractLogger
    inner::ConsoleLogger
end
Logging.min_enabled_level(l::FlushLogger) = Logging.min_enabled_level(l.inner)
Logging.shouldlog(l::FlushLogger, args...) = Logging.shouldlog(l.inner, args...)
function Logging.handle_message(l::FlushLogger, args...; kwargs...)
    Logging.handle_message(l.inner, args...; kwargs...)
    flush(stderr)
end
global_logger(FlushLogger(ConsoleLogger(stderr, Logging.Info)))

function timed(f, label)
    println("START: $label"); flush(stdout)
    t = time()
    result = f()
    elapsed = round(time() - t, digits=2)
    println("KLAAR: $label ($(elapsed)s)"); flush(stdout)
    return result
end

toml_path = joinpath(@__DIR__, "ijssel_config.toml")
config = timed("Config laden") do
    Wflow.Config(toml_path)
end

static_path = Wflow.input_path(config, config.input.path_static)

dataset = timed("NCDataset openen") do
    Wflow.NCDatasets.NCDataset(static_path)
end

reader = timed("NCReader aanmaken") do
    Wflow.NCReader(config)
end

clock = timed("Clock aanmaken") do
    Wflow.Clock(config, reader)
end

domain = timed("Domain aanmaken") do
    Wflow.Domain(dataset, config, Wflow.SbmModel())
end

println("Land cellen: $(length(domain.land.network.indices))"); flush(stdout)
println("Rivier cellen: $(length(domain.river.network.indices))"); flush(stdout)

land_hydrology = timed("LandHydrologySBM aanmaken") do
    Wflow.LandHydrologySBM(dataset, config, domain.land)
end

routing = timed("Routing aanmaken") do
    Wflow.Routing(dataset, config, domain, land_hydrology.soil, Wflow.SbmModel())
end

println("Diagnose klaar."); flush(stdout)
