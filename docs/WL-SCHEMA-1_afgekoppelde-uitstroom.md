# WL-SCHEMA-1 — de uitstroom die van de rivier is afgekoppeld

*Vastgesteld 2026-09-09, tijdens fase C van verwachting v2.*

## Wat er aan de hand is

Het IJssel-model heeft **twee** uitstroompunten in plaats van één. De instroom bij Westervoort bereikt
het punt dat als uitstroom gedocumenteerd staat nooit.

| | cel | coördinaat | uparea | wat het is |
|---|---|---|---|---|
| pit A | (33, 59) | 5.496 O / 53.221 N | 10231 km² | staat in `WL-PROV-2` als stroomgebieds-outlet; **hier meten de historische proeven** |
| pit B | (110, 100) | 5.838 O / 52.579 N | `nan` | hier eindigt het afwateringsnetwerk vanaf Westervoort, ~6 km van de stad Kampen |

Het afwateringsnetwerk vanaf de instroomcel bij Westervoort (181, 138) loopt 131 cellen noordwaarts en
eindigt in **pit B**. Beide pits liggen binnen dezelfde subcatchment. Pit A wordt dus door een ander deel
van het gebied gevoed en ziet uitsluitend lokale neerslag-afvoer.

## Hoe het zich uit

De gauge op pit A gedraagt zich niet als een riviermonding. Over een jaar gemeten forcing:

```
datum        Q_kampen(A)   Q_westervoort   verhouding
2025-09-10          0.1           323.2         0.00
2025-12-09         84.4           395.1         0.21
2026-05-08          0.7           255.0         0.00
2026-06-07         91.6           276.1         0.33
2026-08-06          0.3           110.0         0.00
2026-09-09         74.7           120.2         0.62
```

Grillig, klein, en losgekoppeld van de instroom. Een vullend riviernetwerk stijgt monotoon; dit
oscilleert tussen 0,3 en 194 m³/s terwijl de instroom vloeiend tussen 110 en 395 beweegt.

Op **pit B** gemeten, met exact dezelfde run:

```
2026-09-06   264.1   (instroom 139.4)
2026-09-07   224.8   (instroom 129.4)
2026-09-08   231.6   (instroom 122.1)
2026-09-09   313.5   (instroom 120.2)
```

Hoger dan de instroom, wat klopt: de IJssel wint stroomgebied tussen Westervoort en Kampen. Ter
ijking mat RWS bij Olst op 2026-09-08 ongeveer 138 m³/s; Kampen ligt daar benedenstrooms van. Het model
zit met 232 ruwweg 1,7× boven die meting — hoog voor een ongekalibreerd model, maar de juiste orde en
het juiste teken. Tegenover de 34,6 m³/s van pit A is dat het verschil tussen bruikbaar en betekenisloos.

## Waar het vandaan komt

**Veertig riviercellen hebben `uparea = nan`**, en dat zijn precies de cellen van de PDOK NWB-LDD-correctie
Zwolle→Kampen die in `WL-PROV-2_schematisatie.md` staat beschreven. Die correctie is destijds in de
`wflow_ldd` aangebracht zonder dat `wflow_uparea` opnieuw is afgeleid, en de gecorrigeerde tak eindigt in
een pit in plaats van door te lopen naar pit A.

De `nan`-uparea is daarmee het spoor dat naar de oorzaak wijst: elke cel die de correctie heeft aangeraakt
mist zijn afgeleide waarde.

## Wat er is gedaan

**Alleen de operationele configuratie is aangepast**: `ijssel_config_operational.toml` meet `Q_kampen` en
`h_kampen` voortaan op pit B (5.838 / 52.579). `latest.json` draagt een `gauge`-blok met de coördinaat en
de reden.

Dat is een omweg, geen oplossing. De onderliggende LDD blijft kapot.

**De historische configuraties zijn bewust niet aangepast.** De proeven 4, 5 en 6 blijven meten op pit A,
zodat ze reproduceerbaar blijven tegen hun eerder gepubliceerde uitkomsten. Dat betekent wel dat het
label `Q_kampen` daar een grootheid aanduidt die de IJssel-afvoer niet is — dat moet bij die proeven
vermeld worden, niet stilzwijgend blijven staan.

## Wat dit raakt

- **Proeven 4, 5 en 6** rapporteren `Q_kampen` van pit A. Die reeksen zijn geen IJssel-afvoer bij Kampen.
- **WL-VAL-1** vond bij Kampen een gesimuleerde waterstand met 37,7× de gemeten amplitude en r = 0,52. Dat
  is consistent met een gauge die op een ander, veel kleiner systeem meet. De VAL-1-conclusie ("sim is
  rivierdiepte op ander datum") verklaarde de offset, maar niet de amplitude; dit doet dat wel.
- **WL-PROV-2** documenteert 5.496/53.221 als outlet met uparea 10231 km². Dat klopt als beschrijving van
  de cel, maar niet als beschrijving van waar de IJssel uitkomt.

## Wat er nog moet gebeuren

1. De LDD repareren: pit B doorverbinden en `wflow_uparea` opnieuw afleiden voor de 40 aangeraakte cellen.
   Daarna hoort de omweg hierboven te verdwijnen. Eigen proef, eigen spec.
2. `WL-PROV-2` aanvullen met deze bevinding, zodat de outlet-coördinaat daar niet meer als vanzelfsprekend
   leest.
3. Bij de proeven 4/5/6 op het dashboard vermelden wat `Q_kampen` daar werkelijk is.

## Hoe dit gevonden is

Niet door een foutmelding — wflow draaide alle runs zonder klacht. Het viel op doordat een
plausibiliteitstoets in het implementatieplan expliciet eiste dat het debiet bij Kampen in de orde
100–200 m³/s zou liggen, geijkt op de RWS-meting bij Olst. Dat cijfer kwam er niet uit, en pas het
narekenen van het afwateringsnetwerk cel voor cel bracht de tweede pit aan het licht.

Zonder die toets was er een verwachtingslijn op het dashboard verschenen die er volstrekt geloofwaardig
uitzag.
