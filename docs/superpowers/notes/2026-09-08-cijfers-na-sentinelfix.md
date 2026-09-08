# Cijfers voor en na de sentinelfix (2026-09-08)

De sentinelfix (fase A, taken 1-3) haalt RWS-waarden `999999999` uit de reeksen
vóór het dag-gemiddelde, via `dashboard/rws_client.py`. Onderstaande cijfers
zijn op 2026-09-08 gemeten: eerst tegen de oude, draaiende dienst
(`waterlab-dashboard.service`, cache van 6 uur, sentinelrijen nog aanwezig),
daarna tegen dezelfde dienst ná `systemctl restart` (nieuwe code, koude cache).

Ruwe responses: `/tmp`-achtergebleven kopieën staan (tijdelijk) in
`.superpowers/sdd/2026-09-08-verwachting-v2-fase-ab/{hindcast,reservoir}_{voor,na}.json`.

Bekende besmettingsgraad (2023-09 t/m 2026-09): Westervoort Q 0,24 % van de
ruwe rijen, Kampen WATHTE 0,03 %.

**Reproduceerbaarheid**: de "na"-meting draaide tegen commit `35dd093`
(`fix(reservoir): v2b river-driver via rws_client, sentinelvrij`) op branch
`feat/verwachting-v2-fase-ab`. De "voor"-meting is aan géén commit te koppelen
— die kwam uit het proces van `waterlab-dashboard.service` dat sinds 31
augustus onafgebroken draaide, dus vóór de code die tot dit commit heeft
geleid.

## WL-VAL-2 hindcast (Westervoort, recessiemodel)

Venster in beide metingen identiek: 2026-06-25 → 2026-09-08, n_forecasts = 62.

| grootheid | voor | na | verschil |
|---|---|---|---|
| bias dag 1 (m³/s) | 12,7 | 12,9 | +1,6 % |
| bias dag 14 (m³/s) | 109,3 | 109,1 | −0,2 % |
| RMSE dag 7 (m³/s) | 71,8 | 71,1 | −1,0 % |
| RMSE dag 14 (m³/s) | 110,4 | 110,2 | −0,2 % |
| gemiddelde banddekking | 89 % | 90 % | +1 procentpunt |

Ter vergelijking: de oudere projectdocumentatie noemt bias +11 → +92 m³/s,
RMSE 18 → 99, banddekking ~99 %. Die cijfers komen uit een eerder (korter)
hindcastvenster en zijn dus niet 1-op-1 vergelijkbaar met de metingen hierboven;
de "voor"/"na"-vergelijking in deze tabel gebruikt in plaats daarvan twee
metingen tegen exact hetzelfde venster (vlak vóór en vlak ná de herstart), wat
de eigenlijke sentinel-invloed isoleert.

## Reservoir-NSE per put

| put | voor | na | verschil |
|---|---|---|---|
| GLD000000008239 | 0,812 | 0,809 | −0,4 % |
| GLD000000053138 | 0,501 | 0,564 | +12,6 % |
| GLD000000008262 | 0,231 | 0,324 | +40,3 % |

(Kolom "voor" hier met drie decimalen i.p.v. de afgeronde 0,84/0,52/0,22 uit de
oudere documentatie. Dat zijn geen zuivere afrondingen: 0,812 rondt niet af
naar 0,84 (~3,4 % verschil), en het reservoirmodel doet elke run een
nowcast-tot-vandaag op voortschrijdende BRO/Open-Meteo-data — hetzelfde
soort venstereffect als bij de hindcast is dus ook hier niet uit te sluiten.
Alleen de voor/na-vergelijking binnen dezelfde dag (deze tabel) isoleert de
sentinel-invloed zuiver; het verschil met de oudere documentatiecijfers kan
deels venster-/datadrift zijn en wordt hier niet geïnterpreteerd.)

## Duiding

De hindcastcijfers voor Westervoort veranderen verwaarloosbaar (alle deltas
onder de ~2 %): bij een besmettingsgraad van 0,24 % van de ruwe kwartierrijen
is dat een reëel en acceptabel resultaat — de oude hindcastcijfers blijven
houdbaar, er is geen aanleiding om ze in de memory-notitie te herzien. Voor de
reservoir-NSE ligt het anders: put GLD000000008239 verandert nauwelijks
(NSE 0,812→0,809), maar GLD000000053138 stijgt 12,6 % en vooral
GLD000000008262 stijgt 40,3 % (NSE 0,231→0,324) — allebei ruim boven de
~5 %-drempel. Vermoedelijke oorzaak: het reservoirmodel voedt de "river"-term
met andere RWS-reeksen dan Westervoort-Q alleen, en de auto-fit van de
tijdconstantes reageert merkbaar op de sentinelfix — per put, rechtstreeks uit
`reservoir_voor.json`/`reservoir_na.json` gehaald:

| put | tau_days voor→na | tau_river_days voor→na |
|---|---|---|
| GLD000000008239 | 45 → 45 (ongewijzigd) | 180 → 365 |
| GLD000000053138 | 10 → 10 (ongewijzigd) | 30 → 10 |
| GLD000000008262 | 90 → 180 | 90 → 90 (ongewijzigd) |

Bij GLD000000008239 verschuift alleen `tau_river_days` (180→365) maar blijft
de NSE nagenoeg gelijk; bij GLD000000053138 verschuift `tau_river_days`
(30→10) en stijgt de NSE 12,6 %; bij GLD000000008262 verschuift juist
`tau_days` (90→180, `tau_river_days` blijft 90) en stijgt de NSE het meest
(40,3 %). Elke put reageert dus op een andere parameter, wat past bij een
auto-fit die per put opnieuw convergeert op schonere data — een klein aantal
sentinelrijen in een gevoelig stuk van de reeks kan zo lokaal meer gewicht
hebben gehad dan het aandeel van 0,24 %/0,03 % doet vermoeden. Voor
GLD000000008262 en GLD000000053138 is de memory-notitie bijgewerkt (stap 5);
voor de WL-VAL-2-hindcast en put GLD000000008239 blijven de bestaande cijfers
in de documentatie houdbaar en zijn ze niet aangepast.
