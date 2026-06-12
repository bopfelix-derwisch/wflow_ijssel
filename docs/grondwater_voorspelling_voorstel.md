# Voorstel — grondwaterstand voorspellen (Veluwe-oostflank)

**Datum:** 2026-06-12 · **Status:** voorstel (v1 deels geïmplementeerd)
**Doel:** van de huidige *relatieve* respons-projectie naar een geloofwaardige
**absolute grondwaterstand-voorspelling** per BRO-put, over de komende ~2–4 weken.

---

## De kern van het probleem

Drie obstakels maken absolute voorspelling lastig:

1. **BRO-meetlatentie (~maanden).** De laatste gevalideerde meting is vaak 3–6
   maanden oud (bv. 2025-12-31). Er is dus geen actueel anker; je moet eerst de
   periode *laatste meting → vandaag* reconstrueren (een **nowcast**) vóór je
   vooruit kunt kijken.
2. **Datum/eenheid-mismatch.** De wflow-2018 reeks (`h`) staat op een ander datum
   dan de live RWS-stand; daarom drijft de huidige koppeling op **afvoer (q)**.
3. **Lineaire lag-regressie schaalt niet absoluut.** De helling `dGW/dQ` is op de
   droogte van 2018 gekalibreerd (smal q-bereik). Toegepast over een breed
   q-bereik (winterafvoer) geeft die onrealistische uitslagen. Goed voor een
   14-daagse *perturbatie* (de huidige Δ-projectie), niet voor maanden overbruggen.

**Conclusie:** een lineaire Q→GW-regressie volstaat voor de relatieve respons,
maar niet voor een absolute stand. Daarvoor is een model met *geheugen* nodig.

---

## Voorgestelde aanpak — lineair reservoir (nowcast + forecast)

Modelleer de put als een lineair reservoir dat traag reageert op aanvulling
(neerslag) en op de rivierstand, met terugkeer naar een basisniveau:

```
dGW/dt = −(GW − GW_base)/τ  +  k · recharge(t)  +  m · (river(t) − GW)
```

- **τ** — recessieconstante (geheugen, dagen–weken); per put gekalibreerd.
- **recharge** — uit neerslag (Open-Meteo/ERA5) minus verdamping, met vertraging.
- **river** — RWS-stand/afvoer bij Kampen; levert de kweldruk-term.
- Kalibratie per put op de **volledige BRO-historie** (jaren), niet alleen 2018 —
  dat vangt zowel droge als natte regimes en geeft een echte absolute respons.

### Pijplijn
1. **Nowcast** — integreer het reservoir van de laatste BRO-meting tot vandaag,
   gedreven door de *gemeten* RWS-afvoer + neerslag in die periode (beide
   beschikbaar). Eindwaarde = geschatte actuele stand.
2. **Forecast** — integreer 14 dagen verder met de afvoer- én neerslagverwachting.
3. **Bias-correctie / data-assimilatie** — corrigeer de modelfout op de laatste
   meting (eenvoudige offset, later een Kalman-update) zodat de reeks door de
   echte meting loopt.
4. **Onzekerheidsband** — ensemble over τ/recharge + de neerslagverwachting-spread.

---

## Gefaseerd plan

| Fase | Inhoud | Effort | Status |
|------|--------|--------|--------|
| **v1** | Relatieve Δ-projectie via lag+helling, geankerd op laatste meting (huidige `project_groundwater`); getoond in de verwachtingsgrafiek + interventie | klein | **deels gedaan** |
| **v2** | Lineair-reservoirmodel per put (recharge = neerslag−ET0), gekalibreerd op de BRO-historie (grid-τ + regressie); nowcast laatste-meting→vandaag + forecast +14 d; bias-correctie + band + NSE. `dashboard/reservoir.py`, `/api/grondwater/reservoir`; getoond als absolute reeks in de verwachtingsgrafiek | middel | **GEDAAN (2026-06-12)** |
| **v2b** | Tweede reservoir-term gedreven door de IJssel-stand (RWS WATHTE Kampen, ~4 jr, gedeeld); 2D-grid (τ_recharge, τ_river) + gezamenlijke regressie; graceful fallback naar recharge-only bij RWS-uitval | middel | **GEDAAN (2026-06-12)** — verbetert alle putten (8239 0.82→0.84, 53138 0.49→0.52, 8262 0.17→0.22); 8262 blijft moeilijk (band ±1.0 m → lokale/onttrekkings-invloed) |
| **v3** | Recharge uit ERA5/Open-Meteo met verdamping + bodemberging; validatie op uitgehouden BRO-perioden (Nash–Sutcliffe per put, hindcast) | middel | voorstel |
| **v4** | Fysisch grondwatermodel (iMOD-python / MODFLOW 6) voor de Veluwe-flank; ruimtelijk veld i.p.v. puntreeksen; kwelzone-omkering expliciet | groot | backlog |

**Aanrader:** v2 als eerstvolgende stap — het lost het latentie-anker op en levert
een echte absolute stand, zonder de zwaarte van MODFLOW. v1 staat al live als
indicatieve laag (duidelijk gelabeld).

---

## Validatie

- **Hindcast** op historische droogtes (2018, 2022): voorspel met alleen data tot
  T en vergelijk met gemeten BRO daarna; rapporteer Nash–Sutcliffe + bias per put.
- **Lag-consistentie**: de geschatte τ moet sporen met de empirische lag (6–28 d)
  uit de correlatie-analyse.
- **Cross-put**: putten hoger op de flank horen een langere τ/lag te hebben.

## Databronnen (alle al in gebruik of beschikbaar)
RWS Waterinfo (afvoer/stand, dagreeks-fetch) · Open-Meteo/ERA5 (neerslag, 14-d
verwachting) · BRO GLD via PDOK (historie + laatste meting). Geen nieuwe externe
afhankelijkheden voor v2.
