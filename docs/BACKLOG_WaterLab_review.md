# WaterLab — Backlog (na review)

**Versie:** 1.3 · **Datum:** 2026-06-18 · **Rol:** claude.ai = PO/Architect
**Bron:** reviewsessie POC "Verwachting" (verslag + transcript) + handover v1.0
**Definition of Done (geldt voor élke story):** PI REST 1.25 en dashboard nooit breken · kleine, additieve diffs · `LESSONS_LEARNED.md` lezen vóór wijziging · disclaimer "indicatief leerlab" blijft staan.

---

## Leeswijzer van deze review

De review is enthousiast ("ik vind het geniaal") maar legt onder de complimenten één structureel risico bloot:

> *Voor wie het vak kent leest dit nu als "bullshit", omdat herkomst van data en schematisatie onzichtbaar is en niets tegen metingen is gevalideerd.*

Daarom is de leidende as van deze backlog **vertrouwen**, niet cosmetica. Volgorde:

1. **Herkomst zichtbaar maken** (WL-PROV) — waar komt alles vandaan, per stap aftepelbaar.
2. **Skill tegen metingen** (WL-VAL) — hoe goed is het eigenlijk, expliciet en herhaalbaar.
3. **Interpretatie aan de kaart** (WL-VIS) — per netwerkpunt, met eerlijke labels.
4. **Pas daarna** rekenkern-upgrade (WL-FC) en bevraagbaarheid (WL-CHAT).

---

## Huidige backlog (gereconstrueerd)

| ID | Story | Status |
|----|-------|--------|
| WL-GQL-1 | GraphQL-façade over domeingraaf (= Proef 8) | ✅ done |
| WL-BRO-1 | BRO-grondwaterkoppeling, gekalibreerd (= Proef 9) | ✅ done |
| WL-FC-1 | Vervang statistisch model door wflow SBM nowcast | 🔵 open (van dashboard) |
| WL-FC-2 | Tool-use agent haalt live peilmeting op via API | 🔵 open (van dashboard) |

---

## Nieuwe stories uit de review

### 🟥 Prioriteit 1 — Herkomst (WL-PROV)

#### WL-PROV-1 · Aftepelbare "hoe komt dit tot stand"-pagina per proef
**Als PO wil ik** één pagina die elke stap van een proef afpelt — databron → randvoorwaarde → modelstap → output → AI-duiding — **zodat** een vakgenoot kan zien dat er niets verzonnen is.
**Waarom:** dit is de directe tegenhanger van het "hij dromt iets bij elkaar"-verwijt. Zonder dit blijft elke demo aanvechtbaar.
**Acceptatiecriteria:**
- Per proef een `/uitleg/{proef}`-route met: databron + ophaalmethode (ERA5-Land/Copernicus, RWS Waterinfo, Open-Meteo, BRO via PDOK), randvoorwaarden, modelversie (wflow SBM 1.0.2 / Ribasim 2026.1.1 / statistisch), en de AI-stap met modelnaam.
- Elke getoonde waarde linkt naar zijn bron-endpoint (traceerbaar, geen losse claim).
- Waar een stap *niet* fysisch is, staat dat er expliciet (bv. grondwater = data-gedreven lag-correlatie, géén kwelmodel).

#### WL-PROV-2 · Herkomst van schematisatie en randvoorwaarden expliciet
**Als PO wil ik** dat de schematisatie en de inflow/randvoorwaarden van elke wflow-run herleidbaar zijn **zodat** "waar komt die schematisatie vandaan?" een antwoord heeft.
**Waarom:** het scherpste inhoudelijke gat in de review. Een model zonder herleidbare schematisatie is voor RWS/WMCN per definitie niet serieus te nemen.
**Acceptatiecriteria:**
- Documenteer per run: bron van het uitslagsysteem/netwerk, herkomst van de schematisatie, en de gebruikte instroompunten (bv. Lobith/Olst) met randdebiet.
- Maak zichtbaar dat wflow géén 1-D-float is maar op een randvoorwaarde rekent; benoem waar die vandaan komt.
- Vastgelegd in repo (`docs/`), gelinkt vanaf WL-PROV-1.

---

### 🟧 Prioriteit 2 — Validatie & skill (WL-VAL)

#### WL-VAL-1 · Gesimuleerd vs. gemeten, per punt, met skill-score
**Als PO wil ik** simulatie en meting structureel naast elkaar per netwerkpunt, met een objectieve score **zodat** ik kan zeggen *hoe goed* het model is i.p.v. dat het "plausibel" lijkt.
**Waarom:** de reviewer formuleerde dit zelf als een eigen epic — *"vanuit jouw rol: hoe goed zijn je modellen, vergelijk met metingen."* Validatie kreeg in de sessie expliciet prioriteit.
**Acceptatiecriteria:**
- Per punt een overlay meting/simulatie + skill-metriek (NSE, KGE en bias) over een gekozen periode.
- Werkt op de historische runs (1995/2018/2021) en op het live forecast-spoor.
- Score is een API-veld, niet alleen een plaatje (consistent met API-first).

#### WL-VAL-2 · Maandelijkse hindcast-terugblik ("hoe goed deden we?")
**Als PO wil ik** periodiek de verwachting van een datum over de gerealiseerde lijn leggen **zodat** ik per peildatum de voorspelfout zie en verbetering kan aantonen.
**Waarom:** letterlijk de wens van de reviewer — *"elke maand een rapport, leg de groene over de blauwe, wat was de fout van 31 mei?"*
**Acceptatiecriteria:**
- Genereert per maand een rapport: uitgegeven verwachting vs. realisatie, met fout per horizon.
- Is de *output* van WL-VAL-1, geen apart datapad (geen tweede waarheid bouwen).
- Bevat de onzekerheidsband zoals nu al in het integraal dashboard zit.

---

### 🟨 Prioriteit 3 — Interpretatie aan de kaart (WL-VIS)

#### WL-VIS-1 · Elk netwerkpunt klikbaar en betekenisvol
**Als PO wil ik** dat elke "bol" op de kaart klikbaar is en waterstand, debiet én afwijking t.o.v. normaal toont **zodat** een leek ziet wat er per punt gebeurt — niet alleen voor Kampen.
**Waarom:** *"ik kan als leek niet zien wat in die bolletjes gebeurt"* en *"kun je dit grafiekje voor álle punten maken?"*
**Acceptatiecriteria:**
- Klik op een knoop → grafiek met waterstand + debiet + "hoger/lager dan normaal".
- De Kampen-detailgrafiek is beschikbaar voor elk punt met data.
- Tooltip legt uit wat de bol representeert (de entiteit waarover wflow een uitspraak doet).

#### WL-VIS-2 · Eerlijke labels: gemeten / gesimuleerd / verwacht
**Als PO wil ik** dat elke lijn en as gelabeld is als meting, simulatie of verwachting, en dat debiet en waterpeil nooit ongelabeld op één as staan **zodat** de grafieken niet meer misleiden.
**Waarom:** de grootste tijdvreter in de sessie was precies dit — *"je zegt waterpeil, maar dit is debiet, dat kun je niet vergelijken."* Een verkeerd label ondermijnt het hele verhaal.
**Acceptatiecriteria:**
- Elke serie heeft type-label (meting/simulatie/verwachting) en eenheid + as.
- Debiet (m³/s) en waterpeil (m+NAP) krijgen gescheiden assen of gescheiden grafieken.
- Geen grafiek toont twee grootheden zonder expliciet onderscheid.

---

### 🟦 Prioriteit 4 — Rekenkern & bevraagbaarheid (WL-FC / WL-CHAT)

#### WL-FC-1 · Vervang statistisch model door wflow SBM nowcast *(bestaand, herzien)*
**Als PO wil ik** het statistische recessiemodel + Kalman-filter in Proef 1 kunnen vervangen door een wflow SBM nowcast **zodat** de verwachting op een fysisch model rust.
**PO-noot (niet volgzaam):** de "lichtheid" van Proef 1 is een *bewuste* architectuurkeuze (handover #11). wflow heeft ~2u20 cold start (Julia JIT); een live nowcast vereist eerst een voorverwarmde sysimage (`build_sysimage.jl`). Deze story is daarom **geblokkeerd op WL-PROV-2** (schematisatie-herkomst) en op de sysimage — anders vervangen we een transparant statistisch model door een ondoorzichtige modeltrein, en verplaatsen we het vertrouwensprobleem in plaats van het op te lossen.
**Acceptatiecriteria:**
- Nowcast draait binnen acceptabele responstijd dankzij voorverwarmde sysimage.
- Statistisch model blijft als fallback selecteerbaar (graceful fallback-principe).
- Skill van nowcast vs. statistisch model aantoonbaar via WL-VAL-1.

#### WL-FC-2 · Tool-use agent haalt live peilmeting on-demand op *(bestaand, verduidelijkt)*
**Als PO wil ik** dat de agent zelf via tool-use een live peilmeting opvraagt wanneer dat de duiding verbetert **zodat** de interventie op de meest actuele stand rust.
**Verduidelijking:** het forecast-spoor gebruikt al RWS Waterinfo (15-min cache). Het nieuwe is het *agentische, on-demand* ophalen binnen een redenatie — niet een tweede live-bron.
**Acceptatiecriteria:**
- Tool-call gaat server-side via FastAPI (CORS-architectuur, handover #8) — nooit browser-callable.
- Agent logt welke call met welk resultaat de duiding heeft beïnvloed (traceerbaar t.b.v. WL-PROV-1).

#### WL-CHAT-1 · Bevraagbare uitleg-chatbot achter login
**Als PO wil ik** een chatbot waarmee een gebruiker de inrichting en werking kan bevragen **zodat** vragen als "wat is dit, hoe werkt dit?" zelf-bedienbaar worden.
**PO-noot (sequencing, niet volgzaam):** dit komt *na* WL-PROV-1/2. Een chatbot bovenop ontraceerbare bronnen pleit de hallucinatie alleen welsprekender vrij — het werkelijke risico uit de review. De chatbot moet putten uit de provenance-laag, niet uit vrije generatie.
**Acceptatiecriteria:**
- Achter login (tokenkosten-beheersing — een eigen randvoorwaarde van de reviewer).
- Antwoorden zijn gegrond in WL-PROV-bronnen en linken terug naar de uitlegpagina.
- Per gebruiker een token-budget/rate-limit (consistent met de bestaande 60 req/min-lijn).

#### WL-DEMO-1 · Demo/uitlegfilm afstemmen op het herkomstverhaal
**Als PO wil ik** dat `DEMO.md` (~3–4 min) de nieuwe herkomst- en validatie-laag toont **zodat** de film het "show, not tell"-bewijs levert i.p.v. een mooi plaatje.
**Acceptatiecriteria:** script loopt langs WL-PROV-1 en één WL-VAL-2-rapport; max ~4 min; disclaimer in beeld.

---

### ⬛ Governance (WL-GOV)

#### WL-GOV-1 · Expliciete "wat dit wél/niet bewijst"-grens bij externe presentatie
**Als PO wil ik** dat elke externe weergave van WaterLab — deck, demo, dashboard-landing — een vaste grens toont tussen wat het lab aantoont en wat het uitdrukkelijk *niet* is **zodat** het naast een operationeel/MKS-Goud-systeem (RWsOS) kan staan zonder verkeerde verwachtingen te wekken.
**Waarom:** de review niet zélf benoemd, maar het is de keerzijde van het "bullshit"-risico. Zodra dit lab in een RWS-context belandt, is het verschil tussen *"bewijs van de redeneerlijn op één edge-device"* en *"operationeel voorspelsysteem"* het verschil tussen geloofwaardig en ongeloofwaardig. De wél/niet-claim zat al in het slidewerk; deze story verankert hem als herbruikbare regel, niet als eenmalige dia.
**Acceptatiecriteria:**
- Eén canonieke wél/niet-tekst in de repo (`docs/`), hergebruikt door deck, `DEMO.md` en dashboard.
- **Wél:** redeneerlijn end-to-end op generieke bouwstenen; AI als eerste klas op de rekenketen; standaard-interop (PI REST + GraphQL) zonder tweede datapad.
- **Niet:** geen MKS-Goud/PIN-norm; 1 persoon; deels statistisch i.p.v. fysisch; data-gedreven grondwater i.p.v. kwelmodel; indicatief leerlab.
- Positionering staat vast: innovatie-/leersegment van de waardeketenring, niet de operationele keten.
- **Grens met de dev-backlog:** WL-GOV-1 stuurt *communicatie*, niet code. De technische waarborgen ervan leven in WL-VIS-2 (eerlijke labels) en WL-PROV-1 (traceerbaarheid).

---

### ⬛ Communicatie (WL-COMM)

#### WL-COMM-1 · Herinrichting site rond waardestromen en informatiefuncties
**Als PO wil ik** de site herordenen van "9 proeven/tabs" naar de redeneerlijn — waardestromen (W1–W5) en de informatiefuncties die zij raken — in de visuele stijl van de plaat waardestromen **zodat** een bezoeker eerst de *waarde* ziet en de techniek pas als bewijs daaronder.
**Waarom:** de huidige IA is techniek-eerst ("kijk wat ik bouwde"), precies de framing waardoor de review afgleed naar "bullshit". Een waardestroom-eerste indeling vertelt hetzelfde verhaal als slide 1 (proeven geplot op de redeneerlijn) en maakt de site zelf het *show-not-tell*-bewijs. Dit operationaliseert WL-GOV-1 in de schil van de site.
**Acceptatiecriteria:**
- Landing toont de redeneerlijn als ingang: bezoeker kiest een waardestroom (W1 verwachting, W2 historisch/ensemble, W4 multimodel, W5 grondwater/validatie) → ziet welke informatiefuncties die raakt (innemen · schematiseren · rekenen · duiden · samenstellen · ontsluiten · valideren) → komt dan pas bij de onderliggende proef.
- Proef 7 (FEWS) en 8 (GraphQL) staan als **dwarse** platform-/interoplaag, niet als waardestroom (consistent met de mapping; ze als W-stroom tonen breekt de definitie).
- Visuele stijl volgt de plaat: palet navy `0E2841` · teal `156082` · mid-teal `4E87A0` · licht `D7E7EE` · faint `EFF5F8` · oranje accent `C55A11`; koppen serif (Cambria-achtig), body sans (Calibri-achtig); kaart-/band-logica zoals de informatiefunctie-banden op de plaat.
- De wél/niet-grens van **WL-GOV-1** staat zichtbaar op de landing — een waardestroom-IA mag niet de indruk wekken van een operationeel systeem.
- Elke proefpagina linkt naar zijn herkomst (**WL-PROV-1**) en, waar aanwezig, naar zijn skill-score (**WL-VAL-1**).
- Geen tweede datapad: de nieuwe schil is een client op dezelfde API's (dashboard, FEWS, GraphQL blijven verwisselbare clients).
**PO-noot:** dit is een schil-/IA-story, geen herbouw van de proeven. Houd het additief — bestaande tabs/endpoints blijven werken; de redeneerlijn-ingang komt eroverheen, niet ervoor in de plaats.

---

## Geprioriteerde volgorde (PO-advies)

1. **WL-VIS-2** (labels) + **WL-GOV-1** (wél/niet-grens) — kleinste diffs, samen stoppen ze de grootste misleiding: intern in de grafiek, extern in de claim. WL-GOV-1 geldt vanaf de eerstvolgende keer dat je dit lab aan iemand laat zien.
2. **WL-PROV-1** + **WL-PROV-2** — herstelt geloofwaardigheid; deblokkeert de rest.
3. **WL-VAL-1** → **WL-VAL-2** — maakt "hoe goed is het" hard.
4. **WL-VIS-1** — interpretatie aan de kaart.
5. **WL-FC-1 / WL-FC-2** — rekenkern, na herkomst + sysimage.
6. **WL-COMM-1** — herinrichting site rond de redeneerlijn; bouwt op WL-PROV/WL-VAL (anders link je naar lege herkomst) en draagt WL-GOV-1 uit. Schil, geen herbouw.
7. **WL-CHAT-1** → **WL-DEMO-1** — bevraagbaarheid en verhaal, als sluitstuk.
