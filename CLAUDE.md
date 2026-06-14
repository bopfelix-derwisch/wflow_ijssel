# Waterlab — Claude Code instructies

> **Machine-breed:** `~/.claude/CLAUDE.md` (gedeelde faciliteiten + valkuilen) en `ORIN3_SYSTEEM.md` — niet hier herhalen.
> **Domein:** Edge & Geo (`~/.claude/domains/edge-geo.md`) — deelt geo-basisdata met `Geluidsmeter`. **Start via** `orin3` → window `waterlab` (pad `/mnt/nvme/workspaces/waterlab`) voor consistente memory.
> **Lees eerst:** `README.md` (overzicht + API's), `DRAAIBOEK.md` (model-build), `docs/`.

## Stack & poorten
- Dashboard: FastAPI `dashboard.server:app` op **:8000** — systemd `waterlab-dashboard.service` (system python `/usr/bin/python3`, uvicorn-launcher in `~/.local/bin`).
- Publiek: `waterlab.felixisfelix.com` (cloudflared, dashboard-managed).
- API's: GraphQL **/graphql** (GraphiQL) · FEWS PI REST **/fews/rest/fewspiservice/v1** · REST `/api/...`.
- Lokale LLM **Qwen :8080** (ensemble/grondwater-duiding) · **Claude Haiku** (forecast-interventie, `.env` ANTHROPIC_API_KEY).
- Python 3.10 · Julia (wflow SBM, Ribasim) · `strawberry-graphql` (system python, `--user`).
- Repo: `github.com/bopfelix-derwisch/wflow_ijssel` (branch `master`).

## Valkuilen (project)
- **wflow-data** staat onder `wflow_ijssel/data/output*/`, NIET `<root>/data/` → `DATA_ROOT` in `server.py` + `fews_poc/data_adapter.py`. (Geen top-level `data/` → historische tabs leeg.)
- **`app.js` heeft `"use strict"`**: een verwijzing naar een niet-gedeclareerde var (bv. functieparam vs body-naam) gooit een ReferenceError → de héle grafiek rendert niet. Bump `app.js?v=NN` in `index.html` bij elke JS-wijziging.
- `dashboard/` is de **geserveerde** copy (single source); `wflow_ijssel/dashboard/` is verwijderd.
- Grondwater/reservoir: **eerste call ~30–60 s** (meerjarige Open-Meteo/RWS-fetch), daarna 6 u cache.

## Run
- `sudo systemctl restart waterlab-dashboard.service`
- `curl -sk? http://127.0.0.1:8000/...` · `/graphql` (GraphiQL) · headless browser-check: `verify_map_fallback.sh`.

## Status
Per-project memory: **`waterlab-graphql-and-data-state.md`** — 9 proeven, GraphQL-façade (Proef 8), BRO-grondwater + reservoir-voorspelling v2/v2b (Proef 9), integrale forecast. Voorstel-docs: `docs/WL-BRO-0_feasibility.md`, `docs/grondwater_voorspelling_voorstel.md`. Demo: `DEMO.md`.
