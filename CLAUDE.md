# Waterlab — Claude Code instructies

> **Machine-breed:** `~/.claude/CLAUDE.md` (gedeelde faciliteiten + valkuilen) en `ORIN3_SYSTEEM.md` — niet hier herhalen.
> **Domein:** Edge & Geo (`~/.claude/domains/edge-geo.md`) — deelt geo-basisdata met `Geluidsmeter`. **Start via** `orin3` → window `waterlab` (pad `/mnt/nvme/workspaces/waterlab`) voor consistente memory.
> **Lees eerst:** `README.md` (overzicht + API's), `DRAAIBOEK.md` (model-build), `docs/`.

## Stack & poorten
- Dashboard: FastAPI `dashboard.server:app` op **:8000** — systemd `waterlab-dashboard.service` (system python `/usr/bin/python3`, uvicorn-launcher in `~/.local/bin`).
- Publiek: `waterlab.felixisfelix.com` (cloudflared, dashboard-managed).
- Nachtelijke wflow-nowcast: systemd `waterlab-nowcast.timer` (03:00, `Persistent=true`) → `wflow_ijssel/operational/nowcast.py` → `wflow_ijssel/data/forecast/latest.json`. Het dashboard **leest** dat bestand en rekent zelf niets; `/api/forecast` krijgt een `wflow`-blok met `status` (vers/verouderd/vervallen/ontbreekt/onleesbaar/leeg/mislukt). Boven 48 uur vervalt dat blok naar `available: false`. **Zichtbaar op de Verwachting-tab** als aparte lijn (`#64b5f6`) naast het statistische model, met eronder `#forecast-modelvergelijking` (`renderModelComparison` in `app.js`) dat de verschillen toelicht. Vervalt de lijn, dan staat de reden in dat blok.
- API's: GraphQL **/graphql** (GraphiQL) · FEWS PI REST **/fews/rest/fewspiservice/v1** · REST `/api/...`.
- **De FEWS PI REST is een emulatie die onze eigen data uitgeeft** (`fews_poc/`), géén koppeling die iets ophaalt bij de echte FEWS van RWS. Officiële RWS-cijfers komen altijd uit RWS Waterinfo via `dashboard/rws_client.py`.
- **De nachtrun berekent de dure antwoorden voor** (`dashboard/prebuilt.py`, geschreven door `nowcast.prebuild_dashboard`): `/api/forecast`, `/api/grondwater/reservoir` en `/api/forecast/intervention` serveren een bestand uit `data/forecast/api_*.json` zolang dat van vandaag is, en rekenen anders zelf. **Koud gemeten 2026-09-09: forecast 74 s, reservoir 45 s, interventie 12 s** — met caches van 15 min die na elke herstart leeg zijn. Ontbreekt het bestand, dan is de pagina traag maar niet stuk.
- **Peilverwachting Kampen** (`/api/forecast` → `stage`, `dashboard/stage.py`): **hybride**, nooit "wflow-peil" noemen. wflow levert rivierdiepte zonder opstuwing; Kampen wordt benedenstrooms gestuurd. Relatie `h = a + b·h_ketelmeer + c·Q_olst`, per dag herkalibreerd op ~3 jr RWS (b≈1,01, R²≈0,99, residu 2,3 cm). Meerpeil: RWS-verwachting (~3 d), daarna **gemeten maandklimatologie** van Ketelhaven — geen hardgecodeerd peilbesluit. Band verbreedt van ±5 naar ±14 cm zodra hij op klimatologie terugvalt.
- **Toetspunt Olst** (`/api/forecast` → `olst`): het enige punt op de IJssel waar RWS zowel een debietmeting als een officiële **debiet**verwachting publiceert (~3 dagen). Bij Kampen alleen een waterstandsverwachting, bij Westervoort niets. Modelcel 6.0958/52.3375 — 0,9 km van het echte Olst, want dáár ligt geen riviercel; geverifieerd op het pad Westervoort → uitstroom (stap 58 van 131).
- Lokale LLM **Qwen :8080** (ensemble/grondwater-duiding) · **Claude Haiku** (forecast-interventie, `.env` ANTHROPIC_API_KEY).
- Python 3.10 · Julia (wflow SBM, Ribasim) · `strawberry-graphql` (system python, `--user`).
- Repo: `github.com/bopfelix-derwisch/wflow_ijssel` (branch `master`).

## Valkuilen (project)
- **wflow-data** staat onder `wflow_ijssel/data/output*/`, NIET `<root>/data/` → `DATA_ROOT` in `server.py` + `fews_poc/data_adapter.py`. (Geen top-level `data/` → historische tabs leeg.)
- **`app.js` heeft `"use strict"`**: een verwijzing naar een niet-gedeclareerde var (bv. functieparam vs body-naam) gooit een ReferenceError → de héle grafiek rendert niet. Bump `app.js?v=NN` in `index.html` bij elke JS-wijziging.
- **wflow negeert `starttime`/`endtime` uit de TOML** (gevolg van de ARM-JIT-patches): het rekenvenster komt uit de tijdas van het forcing-bestand. Venster sturen = forcing slicen. Zie `tools/arm_patches/README.md`.
- **De gauge `Q_kampen` van de historische proeven is van de IJssel afgekoppeld.** Het netwerk vanaf Westervoort eindigt in een pit op 5.838/52.579; de gauge op 5.496/53.221 ziet alleen lokale afvoer. De operationele config meet daarom op de pit-cel; de historische configs zijn bewust ongewijzigd. **Verklaart de 37,7× amplitudefout uit WL-VAL-1.** Zie `docs/WL-SCHEMA-1_afgekoppelde-uitstroom.md`.
- **Een wflow-run zonder spin-up levert stil onzin.** De meegeleverde `instates` komen uit december 1994 met een leeg riviernetwerk; 15 dagen is te kort om te vullen. `python3 -m wflow_ijssel.operational.nowcast --spinup` draait 365 dagen (~100 s) en bouwt de state op.
- **ARM-patches op Wflow/CFTime staan buiten git** (`~/.julia/packages/`). Draai `/usr/bin/python3 tools/arm_patches/verify_arm_patches.py` voordat je op de rekenkern vertrouwt; zonder de patches duurt een koude start uren.
- **Alle RWS-verkeer via `dashboard/rws_client.py`** — die filtert de sentinel `999999999` (kwaliteitscode `99`). Voeg nooit een tweede `rw.get_data`-aanroep toe.
- `dashboard/` is de **geserveerde** copy (single source); `wflow_ijssel/dashboard/` is verwijderd.
- Grondwater/reservoir: **eerste call ~30–60 s** (meerjarige Open-Meteo/RWS-fetch), daarna 6 u cache.

## Run
- `sudo systemctl restart waterlab-dashboard.service`
- Nowcast handmatig: `/usr/bin/python3 -m wflow_ijssel.operational.nowcast` (~1 min) · eerste warme state: `… --spinup` (365 d, ~2 min) · log: `wflow_ijssel/data/output_operational/run.log`
- Timer: `systemctl list-timers waterlab-nowcast.timer` · `journalctl -u waterlab-nowcast.service -f`
- `curl -sk? http://127.0.0.1:8000/...` · `/graphql` (GraphiQL) · headless browser-check: `verify_map_fallback.sh`.

## Status
Per-project memory: **`waterlab-graphql-and-data-state.md`** — 9 proeven, GraphQL-façade (Proef 8), BRO-grondwater + reservoir-voorspelling v2/v2b (Proef 9), integrale forecast. Voorstel-docs: `docs/WL-BRO-0_feasibility.md`, `docs/grondwater_voorspelling_voorstel.md`. Demo: `DEMO.md`.
