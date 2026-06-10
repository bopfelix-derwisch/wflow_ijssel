# WL-BRO-0 — BRO grondwater feasibility (resolves Q2 + Q3)

**Date:** 2026-06-10 · server-side probes from orin3 (CORS irrelevant). Status: **done, GO for WL-BRO-1.**

## TL;DR
The handover's assumed `/gm/gld/v1/waterlevel/` endpoint **does not exist**. The real, working pipeline:
**PDOK "grondwatermonitoring in samenhang" OGC API (bbox) → GLD bro_id + location + GMW link + CSV series URLs.**
One bbox call resolves discovery, the GMW↔GLD bridge, *and* gives series download URLs. No bronhouder iteration, no 16 MB objects.

## Q2 — wells near the IJssel/Veluwe? YES
- GMW characteristics (bbox lat 52.25–52.55 / lon 5.95–6.10, east-Veluwe flank Hattem–Heerde–Epe ↔ IJssel): **997 monitoring wells**.
- Of those, **313 GLD groundwater-level dossiers cover summer 2018** with real data.

## Q3 — GLD format & params? CSV (+ JSON), not XML for the data we need
GLD API base: `https://publiek.broservices.nl/gm/gld/v1`
- `GET /seriesAsCsv/{broId}?asISO8601=true` → **CSV**, columns: `Tijdstip, Voorlopige/Beoordeelde/Controle/Onbekend Waarde [m] + Opmerking`. Best for plotting.
- `GET /objectsAsCsv/{broId}?rapportagetype=compact&observatietype=regulier_beoordeeld` → compact CSV (URL handed to us by PDOK per dossier).
- `GET /objects/{broId}/observationsSummary` → JSON (obs list w/ startDate/endDate/type). Small.
- `GET /objects/{broId}` → full IMBRO **XML, ~16 MB** (all observations). **Avoid in the connector.**
- `GET /bro-ids?bronhouder={KvK}` → filters by data-owner KvK, **not bbox** (don't use for discovery).

## The bridge (key design finding)
- GMW objects do **not** reference their GLDs (no public reverse index); GMW coords are RD/EPSG:28992 in `deliveredLocation`, WGS84 in `standardizedLocation`.
- **Solution = PDOK OGC API Features:** `https://api.pdok.nl/bzk/bro-gminsamenhang-karakteristieken/ogc/v1`
  - Collections: `gm_gmw`, `gm_gmw_monitoringtube`, `gm_gmn*`, **`gm_gld`**, `gm_gar`.
  - `GET /collections/gm_gld/items?bbox=<minLon,minLat,maxLon,maxLat>&limit=1000&f=json` (CRS84, max 1000/page, pagination).
  - Each GLD feature gives: `bro_id`, **Point geometry (lon/lat)**, `gm_gmw_monitoringtube_fk/.href` (GMW link), `number_of_observations`, `research_first_date`, `research_last_date`, and `series_*_csv_url` / `imbro_xml_url`.
  - → Filter `number_of_observations>0 AND research_first_date<=2018-06-01 AND research_last_date>=2018-08-31`, then pick by location.

## Candidate wells for Proef 7 (Veluwe east flank, spread S→N)
| GLD BRO-ID | lat, lon | #obs | span |
|---|---|---|---|
| GLD000000044984 | 52.2507, 5.9987 | 56 | 1989→2020 |
| GLD000000008262 | 52.3797, 6.0570 | 2810 | 2017→2025 (rich) |
| GLD000000048526 | 52.4806, 6.0949 | 45 | 1982→2024 |
| GLD000000044584 | 52.5002, 6.0167 | 48 | 1990→2020 |
| GLD000000053138 | 52.5444, 6.0242 | 33 | 2014→2026 |

Reference proven end-to-end: `GLD000000030048` (nationwide sample) → 25,763 rows 1987–2024, **737 rows summer-2018**, hourly m-values.

## WL-BRO-1 connector design (recommended)
1. **Discovery (cached, daily):** PDOK `gm_gld/items?bbox=...` → filter to summer-2018 + obs>0 → curate ~5 wells (config or derived).
2. **Series (cached 15 min):** broservices `seriesAsCsv/{broId}?asISO8601=true`, parse the assessed/preliminary column.
3. **Overlay:** groundwater level (m NAP) vs existing IJssel Kampen `H.meting` (reuse `forecast`/waterinfo data — do NOT refetch).
4. **Analysis:** lag-correlation (river stage → groundwater response, days–weeks) + **Qwen2.5-32B** (localhost:8080) hydrological interpretation, graceful fallback (same pattern as ensemble).
5. New Data Hub connector `bro_gld` (+ `bro_gmw`); cache like existing sources; server-side `requests`.
6. Later: WL-GQL-2 `station → nearbyGroundwaterWells` — the PDOK bbox-by-station feeds this directly.
