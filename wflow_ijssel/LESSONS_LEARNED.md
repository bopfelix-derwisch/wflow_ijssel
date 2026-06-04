# Lessons Learned — Wflow SBM on ARM Edge Hardware
## IJssel Catchment · January 1995 & July 2021 Flood Simulations
### For exchange with Deltares / Wflow development team

**Platform:** NVIDIA Jetson AGX Orin Developer Kit (aarch64, ARM Cortex-A78AE)  
**OS:** Linux 5.15 (Ubuntu 20.04-based JetPack)  
**Julia:** 1.12.5 · **Wflow:** 1.0.2 · **Python:** 3.10  
**Simulation periods:** 1994-12-01 → 1995-01-31 · 2021-05-01 → 2021-08-31  
**Domain:** IJssel catchment, 300×240 grid cells, ~0.0083° (~800 m) resolution  
**Active cells:** 19,490 land · 1,303–1,170 river  
**Final runtime (after JIT warmup):** ~31 s (1995) · ~2 min (2021, JIT already warm)  

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

### 2.7 MERIT D8 routing: IJssel gaat na Zwolle naar het noordoosten in plaats van naar Kampen

**Symptom:**  
Dashboard-balken volgen na Zwolle (52.47°N, 6.17°E) een noordoostelijk pad richting Meppel/Friesland. De echte IJssel buigt hier naar het noordwesten naar Kampen (52.55°N, 5.92°E) en stroomt vervolgens in het Ketelmeer/IJsselmeer.

**Root cause:**  
MERIT Hydro's D8-algoritme berekent de lokale stroomrichting uit hoogtegradiënten in een 90 m DEM. In het vlakke Nederlandse polderlandschap zijn deze gradiënten kleiner dan de verticale ruis in het DEM. Het algoritme koos bij de Zwolle-bifurcatie ten onrechte voor NE, wat overeenkomt met het Zwarte Water/Meppeldiep-systeem in plaats van de Geldersche IJssel richting Kampen.

**Technische details:**  
- Het model-stroomgebied (`wflow_subcatch`) was berekend op basis van de verkeerde D8-routing en dekte daardoor de westelijke Zwolle→Kampen-corridor (lon < 6.06°E) niet.
- Wflow's `flowgraph()` doet `to_node = searchsortedfirst(indices, to_index)`: als een actieve subcatch-cel wijst naar een cel buiten de subcatch, wijst `searchsortedfirst` naar de eerstvolgende actieve cel in gesorteerde volgorde — wat een zelf-lus (`from_node → from_node`) kan creëren en zo een "One or more cycles detected" fout veroorzaakt.
- Cellen die al in de subcatch lagen maar voorheen `wflow_river=0` hadden, kregen `wflow_riverlength=0` — dit leidde na activering als rivier-cel tot "river length must be positive on river cells".

**Fix applied:**  
`fix_staticmaps.py` past drie arrays aan in `staticmaps-ijssel.nc`:

1. **`wflow_ldd`**: junctiecel (52.4708°N, 6.1708°E) van NE→W; 57 cellen langs PDOK NWB-centerline bijgewerkt
2. **`wflow_river`**: alle 57 ketencellen op 1 gezet
3. **`wflow_subcatch`**: 40 cellen buiten het originele stroomgebied toegevoegd (subcatch-ID=1)

Parameter-fill voor 55 cellen die ontbrekende waarden hadden:
- Landparameters (`Slope`, bodem, vegetatie): nearest-neighbour uit bestaande subcatch-cellen
- Rivierparameters (`wflow_riverlength`, `wflow_riverwidth`, `RiverSlope`, `RiverDepth`): nearest-neighbour uitsluitend uit bestaande **rivier**-cellen (om te voorkomen dat 0-waarden van niet-rivier-buren worden overgenomen)

```python
# Kern van de fix — drie cascaderende problemen opgelost:
subcatch[yi, xi] = 1.0        # (1) voorkomt searchsortedfirst-zelf-lus → cycle
ldd[yi, xi]      = ldd_new    # (2) correcte stroomrichting
river[yi, xi]    = 1          # (3) riviercel activeren
# + NN-fill voor alle statische parameters van de nieuwe/geactiveerde cellen
```

**Recommendation to Deltares:**
- Voeg een pre-run validatiestap toe die controleert dat elke actieve subcatch-cel wijst naar een andere actieve cel (of een pit is). Dit vangt `searchsortedfirst`-cycli op vóór het model start.
- De foutmelding "One or more cycles detected" geeft geen locatie. Voeg de CartesianIndex van de betrokken cellen toe.
- Overweeg een HydroMT-optie om een gebruikersopgegeven vector-centerline (bijv. PDOK NWB) te gebruiken om D8-routing te overschrijven in vlakke gebieden, analoog aan de bestaande `river_geom_fn` parameter.
- Documenteer dat `fix_staticmaps`-achtige correcties ook `wflow_subcatch` moeten bijwerken — niet alleen `wflow_ldd` en `wflow_river`.

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
| 7 | Python/cdsapi | `attrs` namespace missing on system Python | Install `attrs>=22` to separate `--target` dir | Env fix |
| 8 | Python/xarray | `dask` not installed, `open_mfdataset` fails | `pip install dask` or pass `chunks=None` | Env fix |
| 9 | Python/scipy | numpy 2.x / scipy 1.x binary incompatibility | `pip install --upgrade scipy` | Env fix |
| 10 | Dashboard/browser | Old `app.js` cached by iPad Safari | `?v=N` cache-bust + `Cache-Control: no-store` | Code fix |
| 11 | Input data/routing | MERIT D8 stuurt IJssel na Zwolle naar NE i.p.v. NW naar Kampen | PDOK-centerline branden in ldd + river + subcatch; NN-fill parameters | Data fix |
| 11a | Wflow/network | Subcatch-cel buiten subcatch → `searchsortedfirst` zelf-lus → cycle-fout | `wflow_subcatch=1` voor alle ketencellen | Data fix |
| 11b | Input data | Nieuw geactiveerde rivier-cellen hebben `riverlength=0` | Aparte NN-fill vanuit rivier-cellen voor river-specifieke parameters | Data fix |

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
| **Total 1995** | **~12 hours** | Could be ~2 hours with fixes applied upfront |
| 2021 simulation + pipeline | ~2 hours | Python dependency issues; Wflow itself ~2 min |
| Multi-year dashboard + browser cache fix | ~1 hour | Cache-busting + year-tab UI |
| **Grand total** | **~15 hours** | |

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

□ Python dependencies (Jetson/ARM):
  pip3 install dask scipy --upgrade   # before first ERA5 processing
  pip3 install --target /tmp/cdsapi_deps cdsapi attrs  # if cdsapi 0.7.x needed
  PYTHONPATH=/tmp/cdsapi_deps python3 download_forcing_*.py

□ Dashboard: add ?v=N suffix to app.js <script> tag on every deploy
  Server: add Cache-Control: no-store to index.html FileResponse
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

## 9. Second simulation year: July 2021 flood

After the 1995 simulation ran successfully, we added a July 2021 simulation to the same installation — the Ahrtal/Rhine high-water event that caused severe flooding in Germany and the Netherlands.

### 9.1 Pipeline structure

The 2021 pipeline mirrors 1995 but uses different TOML parameters:

| Parameter | 1995 | 2021 |
|-----------|------|------|
| Simulation period | 1994-12-01 → 1995-01-31 | 2021-05-01 → 2021-08-31 |
| `cold_start__flag` | `false` (warm start) | `true` (no spin-up state) |
| `snow__flag` | `true` | `false` (summer) |
| Input dir | `data/input` | `data/input_2021` |
| Output dir | `data/output` | `data/output_2021` |
| Staticmaps | original | symlink to 1995 staticmaps |

`cold_start__flag = true` initialises all state variables from default (zero/equilibrium) values. The `path_input` state file is ignored. We symlinked the 1995 instates file as `data/input_2021/instates-ijssel-2021.nc` to satisfy Wflow's file existence check even though the file is not read.

### 9.2 Inflow: RWS Waterinfo API failed, synthetic used

`download_inflow_2021.py` tried the RWS Waterinfo REST API first. In 2026, this API returned HTTP redirect loops (`Exceeded 30 redirects`). A synthetic discharge curve was used instead:

- Baseflow: 250 m³/s with slight seasonal variation
- June pulse: +400 m³/s peak on 2021-06-20 (σ = 6 days)
- July flood: peak ~2200 m³/s at Westervoort on 2021-07-15

The July peak is based on historical data: Lobith peak ~8900 m³/s on 15 July 2021, IJssel share ~25%, giving ~2200 m³/s at Westervoort.

**Result:** Simulated peak Q at Kampen = **3090 m³/s on 16 July 2021**, 14 days above the 1500 m³/s threshold.

### 9.3 Runtime

The 2021 simulation completed in **2 minutes 5 seconds** — much faster than the 1995 first run — because the Julia JIT cache was already warm from the 1995 run. Subsequent runs of the same Wflow version take 2–5 minutes regardless of simulation length.

**Key lesson:** JIT warmup cost is per Julia session, not per simulation. Running two events back-to-back in one session is essentially free for the second. Plan batch runs accordingly.

### 9.4 Multi-year dashboard

The dashboard was extended with a year-tab UI. Architecture:

- **Server:** year-prefixed API routes `/api/{year}/kpis`, `/api/{year}/timeseries/{station}`, `/api/{year}/river/{day}`. Backward-compatible legacy routes `/api/kpis` etc. redirect to 1995.
- **Frontend:** `YEAR_CONFIG` dict in `app.js` maps year → day list, accent colour, alert text, event description. `switchYear()` swaps config and re-fetches all data without a page reload.
- **Plotly:** `Plotly.react()` updates an existing chart in place; no `Plotly.purge()` needed between years.

---

## 10. Python dependency problems on ARM (Jetson)

The Jetson runs Ubuntu 20.04 with Python 3.10. Several library version conflicts appeared when installing scientific Python packages into the user site.

### 10.1 cdsapi 0.7.x requires `ecmwf-datastores` which needs `attrs >= 22`

cdsapi 0.7.7 (the version compatible with the new CDS API key format, a bare UUID without a UID prefix) routes keys without ":" through `ecmwf.datastores.legacy_client`. This package requires `import attrs` — the `attrs` namespace module that was added in attrs 22.x. The system-installed attrs was 21.2.0, which only provides `import attr` (no `attrs` namespace).

**Fix:** install all cdsapi dependencies into a separate directory and inject it at runtime:
```bash
pip3 install cdsapi attrs --target /tmp/cdsapi_deps
PYTHONPATH=/tmp/cdsapi_deps python3 download_forcing_2021.py
```

**Alternative:** pin `cdsapi==0.6.1` — but this version expects old-style `UID:KEY` format and will not work with new-style UUID-only keys.

**Recommendation:** document the cdsapi version / key format dependency. New CDS (post-2024) uses UUID keys; old cdsapi (≤0.6.x) requires `UID:KEY`. A README note mapping CDS key format → cdsapi version would save significant time.

### 10.2 xarray `open_mfdataset` requires dask (not installed)

xarray `open_mfdataset` uses chunked/lazy loading via dask by default. On the Jetson, dask was not installed.

**Symptom:**
```
ImportError: chunk manager 'dask' is not available.
```

**Fix:** `pip3 install dask`

**Alternative:** pass `chunks=None` to `open_mfdataset` to force eager loading — acceptable for files of this size (< 1 MB each).

### 10.3 scipy/numpy binary incompatibility

The system scipy was compiled against numpy 1.x. After pip-installing numpy 2.x (pulled in as a dependency of newer packages), scipy raised:

```
ValueError: numpy.dtype size changed, may indicate binary incompatibility.
Expected 96 from C header, got 88 from PyObject
```

**Fix:** `pip3 install --upgrade scipy` — installs scipy 1.15.3 built against numpy 2.x.

**Lesson:** on a system with mixed apt/pip packages, always upgrade scipy and numpy together. Adding `scipy` to any `requirements.txt` should pin it alongside numpy: `numpy>=2.0,<3; scipy>=1.13`.

---

## 11. Browser caching: dashboard showed old JavaScript after code update

**Symptom:**  
After updating `app.js` to add the 2021 tab, the iPad still loaded the old version. Clicking the "Jul 2021" tab did nothing because the old `app.js` had no year-switching code. The server logs confirmed: all requests still used the legacy URLs (`/api/kpis`, `/api/river/1995-01-01`) rather than the new year-prefixed ones (`/api/1995/kpis`).

**Root cause:**  
Safari on iPad aggressively caches static assets. The server was not sending cache-control headers for `index.html` or `app.js`, so the browser reused its cached copy even after the server's files changed.

**Fix applied:**
1. Added `?v=2` query string to the `<script>` tag: `<script src="/static/app.js?v=2">` — forces a cache miss.
2. Added `Cache-Control: no-store` header to the `/` (index.html) response in FastAPI.

**For production:** use content-based hashing (e.g., Vite/webpack) to generate filenames like `app.abc123.js`. For development/edge deployments without a build step, increment a `?v=N` suffix manually on every deploy.

**Hard-refresh workaround on iPad Safari:** Settings → Safari → Advanced → Website Data → Remove data for the site. Or: long-press the reload button → "Reload Without Content Blockers" (not available on all iOS versions). Easier: tell the user the URL with `?cache=bust` appended to force a reload.

---

## 12. Environment versions

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
