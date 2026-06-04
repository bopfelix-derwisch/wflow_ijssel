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

toml_path = length(ARGS) > 0 ? ARGS[1] : joinpath(@__DIR__, "data", "output_2018", "ijssel_config_2018.toml")

if !isfile(toml_path)
    error("Config niet gevonden: $toml_path")
end

config = Wflow.Config(toml_path)

println("Starten Wflow SBM simulatie IJssel — zomer 2018 ...")
println("  Periode: $(config.time.starttime) → $(config.time.endtime)")
println("  Input:   $(config.dir_input)")
println("  Output:  $(config.dir_output)")
flush(stdout)

Wflow.run(config)

println("\nKlaar. Output in: $(joinpath(@__DIR__, string(config.dir_output)))")
flush(stdout)
