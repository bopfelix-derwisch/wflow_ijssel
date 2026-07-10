# Waterlab — korte rondleiding (demo-flow)

**Duur:** ~4½ min · **Doel:** *show, not tell* — laten zien dat Waterlab niet "iets bij elkaar
dromt", maar dat elk getal **herleidbaar** is (herkomst) en **getoetst** tegen metingen
(validatie). De rode draad is vertrouwen, niet cosmetica.

Open elke stap direct via de **deep-link** (tab-hash). Lokaal: `http://localhost:8000/#…`
· Publiek: `https://waterlab.felixisfelix.com/#…`

> Tip voor opname: zet het venster op ~1400 breed, gebruik de hash-links om
> hard tussen tabs te springen (geen zoekgedrag in beeld). **Houd de disclaimer in
> beeld** — de wél/niet-grens op de landing en de "indicatief"-banner bij de verwachting.

---

### 0 · Landing — de redeneerlijn & de grens  ·  `#intro`  (~25 s) ⭐
**Tonen:** de landing: de **redeneerlijn** (waardestromen × informatiefuncties) en eronder
de **wél/niet-grens**.
**Zeggen:** "Waterlab draait volledig op één NVIDIA Jetson. Je begint niet bij de techniek
maar bij de **waarde**: vier waardestromen, elk gekoppeld aan de informatiefuncties die ze
raken — innemen, schematiseren, rekenen, duiden, ontsluiten, valideren. En meteen de grens:
dit is een **indicatief leerlab, geen operationeel systeem**. Eén persoon, deels statistisch,
data-gedreven grondwater. Dat staat zwart-op-wit op de landing."
**Wijs aan:** de wél/niet-kaarten (`docs/WL-GOV-1`).

### 1 · Het gebied — Rijn & IJssel  ·  `#uitleg`  (~15 s)
**Zeggen:** "De IJssel krijgt ~13% van de Rijn via de Pannerdense Kop. We volgen het traject
Westervoort → Kampen — de rode draad door alle proeven."

### 2 · Live verwachting + integrale AI  ·  `#forecast`  (~40 s) ⭐
**Tonen:** de 14-daagse verwachtingsgrafiek, dan de AI-interventie eronder.
**Zeggen:** "Een live debietverwachting uit RWS Waterinfo + Open-Meteo. Claude duidt die
**integraal**: niet alleen peil en scheepvaart, maar via de grondwater-koppeling ook
drinkwater, landbouw en natuur/kwel. Let op de labels — gemeten, gesimuleerd, verwacht — elk
op zijn eigen as. En de **indicatief**-banner blijft staan."

### 3 · Herkomst — hoe komt dit tot stand?  ·  `#pocs`  (~45 s) ⭐⭐  — WL-PROV-1
**Tonen:** een POC-kaart; klap onderaan **"Herkomst — hoe komt dit tot stand"** open.
**Zeggen:** "Dit is het hart van het vertrouwensverhaal. Voor élke proef kun je de keten
afpellen: **databron → randvoorwaarde → modelstap → output → AI-duiding**. Je ziet de echte
bron en methode — ERA5, RWS Waterinfo, BRO via PDOK — én een eerlijke markering waar een stap
*niet fysisch* is. Bij Hoogwater 1995 staat er bijvoorbeeld dat de instroom bij Westervoort
**gesynthetiseerd** is uit het RIZA-archief, niet gemeten — want vóór 2000 is er geen data."
**Wijs aan:** klik de link **`docs/WL-PROV-2`** in de keten — de schematisatie-pagina opent:
de herkomst van het netwerk (Copernicus DEM + PDOK-correctie) en het instroompunt met randdebiet.
"Geen verzonnen schematisatie — alles staat hier, herleidbaar."

### 4 · Validatie — hoe goed is het écht?  ·  `#validatie`  (~50 s) ⭐⭐  — WL-VAL-1/2
**Tonen — boven:** per punt de skill-score (NSE/KGE/Pearson r/bias).
**Zeggen:** "Herkomst is de helft; de andere helft is: hoe goed ís het? Per punt leggen we
simulatie naast meting met een objectieve score. Eerlijk — alleen waar een onafhankelijke
meting bestaat; de rest staat mét reden in de matrix. Bij Kampen blijkt het gesimuleerde peil
kwantitatief onbruikbaar, en dat zeggen we hardop."
**Scroll naar — onder:** de **Hindcast** ("leg de groene over de blauwe") — *het VAL-2-rapport*.
**Zeggen:** "En de terugblik, letterlijk de wens uit de review: voor elke uitgifte-datum
reconstrueren we de toen gegeven verwachting en leggen die over wat er werkelijk gebeurde. De
fout groeit met de horizon — dag 14 zo'n 100 m³/s RMSE, een systematische overschatting — maar
de onzekerheidsband ving ~99% van de realisaties. Zelfde meetbron als de skill-score, geen
tweede waarheid."

### 5 · Assimilatie — de verwachting bijsturen met de meting  ·  `#assimilatie`  (~30 s) ⭐⭐  — POC E
**Tonen:** de Assimilatie-tab; speel het **"📽 Uitleg in 26 seconden"**-filmpje af.
**Zeggen:** "Validatie liet de systematische overschatting zien — hier lossen we die op. We nemen
de recente RWS-meting mee en sturen de verwachting bij met een ensemble-Kalman-update. Dit filmpje
vat het samen: van overschatting (rood) naar een bijgestuurde, eerlijk-onzekere verwachting (blauwgroen)."
**Wijs aan:** onder het filmpje het **bewijs** — de fout per voorspeldag daalt op elke horizon
(dag 14: 82 → 60 m³/s). "De fout die validatie mat, is nu meetbaar kleiner — de lus is gesloten."

### 6 · Grondwater ↔ IJssel  ·  `#grondwater`  (~35 s) ⭐
**Tonen:** de overlay grondwater vs IJssel (zomer 2018) + de putten-tabel, dan de reservoir-fit.
**Zeggen:** "Echte gemeten grondwaterstanden uit het BRO, gekoppeld aan de IJssel. Lag-correlatie
tot r 0.94, vertragingen van dagen tot weken. Een lineair reservoirmodel voorspelt de absolute
stand per put — **data-gedreven, geen MODFLOW-kwelmodel**, en de NSE per put staat erbij. Qwen
draait lokaal voor de duiding."

### 7 · Eén platform — GraphQL & FEWS  ·  `/graphql` → `#fews`  (~35 s) ⭐
**Tonen:** GraphiQL; run de query; spring dan naar de FEWS-explorer.
```graphql
{ station(id: "kampen") {
    forecast(days: 14) { band { date mean } intervention { regime } }
    nearbyGroundwaterWells(radiusKm: 20, limit: 3) { broId distanceKm } } }
```
**Zeggen:** "Eén query stitcht station, verwachting én grondwaterputten — het schema ís de
domeingraaf. En dezelfde data ook als Deltares PI REST 1.25: elke FEWS-instantie kan Waterlab
als bron aanroepen. Geen tweede datapad — alleen verwisselbare clients."

### Afsluiter (~10 s)
**Zeggen:** "Eén edge-computer, open data, lokale + cloud-AI. Elk getal herleidbaar, elke
verwachting achteraf getoetst. Dat is Waterlab — een **leerlab dat de redeneerlijn bewijst,
geen operationeel systeem**. Voor operationele beslissingen: `waterinfo.rws.nl`."
**Wijs aan:** terug op de landing de **wél/niet-grens** (`docs/WL-GOV-1`).

> **Bonus (optioneel, ~15 s):** open `#chat` ("Vraag het") en stel live een vraag — bv.
> *"waarom is het Kampen-peil niet te valideren?"* De assistent antwoordt **alleen** uit de
> eigen herkomst-/uitleg-bronnen en linkt terug naar de tab; staat het er niet in, dan zegt
> hij dat. Bewijs dat ook de chatbot niet hallucineert.

---

## Snelle flow (alleen de links)
`#intro` → `#uitleg` → `#forecast` → `#pocs` → `#validatie` → `#assimilatie` → `#grondwater` → `/graphql` → `#fews`

## Vooraf (zodat live calls direct laden)
```bash
B=http://localhost:8000
curl -s -o /dev/null $B/api/forecast/intervention      # warmt Claude-interventie
curl -s -o /dev/null $B/api/grondwater                 # warmt overlay + duiding
curl -s -o /dev/null $B/api/grondwater/projection      # warmt vooruitblik
curl -s -o /dev/null $B/api/grondwater/reservoir       # warmt reservoir-fit (~1 min eerste keer)
curl -s -o /dev/null $B/api/validation                 # warmt skill-scores (RWS-fetch)
curl -s -o /dev/null $B/api/validation/hindcast        # warmt het hindcast-rapport (RWS-fetch)
curl -s -o /dev/null $B/api/assimilation               # warmt de assimilatie + hindcast-vergelijking
```
