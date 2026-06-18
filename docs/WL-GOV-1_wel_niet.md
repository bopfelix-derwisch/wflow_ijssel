# WL-GOV-1 · Wat Waterlab wél en niet bewijst

**Status:** canoniek · **Datum:** 2026-06-18 · **Backlog:** `docs/BACKLOG_WaterLab_review_TvB.md` (WL-GOV-1)

> **Dit is de single source.** Elke externe weergave van Waterlab — deck, `DEMO.md`,
> dashboard-landing — gebruikt deze tekst, niet een eigen herformulering. Wijzig hier,
> niet in de kopieën. De technische waarborgen ervan leven in **WL-VIS-2** (eerlijke
> grafieklabels) en **WL-PROV-1/2** (traceerbaarheid).

Waterlab staat naast een operationeel/MKS-Goud-systeem (RWsOS) zonder dat te willen
zíjn. Het verschil tussen *"bewijs van de redeneerlijn op één edge-device"* en
*"operationeel voorspelsysteem"* is het verschil tussen geloofwaardig en ongeloofwaardig.
Daarom staat de grens vast.

## Wél

- **Redeneerlijn end-to-end op generieke bouwstenen** — van open data via open-source
  modellen tot AI-duiding, op één edge-computer (NVIDIA Jetson AGX Orin).
- **AI als eerste klas op de rekenketen** — niet als losse chatbot, maar als duidende
  laag op model- en meetoutput (Claude expert-interventie, lokale Qwen-interpretatie).
- **Standaard-interop zonder tweede datapad** — dezelfde data via PI REST (Deltares
  1.25) én GraphQL; elke consumer (dashboard, FEWS, app, webhook) is een verwisselbare
  client op dezelfde bronnen.

## Niet

- **Geen MKS-Goud / PIN-norm** — geen operationele status, geen borging, geen 24/7-keten.
- **1 persoon, experimenteel** — een micro-innovatielab, geen organisatie of dienst.
- **Deels statistisch i.p.v. fysisch** — de live verwachting rust op een statistisch
  recessiemodel, geen gekalibreerde nowcast.
- **Data-gedreven grondwater i.p.v. kwelmodel** — de IJssel↔Veluwe-koppeling is
  data-gedreven (lag-correlatie + lineair reservoir) op één droogte-event (2018), geen
  MODFLOW/iMOD.
- **Indicatief leerlab** — uitkomsten zijn indicatief; voor operationele beslissingen:
  `waterinfo.rws.nl`.

## Positionering

Waterlab hoort in het **innovatie-/leersegment van de waardeketenring**, niet in de
operationele keten. Het toont de redeneerlijn die een modern, API-first, AI-ondersteund
kennisinstrumentarium zou kunnen volgen — als verkenning, niet als vervanging.
