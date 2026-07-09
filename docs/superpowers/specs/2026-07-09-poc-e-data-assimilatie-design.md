# Ontwerp — POC E · data-assimilatie (EnKF-familie) op het recessiemodel

**Datum:** 2026-07-09 · **Status:** goedgekeurd, gereed voor implementatie

## Doel
De VAL-2-hindcast toonde dat de Westervoort-recessie **systematisch overschat** (bias loopt op
van +11 naar +92 m³/s over 14 dagen). Deze POC assimileert de recente RWS-meting via een
ensemble-Kalman-update op de recessieparameters, corrigeert de verwachting, en **bewijst via de
bestaande hindcast-machinerie dat de bias/RMSE per horizon daalt** (validatie-lus gesloten).

## Aanpak — Ensemble Smoother (EnKF-familie, batch-update)
Puur numpy, in `dashboard/assimilation.py`. Eerlijk gelabeld als batch-ensemble-update (Ensemble
Smoother), geen sequentiële-filter-overclaim.

1. **Prior-ensemble** (N≈60): perturbeer parameters θ=(τ, doel) rond de prior (τ0=10,
   doel=`_seasonal_mean(month)`); meetruis op q0.
2. **Batch-update over het recente venster** (laatste M≈10 gemeten Westervoort-dagen):
   - Elk lid voorspelt het recente verloop vanaf de waarde M dagen terug: `recession_traj(anchor, τ_i, doel_i)`.
   - EnKF-update: `K = Cov(Θ,Y)·(Cov(Y)+R)⁻¹`, `θ_i ← θ_i + K·(y+ε_i − ŷ_i)` met geperturbeerde
     observaties ε_i~N(0,R), R = (8%·obs+20)². Posterior θ geclipt op fysische grenzen.
3. **Vooruit-verwachting** vanaf de meting van vandaag met posterior-θ → geassimileerd gemiddelde
   + P10/P90-ensembleband. **Vrije** verwachting = huidige deterministische recessie (τ0, seizoensdoel).

`recession_traj(q0,n,τ,doel)` = `max(doel + (q0−doel)·exp(−t/τ), 80)` — zelfde formule als
`forecast._recession`, maar met expliciet doel (dat `_recession` intern op het seizoensgemiddelde
vastzet). Prior-doel via `forecast._seasonal_mean`.

## Validatie-lus (bewijs)
Voor elke uitgifte-datum in het venster: assimileer met data tot D, forecast vooruit, vergelijk met
de realisatie D+1..D+14. Aggregeer **vrij vs geassimileerd** bias/RMSE per horizon via de bestaande
`validation.horizon_skill`. Toont of de assimilatie de VAL-2-overschatting daadwerkelijk verkleint.

## UX — nieuwe tab "Assimilatie"
- **Live-grafiek:** recente meting + vrije verwachting (stippel) vs geassimileerde verwachting (vol)
  + ensembleband.
- **Wat veranderde:** regel met prior→posterior τ en doel (bv. "τ 10 → 6, doel 240 → 180 m³/s → lagere staart").
- **Lus gesloten:** per lead-time de RMSE vrij vs geassimileerd (grafiek/tabel).

## Techniek
- Hergebruikt `_rws_daily`/`_recession`/`_seasonal_mean` (forecast) + `horizon_skill` (validation) —
  **geen tweede datapad**. Endpoint `GET /api/assimilation` (6u cache).
- EnKF-update = **pure functie** → getest (`tests/test_assimilation.py`): synthetische snelle-decay-obs
  → posterior-forecast heeft lagere RMSE t.o.v. de ware voortzetting dan de vrije forecast.
- Frontend: nieuwe tab + `loadAssimilation()` in app.js, `app.js?v=`-bump.

## Eerlijk afgebakend
Assimileert het **statistische** recessiemodel bij **Westervoort** (waar een meting bestaat) — niet
wflow-physics (= POC C, geblokkeerd op de sysimage) en niet Kampen (geen gemeten debiet, zie VAL-1).

## Definition of done
- Test groen (assimilatie verlaagt RMSE op de synthetische case).
- Tab toont live vrij-vs-geassimileerd + ensembleband + de per-horizon RMSE-vergelijking.
- Geen JS-fouten (headless), deep-link `#assimilatie` werkt (top-level state, geen TDZ).
- Forecast/validatie/PI REST blijven werken.
