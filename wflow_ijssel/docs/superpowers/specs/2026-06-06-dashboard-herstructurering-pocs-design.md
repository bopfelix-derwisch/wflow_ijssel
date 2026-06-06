# Dashboard herstructurering — POC's pagina & FEWS documentatie

**Datum:** 2026-06-06  
**Status:** goedgekeurd  

## Samenvatting

Vier samenhangende wijzigingen aan het Waterlab-dashboard:
1. Nieuwe tab `POC's` met uitgebreide beschrijving van alle proeven
2. `Rijn & IJssel`-tab beperkt tot gebiedsbeschrijving (netwerk, kaart, hoogwatergolven)
3. `FEWS`-tab krijgt een POC-contextblok boven de API Explorer
4. `Intro`-pagina krijgt een kaart voor Proef 7 (FEWS PI REST)

## Navigatie

Tab-volgorde na de wijziging:
```
Waterlab | Rijn & IJssel | POC's | Verwachting | Ensemble AI | Multimodel |
Jan 1995 | Zomer 2018 | Jul 2021 | FEWS | Platform Visie | Roadmap | Info & Analyse
```

`POC's` zit direct na `Rijn & IJssel`: gebied → experimenten → uitvoering.

- Tab-kleur: `active-pocs { background: #00695c; border-color: #4db6ac; }`
- Badge in banner: `🧪 POC's`
- data-year: `"pocs"`

## 1 — Rijn & IJssel (uitleg-panel) — inkorten

### Behouden
- Sectie 0: Leerplatform-framing (drie doelen: modellen, vakgebied, AI)
- Sectie 1: Hoe werkt het Rijn–IJssel systeem? (Pannerdense Kop, verdeling)
- Sectie 2: Wat zie je op de kaart? (kleurschaal, slider, meetpunten)
- Sectie 3: Twee hoogwatergolven: 1995 en 2021

### Verwijderd (→ POC's)
- Sectie 4: Zes experimenten (overzichtstabel)
- Secties 5–7: Proef 1, 2, 3 detailbeschrijvingen
- Secties verder: Proef 4–6 detailbeschrijvingen
- "Backlog & Mogelijke POC's" met kaarten A–F

## 2 — Nieuwe pagina POC's (pocs-panel)

### Structuur

```
[🧪 POC's badge] Waterlab — zeven proeven

Introductieregel: één zin over doel van de proeven

[Overzichtstabel: 7 rijen]
Proef | Naam                        | Technologie              | AI-rol              | Status
1     | 14-daagse verwachting        | wflow SBM + Waterinfo    | Claude interventie  | ✓ live
2     | Ensemble AI                  | wflow + Qwen2.5-32B      | interpretatie       | ✓ live
3     | Multimodel (Ribasim + wflow) | Ribasim + LLM orchestr.  | orkestratie         | ✓ live
4     | Hoogwater jan 1995           | wflow SBM + ERA5         | —                   | ✓ live
5     | Droogte zomer 2018           | wflow SBM + ERA5         | —                   | ✓ live
6     | Hoogwater jul 2021           | wflow SBM + ERA5 + RWS   | —                   | ✓ live
7     | FEWS PI REST                 | FastAPI + PI JSON v1.25  | —                   | ✓ live

[Proef 1 sectie]  (overgenomen uit uitleg-panel + "Wat leerde je" alinea)
[Proef 2 sectie]
[Proef 3 sectie]
[Proef 4 sectie]
[Proef 5 sectie]
[Proef 6 sectie]
[Proef 7 sectie — FEWS PI REST]  (nieuw, uitgebreid)
[Backlog POC's A–F]  (ongewijzigd overgenomen)
```

### Proef 7 — FEWS PI REST (nieuwe sectie)

Bevat:
- **Doel**: Waterlab publiceren als externe FEWS-databron zonder FEWS-aanpassingen
- **Technologie**: FastAPI router, `fews_poc` package, PI JSON v1.25 (Deltares spec)
- **Vier endpoints**: `filters`, `locations`, `parameters`, `timeseries`
- **Wat werkt**: read-only PI JSON conform spec; wflow-tijdreeksen opvraagbaar per locatie/parameter/periode
- **Wat ontbreekt**: authenticatie, schrijf-endpoints, webhooks
- **Knop**: `Bekijk POC →` → navigeert naar FEWS-tab

### Elke proef-sectie bevat
- Korte omschrijving (bestaande tekst, ongewijzigd)
- Technische kern (model, forcing, AI-rol)
- "Wat leerde je" — één of twee zinnen (nieuw, kort)
- Knop `Bekijk [naam] →` naar bijbehorende tab

## 3 — FEWS-tab — POC-contextblok

Nieuw blok boven de bestaande API Explorer:

```
┌─────────────────────────────────────────────────────┐
│ 🔌 POC 7 — Waterlab als FEWS PI REST service        │
│                                                     │
│ Wat is bewezen                                      │
│   Vier standaard-endpoints retourneren PI JSON      │
│   conform Deltares spec v1.25. Elke FEWS-instantie  │
│   kan dit endpoint aanroepen als externe databron.  │
│                                                     │
│ Wat je ziet in deze pagina                          │
│   API Explorer: ruwe JSON-responses live            │
│   Tijdreeksgrafiek: wflow-sim vs RWS Waterinfo      │
│   PI REST hiërarchie: filter→location→parameter     │
│                                                     │
│ Wat nog ontbreekt                                   │
│   Authenticatie · schrijf-endpoints · webhooks      │
│   Dit is een read-only v1 demonstratie.             │
└─────────────────────────────────────────────────────┘
```

Stijl: `fews-poc-context` klasse, teal border-left, donkere achtergrond.

## 4 — Intro-pagina — FEWS kaart (Proef 7)

Positie: na Multimodel-kaart (Proef 3), vóór Jan 1995 (Proef 4).

```
Kleur:    linear-gradient(180deg, #001a13 0%, #002820 100%)
Label:    Proef 7 · FEWS PI REST integratie
Titel:    FEWS PI REST — Waterlab als service
Desc:     wflow-output beschikbaar via vier standaard FEWS-endpoints.
          RWS- en waterschap-systemen kunnen direct verbinden zonder
          aanpassing aan FEWS.
Knop:     Bekijk POC →  (→ switchYear('fews'))
Visueel:  SVG: request-pijl → server-blokje → JSON-response
Badge:    color #4db6ac, border #004d40
```

## Niet gewijzigd

- API Explorer (FEWS-tab)
- Tijdreeksgrafiek (FEWS-tab)
- PI REST hiërarchie (FEWS-tab)
- Alle andere tabs (forecast, ensemble, multimodel, 1995, 2018, 2021, arch, roadmap, info)
- server.py (geen backend-wijzigingen)
- app.js logica voor bestaande tabs

## Bestanden die wijzigen

| Bestand | Wijziging |
|---|---|
| `dashboard/index.html` | uitleg-panel inkorten; pocs-panel toevoegen; fews-panel uitbreiden; intro-kaart toevoegen |
| `dashboard/app.js` | `switchYear('pocs')` case toevoegen; hideAll() uitbreiden; tab-styling |
