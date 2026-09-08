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
oudere documentatie — zelfde orde van grootte, kleine afronding.)

## Duiding

De hindcastcijfers voor Westervoort veranderen verwaarloosbaar (alle deltas
onder de ~2 %): bij een besmettingsgraad van 0,24 % van de ruwe kwartierrijen
is dat een reëel en acceptabel resultaat — de oude hindcastcijfers blijven
houdbaar, er is geen aanleiding om ze in de memory-notitie te herzien. Voor de
reservoir-NSE ligt het anders: put GLD000000008239 (tau_river_days 180→365,
NSE nagenoeg gelijk) verandert nauwelijks, maar GLD000000053138 stijgt 12,6 %
en vooral GLD000000008262 stijgt 40,3 % (NSE 0,231→0,324) — allebei ruim boven
de ~5 %-drempel. Vermoedelijke oorzaak: het reservoirmodel voedt de
"river"-term met andere RWS-reeksen dan Westervoort-Q alleen (`tau_river_days`
verschuift ook merkbaar: 90→90, 45→180 dagen zijn hier niet allemaal identiek
gebleven), dus een klein aantal sentinelrijen in een gevoeliger stuk van die
reeks kan lokaal meer gewicht hebben gehad dan het aandeel van 0,24 %/0,03 %
doet vermoeden. Voor GLD000000008262 en GLD000000053138 is de memory-notitie
bijgewerkt (stap 5); voor de WL-VAL-2-hindcast en put GLD000000008239 blijven
de bestaande cijfers in de documentatie houdbaar en zijn ze niet aangepast.
