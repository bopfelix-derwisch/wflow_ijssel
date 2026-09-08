# Verwachting v2 — wflow-nowcast, peil-laag en eerlijke band

*Ontwerp, 2026-09-08. Vervangt de open backlog-items WL-FC-1 en (deels) WL-FC-2.*

## 1 · Doel

De Verwachting-tab (Proef 1) rust nu op een statistisch recessiemodel dat het debiet
bij Westervoort extrapoleert, en toont voor het peil bij Kampen alleen de RWS-meting
plus de officiële RWS-verwachting. Vier dingen gaan veranderen:

1. Het debiet komt uit een operationele **wflow SBM-nowcast** in plaats van uit de recessie.
2. Er komt een **eigen peilverwachting** voor Kampen, 14 dagen vooruit.
3. De systematische **bias van het recessiemodel** (+11 → +92 m³/s over 14 dagen, WL-VAL-2)
   wordt gecorrigeerd, zodat het een eerlijke vergelijkingsbasis blijft.
4. De vaste band van ±(18 + 4·dag)% maakt plaats voor een **meteo-ensemble met
   hindcast-inflatie**.

Het statistische model verdwijnt niet. Het blijft zichtbaar naast wflow, dient als
fallback bij uitval, én levert de randvoorwaarde voor dag 4–14 (zie §3.2).

## 2 · Wat fase 0 heeft opgeleverd

Alle cijfers hieronder zijn gemeten op orin3 op 2026-09-08, niet aangenomen.

### 2.1 De rekenkern was al niet meer geblokkeerd

WL-FC-1 stond twee keer als "geblokkeerd op de sysimage (~2u20 cold start)". Dat klopt
niet meer:

| meting | waarde |
|---|---|
| sysimage bouwen (PackageCompiler, ARM) | 11,2 min → 486 MB |
| koude start **zonder** sysimage | 2 min 15 s |
| koude start **met** sysimage, incl. volledige 62-daagse run | **16,7 s** (Wflow laden: 0,0 s) |
| wflow-rekentijd zelf, 61 dagstappen | 15,1 s |

De ARM-JIT-patches uit `LESSONS_LEARNED.md` §2.1 hebben het cold-startprobleem al
opgelost; dat is nooit teruggekoppeld naar de backlog. De reden dat de story bleef
liggen is prozaïscher: `build_sysimage.jl` en `precompile_wflow.jl` beginnen allebei
met een losse `"""…"""` boven een `using`. Julia leest dat als docstring, `using` is niet
documenteerbaar, en beide scripts falen binnen een seconde. Ze zijn nooit gedraaid.

### 2.2 wflow negeert het tijdvenster uit de config

Fix 6 (`sbm_model.jl`) neemt `nctimes[1]` als starttime, Fix 7 (`Wflow.jl:311`) neemt
`last(reader.dataset_times)` als endtime — allebei bewust, om de LLVM-cascade te
vermijden. Getest met `starttime`/`endtime` op een venster van 10 dagen: er kwamen
61 dagstappen uit, tot het einde van de forcing.

> **Het rekenvenster wordt volledig bepaald door de tijdas van het forcing-bestand.**
> De nowcast stuurt de run dus door de forcing te slicen, nooit door de TOML aan te passen.

Dit gevolg staat nergens opgeschreven; `LESSONS_LEARNED.md` documenteert wél de patches
zelf, maar niet dat ze de config-sleutels buiten werking stellen.

### 2.3 RWS levert randvoorwaarden — maar slechts ~3 dagen

RWS Waterinfo heeft `Q`-verwachtingen op 13 locaties, waaronder Lobith en **Olst**, dat
op de IJssel zelf ligt. Olst heeft óók een `Q`-*meting*: een in-domein debietmeetpunt
waarvan WL-VAL-1 concludeerde dat het niet bestond. Voor de peil-laag zijn
`ketelhaven.ketelmeer`, `swifterbant.ketelmeer` en `kampen.keteldiep` beschikbaar met
zowel meting als verwachting.

Beperking: alle RWS-verwachtingen reiken **~3 dagen** (n=3 op 2026-09-08), niet 14.
Dag 4–14 moeten we zelf leveren.

### 2.4 De peil-relatie klopt, en overtuigend

Getoetst op 1096 dagen (2023-09-09 … 2026-09-08), na sentinel-filtering:

```
h_kampen = −0,0947 + 1,0133·h_ketelmeer + 0,000509·Q_olst
R² = 0,991     RMSE = 2,3 cm
```

| model | R² | RMSE |
|---|---|---|
| `h_kampen = h_ketelmeer` (geen fit) | 0,679 | 13,5 cm |
| `a + b·h_ketelmeer` | 0,890 | 7,9 cm |
| `a + c·Q_olst` | 0,618 | 14,7 cm |
| `a + b·h_ketelmeer + c·Q_olst` | **0,991** | **2,3 cm** |

De coëfficiënt **b ≈ 1,013** bevestigt de opstuwingsredenering: Kampen volgt het
benedenstroomse meerpeil vrijwel 1:1, met het debiet als opzetterm (~0,51 m bij
1000 m³/s). Lag-scan op Q: 0–1 dag optimaal, daarna loopt de fout op.

Dit rechtvaardigt route A en verklaart meteen waarom de directe wflow-route niet kan:
`river_routing = "kinematic_wave"` kent geen opstuwing, en WL-VAL-1 mat bij Kampen een
amplitude van 37,7× de gemeten waarde.

### 2.5 Bijvangst — een bug in bestaande productiecode

`dashboard/forecast.py::_rws_daily` filtert de RWS-sentinel niet. Ontbrekende waarden
komen binnen als `999999999` met `WaarnemingMetadata.Kwaliteitswaardecode == '99'` en
worden mee-gemiddeld in het dagcijfer; één besmet kwartier maakt een dagwaarde van ~6,9
miljoen.

| reeks | sentinel-rijen | aandeel |
|---|---|---|
| `kampen.ijssel` WATHTE | 49 / 161 885 | 0,03 % |
| `ketelhaven.ketelmeer` WATHTE | 423 / 161 847 | 0,26 % |
| `olst` Q | 287 / 162 236 | 0,18 % |
| `westervoort` Q | 102 / 43 381 | 0,24 % |

Dit raakt live code op drie plekken: de peillijn en KPI in `forecast.py`, de 4-jaars
river-driver in `reservoir.py` (v2b-regressie) en de Westervoort-reeks in
`assimilation.py`. Wordt **als aparte fix vóór de rest** opgepakt (§6, fase A), zodat de
VAL-2-hindcastcijfers en de reservoir-NSE's daarna op schone data herbepaald worden.

## 3 · Architectuur

```
   ┌─ Open-Meteo archief      (neerslag/ET0/temp, t/m D-6)
   ├─ Open-Meteo forecast     (deterministisch, D … D+14)
   ├─ Open-Meteo Ensemble API (N leden, D … D+14)
   ├─ RWS Q-verwachting       (Lobith/Olst, dag 1-3)
   └─ recessiemodel           (dag 4-14, bias-gecorrigeerd)
            │
   forcing-bouw (Python)  — punten-raster → modelgrid 300×240
            │
            ├─→ forcing-nowcast.nc   (D-1 … D,  gemeten)
            └─→ forcing-lid-{i}.nc   (D   … D+14, per lid)
            │
   wflow SBM (Julia, --sysimage wflow_sysimage.so)
            │   1× nowcast : instates(D-1) → outstates(D)   ← warme keten
            │   N× forecast: vanaf outstates(D), 14 dagen
            ▼
   wflow_ijssel/data/forecast/latest.json
            │
   peil-laag (Python)   h_kampen = a + b·h_ketelmeer + c·Q(t−1)
            ▼
   dashboard/forecast.py → /api/forecast
```

Het dashboard leest een bestand en rekent niet zelf — één datapad, geen tweede.

### 3.1 Forcing-bouw

De huidige `download_forcing.py` haalt ERA5-Land via CDS: ~5 dagen latentie en geen
verwachting, dus operationeel onbruikbaar. De nieuwe bouwer gebruikt Open-Meteo, dat al
elders in het project wordt gebruikt (`forecast.py`, `reservoir.py`).

Modelgrid: **300×240 cellen à 0,00833°** (~1 km), 5,00–7,50 O / 51,50–53,50 N, 19 530
actieve cellen. Open-Meteo wordt bevraagd op een grover puntenraster (0,25° ≈ 11×9 = 99
punten; zo nodig 0,1°) en bilineair geïnterpoleerd naar het modelgrid. Dat is
vergelijkbaar met de ERA5-Land-resolutie waarop het model is opgezet.

Variabelen: `precip`, `pet`, `temp`, `inflow` — allemaal `(time, y, x)`, net als nu.
`inflow` is nul buiten de Westervoort-cel.

**Randvoorwaarde (`inflow`) per dag:**

| dag | bron |
|---|---|
| D-1 … D | RWS Westervoort `Q` meting |
| D+1 … D+3 | RWS `Q` verwachting **Lobith**, geschaald naar Westervoort |
| D+4 … D+14 | recessiemodel, bias-gecorrigeerd |

De schaalfactor Lobith → Westervoort (de IJssel-tak van de Rijnverdeling, ruwweg 1/9)
wordt empirisch bepaald uit de overlappende meetreeksen, niet als constante aangenomen.

**Olst wordt hier bewust níét gebruikt.** Olst ligt bínnen het modeldomein,
benedenstrooms van de instroomrand; het als randvoorwaarde opvoeren zou het
stroomgebied tussen Westervoort en Olst dubbeltellen. Olst is daarom het
*validatiepunt* — het enige gemeten debiet op de IJssel zelf (§2.3), en daarmee de
eerste echte toets op de wflow-Q die WL-VAL-1 nog niet had.

De overgang tussen bron 2 en 3 wordt over twee dagen gemengd, zodat er geen sprong in
de randvoorwaarde ontstaat.

### 3.2 Warme-state-cyclus

Elke nacht:

1. Bouw `forcing-nowcast.nc` over D-1 … D uit gemeten data.
2. Draai wflow vanaf `instates` (van gisteren) → `outstates(D)`.
3. **Alleen bij exitcode 0**: promoveer `outstates(D)` naar de nieuwe `instates`.
4. Bouw N ensemble-forcings over D … D+14.
5. Draai N forecastruns, elk startend vanaf `outstates(D)`; deze raken de `instates` niet.
6. Schrijf `latest.json` atomisch (schrijf naar `.tmp`, dan `os.replace`).

Stap 3 is de kritieke: één mislukte nacht mag de warme keten niet breken. Bij falen
blijft de oude `instates` staan en draait de volgende nacht met een dag extra forcing.

### 3.3 Peil-laag

Kalibratie op ~3 jaar RWS-daggemiddelden, herkalibratie maandelijks. In voorspelmodus:

| dag | `h_ketelmeer` |
|---|---|
| D+1 … D+3 | RWS-verwachting Ketelhaven |
| D+4 … D+14 | peilbesluit-klimatologie (winter NAP −0,40 m, zomer NAP −0,20 m), met exponentiële overgang vanaf de laatste verwachtingswaarde |

`Q` is de door wflow gesimuleerde afvoer **bij Olst** — hetzelfde punt waarop de relatie
is gekalibreerd (§2.4), zodat coëfficiënt c zijn betekenis houdt.

**Foutbegroting.** Met c = 0,000509 m per m³/s kost een debietfout van 100 m³/s slechts
~5 cm peil, terwijl een fout in het meerpeil ~1:1 doorwerkt. **Voorbij dag 3 domineert
het meerpeil de peilonzekerheid, niet wflow.** De band moet dat weerspiegelen: de
klimatologie-onzekerheid van het IJsselmeerpeil is de grootste term vanaf dag 4.

### 3.4 Onzekerheidsband

`band = spread(ensembleleden) ⊕ modelfout(lead-time)`, waarbij de tweede term empirisch
uit de hindcast komt. Dit volgt de les die `assimilation.py` al vastlegt: alleen
forcing-spreiding geeft een overconfident band (dekking 21 % → 80 % na inflatie). De
dekking wordt getoetst met de bestaande `validation.horizon_skill()`.

### 3.5 Labels

Op de tab, letterlijk:

- **"wflow SBM — gedistribueerd neerslag-afvoermodel"** voor het debiet.
- **"hybride — wflow-debiet + empirische afvoerrelatie"** voor het peil, met de reden
  erbij (kinematische golf kent geen opstuwing; Kampen wordt benedenstrooms gestuurd).

Nooit "wflow-peil". Dat zou precies de VAL-1-fout herhalen.

## 4 · Componenten

| module | verantwoordelijkheid | pure functies (getest) |
|---|---|---|
| `dashboard/rws_client.py` *(nieuw)* | RWS-fetch mét sentinel-filter; enige plek die `rw.get_data` aanroept | `filter_sentinels(df)` |
| `wflow_ijssel/operational/forcing.py` *(nieuw)* | Open-Meteo → modelgrid; randvoorwaarde samenstellen | `blend_boundary()`, `to_model_grid()` |
| `wflow_ijssel/operational/nowcast.py` *(nieuw)* | warme-state-cyclus, wflow-subprocessen, `latest.json` | — (contract-getest) |
| `dashboard/stage.py` *(nieuw)* | peil-laag: kalibratie + toepassing | `fit_stage_relation()`, `apply_stage_relation()`, `lake_climatology()` |
| `dashboard/forecast.py` | leest `latest.json`, valt terug op statistisch model | `bias_correct()` |
| `dashboard/validation.py` | uitgebreid: wflow vs statistisch vs RWS per lead-time | bestaande `horizon_skill()` |

`dashboard/rws_client.py` wordt de enige plek waar RWS wordt opgehaald; `forecast.py`,
`reservoir.py` en `assimilation.py` gaan er doorheen. Dat lost §2.5 structureel op in
plaats van op drie plekken los.

## 5 · Foutafhandeling

| storing | gedrag |
|---|---|
| nachtrun faalt | `latest.json` blijft staan; tab toont wflow-lijn met "verouderd (D-n)"-badge; boven 48 u vervalt de lijn en toont de tab alleen het statistische model met terugvalbanner |
| `instates` corrupt/ontbreekt | nachtrun weigert te promoveren, logt, meldt in `latest.json.status` |
| Open-Meteo uit | geen nieuwe forcing → geen nieuwe run; oude `latest.json` blijft |
| RWS uit | randvoorwaarde valt terug op recessiemodel vanaf dag 1 in plaats van dag 4 |
| Ketelmeer-verwachting uit | peil-laag valt terug op klimatologie vanaf dag 1 |
| sysimage ontbreekt | run draait zonder (2 min 15 s i.p.v. 16,7 s) — waarschuwing, geen fout |

Elke degradatie is zichtbaar op de tab. Stil terugvallen is hier het ergste wat we kunnen
doen: het lab gaat over vertrouwen.

## 6 · Fasering

| fase | inhoud | klaar als |
|---|---|---|
| **A** | sentinel-fix + `rws_client.py`; VAL-2 en reservoir-NSE's herbepaald | tests groen, cijfers vernieuwd, aparte commit |
| **B** | repo-scripts repareren (`build_sysimage.jl`, `precompile_wflow.jl`), ARM-patches vendoren, §2.2 documenteren | `build_sysimage.jl` draait vanaf schoon |
| **C** | forcing-bouw + warme-state-cyclus + cron + `latest.json` | wflow-debietlijn live op de tab |
| **D** | peil-laag | eigen peillijn, 14 dagen, gevalideerd |
| **E** | ensembleband + bias-correctie statistisch model | banddekking getoetst |
| **F** | tab + skill-vergelijking per lead-time | wflow vs statistisch vs RWS zichtbaar |

D kan parallel aan C: de relatie kalibreert op RWS-metingen en heeft wflow pas nodig bij
het toepassen.

**Het eerste implementatieplan dekt A + B.** Dat zijn de fixes en de fundering: de
sentinel-bug raakt bestaande productiecode en moet los verifieerbaar zijn, en zonder
gevendorde ARM-patches is de rekenkern niet reproduceerbaar. C tot en met F krijgen een
eigen plan zodra A en B staan.

## 7 · Testen

Pure functies apart getest, zoals `assimilation.py` en `validation.py` het al doen:
`filter_sentinels`, `blend_boundary`, `fit_stage_relation`, `lake_climatology`,
`bias_correct`, de ensemble-aggregatie.

De wflow-run is een subprocess en wordt op **contract** getest, niet op hydrologische
uitkomst:

- schrijft `latest.json` met het afgesproken schema;
- laat `instates` ongemoeid bij een niet-nul exitcode;
- `latest.json` wordt atomisch vervangen (nooit half gelezen).

Voor de peil-laag komt er een hindcast-toets via `horizon_skill()`, zodat de claim
"RMSE 2,3 cm" niet als kalibratiecijfer blijft staan maar als *voorspel*-cijfer wordt
getoetst — die zal aanzienlijk hoger uitvallen, want dan zitten de wflow-fout en de
meerpeil-onzekerheid erin.

## 8 · Risico's

1. **De ARM-patches staan in `~/.julia/packages/Wflow/mJ7Ug/`, buiten git.** Eén
   `Pkg.update` en ze zijn weg; de sysimage bakt ze in, maar herbouwen vereist ze. Fase B
   moet ze de repo in brengen. Zonder dat is de hele rekenkern één commando van kapot.
2. **De peil-relatie is gekalibreerd op *gemeten* Q bij Olst.** In productie komt Q uit
   wflow, met eigen bias. De relatie moet worden herkalibreerd tegen wflow-Q, anders
   erft het peil de debietbias vergroot met c.
3. **Open-Meteo op 0,25° is grover dan het modelgrid.** Voor een 12 500 km²-stroomgebied
   op dagbasis acceptabel, maar het is een schematisatiekeuze die in de herkomst-keten
   (WL-PROV-1) benoemd moet worden.
4. **De skill-vergelijking kan tegenvallen.** wflow hoeft niet beter te zijn dan de
   recessie op 14 dagen. Dat is een geldige uitkomst en wordt dan ook zo getoond — het
   lab bewijst de redeneerlijn, niet het model.

## 9 · Buiten scope

- **Local-inertial routing met benedenstroomse peilrandvoorwaarde** (route B). Fysisch de
  juiste weg naar een echt wflow-peil, maar vereist bathymetrie, floodplain-schematisatie
  en hercalibratie. Eigen proef, eigen spec.
- **WL-FC-2** (agentische tool-use voor peilmetingen) — apart item.
- Herziening van de assimilatie-tab. Die assimileert bewust het statistische model; wflow
  assimileren is een volgende stap.

## 10 · Uitgevoerd tijdens fase 0

- `wflow_sysimage.so` gebouwd (486 MB, repo-root, `*.so` toegevoegd aan `.gitignore`).
- `wflow_ijssel/ijssel_config_precompile.toml` aangemaakt (untracked) — geïsoleerde
  precompile-config die naar `data/output_precompile/` schrijft en de Proef 4-output met
  rust laat.
- Spike-scripts staan in de scratchpad, niet in de repo.
