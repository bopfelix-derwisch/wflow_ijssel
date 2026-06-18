# Waterlab — korte rondleiding (demo-flow)

**Duur:** ~3–4 min · **Doel:** in één vloeiende flow laten zien dat Waterlab een
API-first waterplatform is: hydrologische modellen + AI + open data, op één Jetson.

Open elke stap direct via de **deep-link** (tab-hash). Lokaal: `http://localhost:8000/#…`
· Publiek: `https://waterlab.felixisfelix.com/#…`

> Tip voor opname: zet het venster op ~1400 breed, gebruik de hash-links om
> hard tussen tabs te springen (geen zoekgedrag in beeld).

---

### 0 · Opening — Handleiding  ·  `#handleiding`  (~20 s)
**Tonen:** de Handleiding-tab.
**Zeggen:** "Waterlab draait volledig op een NVIDIA Jetson AGX Orin. Drie leerdoelen —
modellen leren, het vakgebied verkennen, AI testen — en het is **API-first**: dashboard,
FEWS, app en GraphQL zijn allemaal verwisselbare clients op dezelfde data."
**Wijs aan:** de drie API-kaarten (PI REST · GraphQL · REST-endpoints).

### 1 · Het gebied — Rijn & IJssel  ·  `#uitleg`  (~20 s)
**Tonen:** de systeemuitleg + kaart.
**Zeggen:** "De IJssel krijgt ~13% van de Rijn via de Pannerdense Kop. We volgen het traject
Westervoort → Kampen — dat is de rode draad door alle proeven."

### 2 · Live verwachting + integrale AI  ·  `#forecast`  (~45 s) ⭐
**Tonen:** de 14-daagse verwachtingsgrafiek, dan de AI-interventie eronder.
**Zeggen:** "Een live debietverwachting uit RWS Waterinfo + Open-Meteo. Claude duidt die
als expert-hydroloog — en sinds kort **integraal**: niet alleen peil en scheepvaart, maar via
de grondwater-koppeling ook drinkwater (Vitens), landbouw en natuur/kwel op de Veluwe."
**Wijs aan:** de grondwater-context-regel onder de interventie (putten + lag/correlatie).

### 3 · Grondwater ↔ IJssel  ·  `#grondwater`  (~60 s) ⭐⭐
**Tonen — boven:** de overlay grondwater vs IJssel-peil (zomer 2018) + de putten-tabel.
**Zeggen:** "Echte gemeten grondwaterstanden uit het BRO, gekoppeld aan het IJssel-peil.
De lag-correlatie is sterk — r tot 0.94 — met vertragingen van 6 tot 28 dagen: putten hoger
op de Veluwe-flank volgen de rivier later. Qwen draait lokaal voor de duiding."
**Scroll naar — onder:** de **Vooruitblik**-grafiek.
**Zeggen:** "En vooruit: de live IJssel-verwachting geprojecteerd naar de verwachte
grondwatertrend per put. De eerste weken liggen al vast door reeds-gemeten afvoer; de
stippellijn is vandaag, het gearceerde deel is de 14-daagse verwachting."

### 4 · Validatie — hoe goed is het écht?  ·  `#validatie`  (~40 s) ⭐⭐
**Tonen:** de Validatie-tab — per punt de skill-score, dan de hindcast eronder.
**Zeggen:** "Niet alleen *'het ziet er plausibel uit'* — hoe goed ís het, objectief? Per punt
leggen we simulatie naast meting met een skill-score: NSE, KGE, bias. Eerlijk: alleen waar een
onafhankelijke meting bestaat; de rest staat mét reden in de matrix. Bij Kampen blijkt het
gesimuleerde peil kwantitatief onbruikbaar — en dat zeggen we hardop in plaats van het te verbergen."
**Scroll naar — onder:** de **Hindcast** ("leg de groene over de blauwe").
**Zeggen:** "En de terugblik — letterlijk de wens uit de review: voor elke dag reconstrueren we
de toen uitgegeven verwachting en leggen die over wat er werkelijk gebeurde. De fout groeit met de
horizon — dag 14 zo'n 100 m³/s RMSE, met een systematische overschatting — maar de onzekerheidsband
ving ~99% van de realisaties. Zelfde meetbron als de skill-score, geen tweede waarheid."

### 5 · De negen proeven  ·  `#pocs`  (~20 s)
**Tonen:** de POC-kaarten (scroll kort).
**Zeggen:** "Negen proeven, elk langs drie lijnen — functioneel, technisch, opvolging.
Van ensemble-AI en een multimodel-pipeline tot FEWS en grondwater."

### 6 · Het platform — GraphQL  ·  `/graphql`  (~45 s) ⭐
**Tonen:** GraphiQL; plak en run deze ene query:
```graphql
{
  station(id: "kampen") {
    name
    forecast(days: 14) { band { date mean } intervention { regime } }
    nearbyGroundwaterWells(radiusKm: 20, limit: 3) {
      broId  distanceKm
      series(period: "2018-06-01/2018-08-31") { events { date value } }
    }
  }
}
```
**Zeggen:** "Eén query stitcht stationmetadata, de live verwachting én de nabije
grondwaterputten met hun reeks — het schema ís de domeingraaf. Read-only en gelimiteerd
(diepte, tokens, 60 req/min)."

### 7 · Interoperabel — FEWS  ·  `#fews`  (~15 s)
**Tonen:** de FEWS PI REST-explorer.
**Zeggen:** "Dezelfde data ook als Deltares PI REST 1.25 — elke FEWS-instantie kan Waterlab
als externe bron aanroepen, zonder aanpassing."

### Afsluiter (~10 s)
**Zeggen:** "Eén edge-computer, open data, lokale + cloud-AI, en elke consumer praat met
dezelfde API. Dat is Waterlab — een **leerlab dat de redeneerlijn bewijst, geen
operationeel voorspelsysteem**: deels statistisch i.p.v. fysisch, data-gedreven grondwater,
één persoon. Voor operationele beslissingen: `waterinfo.rws.nl`."
**Wijs aan:** de **wél/niet-grens** op de landing (`#intro`) — canoniek vastgelegd in
`docs/WL-GOV-1_wel_niet.md` (WL-GOV-1); deck en dashboard gebruiken díe tekst.

---

## Snelle flow (alleen de links, voor een vlotte demo)
`#handleiding` → `#uitleg` → `#forecast` → `#grondwater` → `#validatie` → `#pocs` → `/graphql` → `#fews`

## Vooraf (zodat live calls direct laden)
```bash
B=http://localhost:8000
curl -s -o /dev/null $B/api/forecast/intervention      # warmt Claude-interventie
curl -s -o /dev/null $B/api/grondwater                 # warmt overlay + duiding
curl -s -o /dev/null $B/api/grondwater/projection      # warmt vooruitblik
curl -s -o /dev/null $B/api/validation                 # warmt skill-scores (RWS-fetch)
curl -s -o /dev/null $B/api/validation/hindcast        # warmt hindcast (RWS-fetch)
```
