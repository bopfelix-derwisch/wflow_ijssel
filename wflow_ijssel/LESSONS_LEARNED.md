# Lessons Learned — Wflow SBM on ARM Edge Hardware
## IJssel Catchment · January 1995 Flood Simulation
### For exchange with Deltares / Wflow development team

**Platform:** NVIDIA Jetson AGX Orin Developer Kit (aarch64, ARM Cortex-A78AE)  
**OS:** Linux 5.15 (Ubuntu 20.04-based JetPack)  
**Julia:** 1.12.5 · **Wflow:** 1.0.2 · **Python:** 3.10  
**Simulation period:** 1994-12-01 → 1995-01-31 (62 daily timesteps)  
**Domain:** IJssel catchment, 300×240 grid cells, ~0.0083° (~800 m) resolution  
**Active cells:** 19,490 land · 1,303 river  
**Final runtime (after fixes):** ~31 seconds per simulation  

---

## 1. Context and goal

We ran the full Wflow SBM hydrological model on an NVIDIA Jetson AGX Orin — a compact ARM-based edge AI board — to simulate the January 1995 Rhine/IJssel flood event. The goal was to create a self-contained field dashboard: simulation + data export + FastAPI web server running on a single device, accessible over the local network. No cloud, no x86 workstation.

This document records every problem encountered, its root cause, the fix applied, and what Deltares/the Wflow team could do to prevent the problem for future users.

---

## 2. Problems and fixes

### 2.1 JIT compilation on ARM: 2–3 hour hang on first run

**Symptom:**  
Julia appeared completely frozen for 30–150+ minutes immediately after model initialisation began. No log output, no CPU saturation, memory stable at ~1.2 GB. Users naturally assumed a crash or deadlock.

**Root cause:**  
Julia's LLVM JIT compiler is dramatically slower on ARM than on x86_64. More importantly, Wflow's initialisation code triggered cascading *type-inference explosions*: Julia's compiler tried to statically resolve deeply nested parametric types at compile time, causing LLVM to compile hundreds of specialisations for code paths that are never actually taken at runtime.

Three separate trigger points were identified:

#### Fix A — `Clock(config, reader)` in `sbm_model.jl`

The `Clock(config, reader)` constructor (Wflow `Wflow.jl:82–119`) calls `cftime()` from CFTime.jl, which returns an abstract `UnionAll` type. Julia therefore could not infer a concrete type for `starttime`, and propagated this type-instability into every subsequent operation on the clock, triggering recursive specialisation cascades.

**Fix applied** (`sbm_model.jl:12–17`):
```julia
# Bypass Clock(config, reader) — triggers 30+ min LLVM cascade via CFTime constructors.
# Use nctimes[1] directly; all three config time fields are set in our TOML.
clock = let nctimes = reader.dataset_times
    Clock(nctimes[1], 0, Second(config.time.timestepsecs))
end
```
By reading `nctimes[1]` (already a concrete `DateTimeProlepticGregorian` from NCDatasets), the clock type is immediately concrete and the cascade is avoided.

#### Fix B — `cftime()` in `run!` in `Wflow.jl`

`run!` called `cftime(config.time.endtime, config.time.calendar)` to determine the simulation end time. `cftime()` calls `CFTime.timetype("proleptic_gregorian")` which returns the bare `DateTimeProlepticGregorian` UnionAll (not an instance), making `endtime` abstract.

**Fix applied** (`Wflow.jl:310–312`):
```julia
# Fix: cftime() returns abstract UnionAll type, causing type instability.
# Use last element of forcing times — same concrete type as starttime.
endtime = last(model.reader.dataset_times)
```

#### Fix C — CFTime `Period` constructor: type-parameter instability

Even after A and B, CFTime's internal `Period` constructor was not type-stable because `_factor(T)` and `_exponent(T)` returned raw integers (`Int64`), making `Period`'s return type dependent on runtime values.

**Fix applied** (new helpers in `CFTime/period.jl:31–40`):
```julia
@inline _itype(::Type{Period{T, Tfactor, Texponent}}) where {T, Tfactor, Texponent} = T
@inline _factor_type(::Type{Period{T, Tfactor, Texponent}}) where {T, Tfactor, Texponent} =
    isa(Tfactor, Val) ? Tfactor : Tfactor()
@inline _exponent_type(::Type{Period{T, Tfactor, Texponent}}) where {T, Tfactor, Texponent} =
    isa(Texponent, Val) ? Texponent : Texponent()

@inline function Period(Tdata::DataType, tuf::Tuple, ::Val{F}, ::Val{E}) where {F, E}
    duration = Tdata(_datenum(tuf, F, E))
    return Period{Tdata, Val{F}(), Val{E}()}(duration)
end
```

Key subtlety: `Tfactor` in the `Period` type parameters may be either a **type** (`Val{1}`) or an **instance** (`Val{1}()`), depending on which code path created it. The `isa(Tfactor, Val) ? Tfactor : Tfactor()` guard handles both. The Period constructor must create `Period{Tdata, Val{F}(), Val{E}()}` (with instance type parameters) to match the outer `DateTimeProlepticGregorian` type, otherwise a `convert` call is needed at `reset_clock!` time that fails because `unwrap(::Val{x})` only accepts instances.

Also required: a second `unwrap` overload:
```julia
# CFTime/datetime.jl line 6
unwrap(::Type{Val{x}}) where {x} = x   # handles type-param case
```

**Fix D** — `advance!`/`rewind!` in `io.jl`:
```julia
function advance!(@nospecialize(clock))
    clock.iteration += 1; clock.time += clock.dt; return nothing
end
```
`@nospecialize` prevents Julia from generating separate specialisations for every concrete Clock type.

**Recommendation to Deltares/Wflow team:**  
- The core issue is that `cftime()` returns an abstract type. Consider making `NCReader` store forcing times as a concrete type from the start, and have `Clock(config, reader)` use that type directly.  
- Upstream PR to CFTime.jl: add the type-stable `Period` constructor and `_factor_type`/`_exponent_type` helpers.  
- The ARM compilation time is ~300× worse than x86_64 for the same type-inference load. Any abstract return type that reaches a hot loop causes disproportionate pain on ARM.  
- Consider shipping a precompiled `PackageImage` (`.so`) for common ARM targets via Pkg artifacts.

---

### 2.2 Brooks-Corey exponent `c`: wrong dimension count

**Symptom:**
```
ERROR: LoadError: FieldError: type Wflow.InputEntries has no field
`soil_layer_water__brooks_corey_exponent`
```
This `FieldError` was misleading — it was thrown inside Wflow's *error handler*, not at the actual failure site.

**Root cause (actual):**  
The real error was `size(c, 1) != maxlayers`. Wflow's soil model internally uses `maxlayers = length(soil_layer_thickness) + 1` — one extra slot for a NaN sentinel layer. With `soil_layer__thickness = [100, 300, 800]` (3 layers), `maxlayers = 4`. Our `c_layer` NetCDF variable had only 3 layers.

**Root cause (secondary):**  
The error handler at `soil.jl:495` called `param(config.input.static, "soil_layer_water__brooks_corey_exponent")` on a `Wflow.InputEntries` object that only supports dict-style access (`getindex`), not property access (`getproperty`). So the helpful error message was never shown — only the crash in the crash handler.

**Fix applied:**  
Recreate `c_layer` with 4 layers, values `10.0` for all (including the sentinel):
```python
ds.createDimension('layer', 4)
c_layer = ds.createVariable('c_layer', 'f8', ('layer', 'y', 'x'), fill_value=-9999.0)
c_layer[:] = np.full((4, 240, 300), 10.0)
```

**Recommendation to Deltares:**  
- Document that layered parameters must match `maxlayers = n_configured_layers + 1`, not `n_configured_layers`. This is not obvious — the TOML says `soil_layer__thickness = [100, 300, 800]` (3 values) but the NetCDF must have 4.  
- The error handler at `soil.jl:495` should be fixed to not crash when `InputEntries` doesn't support field access. Ideally: print the variable name directly without calling `param()`.  
- HydroMT's static maps generator creates a 2D `c` variable. HydroMT should either generate `c_layer` with the correct number of layers automatically, or Wflow should degrade gracefully when a 2D `c` is provided (broadcasting to all layers).

---

### 2.3 Initial state file: missing `time` dimension

**Symptom:**
```
ERROR: LoadError: Number of state dims should be 3 or 4, number of dims = 2
```

**Root cause:**  
Our `instates-ijssel.nc` contained 2D state variables `(y, x)`. Wflow's `set_states!` expects either 3D `(y, x, time)` or 4D `(layer, y, x, time)` — a mandatory `time` dimension of size 1.

Additionally, the `ustorelayerdepth` state variable had 3 layers but needed 4 (same sentinel issue as `c_layer`).

**Fix applied:**  
Rebuild instates with a `time=1` dimension on all spatial variables, and 4 layers for `ustorelayerdepth` (4th layer = NaN).

**Recommendation to Deltares:**  
- Document the required state file format explicitly in the Wflow docs, including the mandatory singleton `time` dimension.  
- HydroMT or a Wflow utility should generate a valid cold-start state file that already has the correct dimensions. Writing this by hand is error-prone.  
- When `cold_start__flag = true`, Wflow generates default state. When it is `false` (warm start), the error message for wrong dimensions could be clearer: "State variable `ustorelayerdepth` has 2 dimensions; expected 3 (y, x, time) or 4 (layer, y, x, time)."

---

### 2.4 Forcing data: missing values on active cells at domain boundary

**Symptom:**
```
ERROR: ArgumentError: Forcing data at 1994-12-02T00:00:00 has missing values
on active model cells for precip
```

**Root cause:**  
ERA5 was downloaded with a bounding box that matched the grid extent. Three cells at the very northern edge of the catchment (the IJssel outlet into IJsselmeer at ~53.22°N) fell just outside the ERA5 grid coverage. Wflow treats NaN/missing forcing as a hard error on active cells.

**Fix applied:**  
Nearest-neighbour fill: replace the 3 NaN cells with values from the nearest non-NaN active cell, for all timesteps and all forcing variables (precip, temp, pet):
```python
for (ny, nx), (src_ny, src_nx) in nn_map.items():
    var[t, ny, nx] = var[t, src_ny, src_nx]
```

**Recommendation to Deltares:**  
- Add a small buffer (e.g., 0.1°) when downloading forcing data to ensure full coverage.  
- Alternatively, Wflow could fill boundary NaN cells automatically with nearest-neighbour during forcing loading, with a warning rather than a hard error. Missing forcing at 3 cells on a 19,490-cell domain will not meaningfully affect results.  
- Document this failure mode: ERA5 has a half-grid-cell offset at the poles and domain edges that can cause exactly this.

---

### 2.5 CSV output: gauge coordinates outside active river network

**Symptom:**
```
ERROR: inactive coordinate specified for output
```

**Root cause:**  
The TOML specified Kampen gauge at `(5.92, 52.55)` — the geographical town of Kampen on the IJssel delta. However, at the 800 m model resolution, the river at that location does not exist as an active river cell. The IJssel's navigable channel near the delta is represented ~20 km further north/west in the model (`5.496, 53.221` = outlet pit).

**Fix applied:**  
Update gauge coordinates in TOML to actual river cells:
```toml
[[output.csv.column]]
header = "Q_kampen"
coordinate.x = 5.496   # outlet pit cell
coordinate.y = 53.221
```

**Recommendation to Deltares:**  
- Provide a utility (or HydroMT function) that snaps a user-provided (lon, lat) coordinate to the nearest active river cell, with a warning showing the distance snapped.  
- The error message "inactive coordinate specified for output" could include the nearest active cell's coordinates as a suggestion: "Nearest river cell: x=5.496, y=53.221 (distance: 19.3 km)."  
- At ~800 m resolution, a 20 km snap distance may still produce scientifically useful output. Consider an auto-snap option in the TOML.

---

### 2.6 Output dimension names: `lat`/`lon` vs `x`/`y`

**Symptom:**  
Post-processing script failed with `ValueError: Dimensions {'y', 'x'} do not exist. Expected one or more of ('time', 'lat', 'lon')`.

**Root cause:**  
Wflow writes output NetCDF with coordinate names `lat` and `lon`, but the export script was written assuming `x` and `y`. Both are valid conventions, but they must be consistent.

**Fix applied:**  
Change `isel(x=xi, y=yi)` → `isel(lon=xi, lat=yi)` throughout `export_output.py`.

**Recommendation to Deltares:**  
- Standardise on `lat`/`lon` and document it. Alternatively, support both by adding `x = lon` and `y = lat` as coordinate aliases in the output.  
- xarray makes this easy with `ds.rename({'lat': 'y', 'lon': 'x'})`.

---

## 3. Summary table

| # | Component | Problem | Fix | Effort |
|---|-----------|---------|-----|--------|
| 1a | Julia/Wflow | `Clock(config, reader)` 30–150 min JIT hang | Bypass constructor, use `nctimes[1]` | Source patch |
| 1b | Julia/Wflow | `cftime()` → abstract `endtime` in `run!` | Use `last(reader.dataset_times)` | Source patch |
| 1c | CFTime.jl | Type-unstable `Period` constructor | New type-stable overloads | Source patch |
| 1d | Wflow/io | `advance!` compiles for every Clock type | `@nospecialize` annotation | Source patch |
| 2 | Input data | `c_layer` has 3 layers, model needs 4 | Add sentinel NaN layer to NetCDF | Data fix |
| 3 | Input data | State file lacks `time` dimension | Rebuild instates with `time=1` dim | Data fix |
| 4 | Input data | 3 outlet cells outside ERA5 coverage | Nearest-neighbour fill | Data fix |
| 5 | TOML config | Kampen gauge not on river network | Snap to nearest river cell | Config fix |
| 6 | Post-processing | `lat`/`lon` vs `x`/`y` mismatch | Fix dimension names in export script | Code fix |

---

## 4. Time accounting

| Phase | Time spent | Notes |
|-------|-----------|-------|
| Project scaffolding + HydroMT static maps | ~1 hour | Mostly automated via HydroMT |
| ERA5 forcing download + processing | ~30 min | API rate-limited |
| Wflow configuration (TOML) | ~1 hour | Parameter name lookup via docs |
| JIT compilation fix (issues 1a–1d) | ~4 hours | ARM-specific, hard to diagnose |
| Data dimension fixes (issues 2–4) | ~3 hours | Multiple restarts, slow feedback loop |
| Config/post-processing fixes (5–6) | ~30 min | Quick once root cause was known |
| Dashboard (FastAPI + deck.gl frontend) | ~2 hours | Mostly boilerplate |
| **Total** | **~12 hours** | Could be ~2 hours with fixes applied upfront |

The dominant cost was the **slow feedback loop on ARM**: each failed attempt required a new Julia startup (~2–5 min for package loading) plus waiting for errors to surface during model init (~10–15 min). On x86, the same iteration cycle would be ~30 seconds.

---

## 5. Recommendations by priority

### High priority (blockers for ARM deployment)

**P1 — Fix CFTime type instability upstream**  
File a PR or issue against CFTime.jl with the type-stable `Period` constructor. This is the root cause of the ARM JIT explosion and will affect any Julia application using CFTime on ARM. The fix is self-contained and does not change behaviour on x86.

**P2 — Fix `cftime()` return type in Wflow**  
`cftime()` returning an abstract `UnionAll` is the entry point for the Wflow-specific instability. Either return a concrete type or document that callers must use `nctimes[1]` instead.

**P3 — Publish a precompiled PackageImage for ARM**  
Wflow could ship a `PackageCompiler`-generated `.so` system image for `aarch64-linux-gnu` as a GitHub Release asset. This would reduce first-run time from 2–3 hours to ~30 seconds for all ARM users.

### Medium priority (data format clarity)

**P4 — Document `maxlayers = n_layers + 1`**  
The NaN sentinel layer is an implementation detail of the SBM soil model. HydroMT should generate `c_layer` with `n_layers + 1` depth automatically, or Wflow should accept `n_layers` and pad internally.

**P5 — Fix the broken error handler in `soil.jl:495`**  
The secondary crash in the error handler (`FieldError on InputEntries`) makes the actual error invisible. Fix: replace `param(config.input.static, varname)` with direct string interpolation.

**P6 — Document state file format with examples**  
The `time` dimension requirement and layer count for `ustorelayerdepth` are not documented. Provide a reference `instates.nc` alongside the example models.

**P7 — Coordinate snapping for CSV gauges**  
Auto-snap output gauge coordinates to the nearest river cell with a warning. The current hard error is unfriendly to users who specify real-world monitoring station locations.

### Low priority (quality of life)

**P8 — Standardise output dimension names**  
Pick `lat`/`lon` or `y`/`x` and document it. Currently Wflow writes `lat`/`lon` but examples and user scripts often assume `x`/`y`.

**P9 — Forcing boundary buffer**  
Add a configurable buffer (e.g., 0.1°) to forcing download bounding boxes to avoid NaN cells at domain edges.

---

## 6. What worked well

- **HydroMT** — generating static maps from MERIT Hydro + Copernicus land use via a single YAML configuration is excellent. The main gap is the 3D layered variables (see P4 above).
- **Wflow TOML configuration** — the standard name system (`atmosphere_water__precipitation_volume_flux`, etc.) is verbose but unambiguous and grep-friendly.
- **NCDatasets dimension handling** — Wflow's `read_dims`/`permute_data`/`reverse_data!` pipeline correctly handles both `(layer, y, x)` and `(x, y, layer)` dimension orderings. No manual transposition needed.
- **Julia Polyester `@batch`** — the parallelisation for land cells is transparent and effective; no changes needed for ARM.
- **FastAPI + deck.gl** — the combination of a Wflow-generated NetCDF → JSON export → FastAPI static file server → deck.gl browser dashboard worked very cleanly for edge deployment.

---

## 7. Reproducibility checklist for next ARM deployment

Use this list to reduce the ~12 hour setup to ~2 hours:

```
□ Apply CFTime patch before first Julia invocation
  (period.jl: type-stable Period constructor + unwrap overload)
  (datetime.jl: _factor_type/_exponent_type calls)

□ Apply Wflow patches
  (sbm_model.jl: bypass Clock(config, reader))
  (Wflow.jl: use last(reader.dataset_times) for endtime)
  (io.jl: @nospecialize on advance!/rewind!)

□ After any patch: rm -rf ~/.julia/compiled/v1.12/{CFTime,Wflow}

□ Input: c_layer must have maxlayers = n_soil_layers + 1 depth slices

□ Input: instates.nc must have time=1 dimension on all spatial vars
  and ustorelayerdepth must also have n_soil_layers + 1 depth slices

□ Input: download forcing with ≥0.1° buffer beyond domain extent

□ TOML: verify gauge coordinates snap to active river cells
  (use wflow_river mask + nearest-neighbour check in Python)

□ Post-processing: use lat/lon not x/y for output NetCDF dimensions
```

---

## 8. Dashboard network access: WiFi isolation and Tailscale

**Symptom:**  
Dashboard running on `0.0.0.0:8000` was unreachable from an iPad on the same WiFi network. SSH to the Jetson worked fine from the same device.

**Root cause:**  
Most consumer and office WiFi routers enable **AP client isolation** (also called wireless isolation or WLAN isolation) by default. This prevents devices connected to the same access point from communicating directly with each other — a security measure against lateral movement. SSH traffic over port 22 may be exempted by some routers or reach the Jetson via a different path (wired uplink, VPN), while arbitrary high ports like 8000 are blocked.

**Fix applied:**  
The Jetson already had **Tailscale** running (`tailscale ip` → `100.112.6.2`). The iPad also had Tailscale installed in the same tailnet. Tailscale creates an encrypted peer-to-peer overlay network that bypasses the router entirely — traffic goes directly between devices regardless of local network topology.

Accessing `http://100.112.6.2:8000` from the iPad worked immediately.

**Recommendation for edge deployments:**  
Install Tailscale on the edge device as standard practice. It solves three problems at once:
1. **WiFi isolation** — access from any device in the tailnet regardless of local network policy
2. **Remote access** — reach the device from outside the local network without port forwarding
3. **Security** — no need to bind services to `0.0.0.0`; bind to the Tailscale interface (`100.x.x.x`) only, keeping the service invisible to the local LAN

**Recommended uvicorn startup** for production use on Tailscale:
```bash
TAILSCALE_IP=$(tailscale ip -4)
uvicorn dashboard.server:app --host $TAILSCALE_IP --port 8000
```
Access URL: `http://$(tailscale ip -4):8000` — works from any device in the tailnet, on any network.

---

## 9. Environment versions

| Package | Version |
|---------|---------|
| Hardware | NVIDIA Jetson AGX Orin Dev Kit |
| OS | Linux 5.15.148-tegra (aarch64) |
| Julia | 1.12.5 |
| Wflow.jl | 1.0.2 |
| CFTime.jl | (pinned with Wflow) |
| NCDatasets.jl | (pinned with Wflow) |
| Python | 3.10.12 |
| HydroMT | latest |
| FastAPI / uvicorn | latest |
| xarray | latest |

---

*Document prepared 2026-05-31. Contact: bop.felix@gmail.com*
