# Ontwerp — tab "POC via FEWS" (FEWS-client-modus)

**Datum:** 2026-07-06 · **Status:** goedgekeurd, gereed voor implementatie

## Doel
Een nieuwe dashboard-tab die bestaande POC's **draait als FEWS-client**: alle data wordt
opgehaald via de eigen **FEWS PI REST 1.25**-endpoints (`/fews/rest/fewspiservice/v1/…`),
niet via de interne `/api`. Bewijst dat Waterlab een echte, consumeerbare FEWS-databron is —
precies wat een Delft-FEWS-instantie zou binnenhalen. Complementair aan Proef 7 (de bestaande
FEWS-tab is een ruwe API-explorer; deze tab is een narratief, chart-gedreven "run").

## Scope
- **In scope:** de historische wflow-runs met een `period` in de FEWS-service — Hoogwater 1995,
  Droogte 2018, Hoogwater 2021 (= Proef 4/5/6). Parameter `Q.sim` op `KAMPEN` + `WESTERVOORT`.
- **Bewust buiten scope (eerlijk):** géén overlay van `Q.meting`/`H.meting` op een historische
  grafiek — die endpoints leveren *live* RWS (recent), niet de event-periode. Ze worden getoond
  als "óók via dezelfde interface beschikbaar", niet als (mismatchende) lijn. De live verwachting
  (Proef 1) zit niet in de FEWS-service → een mogelijke "volgende".

## UX / flow
1. **Run-keuze:** knoppen Hoogwater 1995 · Droogte 2018 · Hoogwater 2021.
2. **FEWS-handshake als mini-pijplijn** (echt uitgevoerd): `filters → locations → parameters →
   timeseries`, elk met het aantal (1 / 3 / 3 / n events) en de aangeroepen URL. Leesbaar als
   "de POC is dóór de FEWS-service gedraaid".
3. **Resultaat uit PI JSON:** de `timeseries`-respons (Q.sim @ Kampen + Westervoort) wordt
   client-side geparsed (let op: `event.value` is een string → `parseFloat`) en als grafiek
   gerenderd — dezelfde POC-uitkomst, maar via FEWS binnengehaald.
4. **Transparantie:** de exacte PI-REST-URL('s) + een PI-JSON-header-samenvatting (locationId,
   parameterId, units, start/eind) in beeld.

## PI JSON-contract (bestaand, geverifieerd)
`GET /fews/rest/fewspiservice/v1/timeseries?locationIds=…&parameterIds=Q.sim&period=…`
→ `{ version, timeZone, timeSeries:[ { header:{locationId,parameterId,units,startDate:{date,time},
endDate,…}, events:[ {date,time,value:"<num-string>",flag} ] } ] }`.

## Techniek
- **Puur frontend.** Nieuwe nav-knop `data-year="fewsrun"` + `#fewsrun-panel` in `index.html`,
  `loadFewsRun(runId)` + render-helpers in `app.js`, `app.js?v=`-bump.
- **Geen backend-wijziging, geen tweede datapad** — client op de bestaande FEWS-endpoints.
- Bestaande FEWS-tab blijft ongewijzigd.

## Definition of done
- Tab kiest een run → toont de 4-staps FEWS-handshake met echte tellingen + URLs → rendert de
  Q.sim-grafiek (Kampen + Westervoort) uit de PI JSON.
- Geen JS-fouten (headless), deep-link `#fewsrun` werkt (top-level state, geen TDZ).
- PI REST en bestaande tabs blijven werken.
