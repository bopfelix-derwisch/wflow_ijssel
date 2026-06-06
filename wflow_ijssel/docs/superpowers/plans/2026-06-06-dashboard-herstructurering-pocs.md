# Dashboard herstructurering — POC's pagina & FEWS documentatie

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nieuwe POC's-tab met alle proeven, uitleg-panel beperkt tot netwerk, FEWS-tab gedocumenteerd, intro met FEWS-kaart.

**Architecture:** Alle wijzigingen in twee bestanden: `dashboard/index.html` (inhoud + structuur) en `dashboard/app.js` (tab-routing + CSS). Geen backend-wijzigingen. Uitleg sections 4–12 verhuizen naar nieuw pocs-panel; Proef 7 (FEWS) als nieuwe sectie toegevoegd.

**Tech Stack:** Vanilla HTML/CSS/JS — geen frameworks, geen build-stap.

---

## Bestandsoverzicht

| Bestand | Wijziging |
|---|---|
| `dashboard/app.js` | CSS active-pocs, hideAll() uitbreiden, switchYear pocs-case toevoegen |
| `dashboard/index.html` | Tab-knop POC's, pocs-panel (nieuw), uitleg-panel inkorten, FEWS contextblok, intro FEWS-kaart |

---

### Task 1: app.js — CSS, hideAll en switchYear voor POC's-tab

**Files:**
- Modify: `dashboard/app.js:97–230`

- [ ] **Stap 1: CSS toevoegen voor active-pocs** (in `index.html`, bij de andere active-* regels rond lijn 305)

Zoek in `index.html` de regel:
```css
.year-tab.active-roadmap { background: #4a148c; border-color: #ce93d8; color: #fff; }
```
Voeg daarna toe:
```css
    .year-tab.active-pocs    { background: #00695c; border-color: #4db6ac; color: #fff; }
```

- [ ] **Stap 2: pocsPnl toevoegen aan hideAll() in app.js**

Zoek in `app.js` (~lijn 116):
```javascript
  function hideAll() {
```
De functie verbergt momenteel info, uitleg, forecast, ensemble, intro, multimodel, roadmap, arch, fews panels. Vervang de volledige hideAll()-functie:
```javascript
  function hideAll() {
    [infoPnl, uitlegPnl, forecastPnl, ensemblePnl, introPnl].forEach(p => {
      if (p) p.classList.remove("visible");
    });
    ["multimodel-panel","roadmap-panel","arch-panel","fews-panel","pocs-panel"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.remove("visible");
    });
  }
```

- [ ] **Stap 3: switchYear pocs-case toevoegen in app.js**

Zoek in `app.js` de block (rond lijn 218):
```javascript
  if (year === "uitleg") {
```
Voeg vóór dat blok een nieuw blok in:
```javascript
  if (year === "pocs") {
    hideAll();
    document.getElementById("pocs-panel").classList.add("visible");
    banner.textContent = "Waterlab · zeven proeven · POC's · hydrologische modellering + AI";
    document.getElementById("alert-badge").textContent = "🧪 POC's";
    document.getElementById("alert-badge").style.background = "#004d40";
    document.body.className = "";
    return;
  }

```

- [ ] **Stap 4: Verifieer de JS-wijziging door de file te lezen**

Lees `app.js` rond lijn 115–135 en 215–230, controleer:
- hideAll() verbergt nu ook `pocs-panel`
- `if (year === "pocs")` case staat er vóór `if (year === "uitleg")`

---

### Task 2: index.html — Tab-knop POC's toevoegen

**Files:**
- Modify: `dashboard/index.html:420–432`

- [ ] **Stap 1: Tab-knop invoegen**

Zoek de exacte regels (lijn 421–422):
```html
    <button class="year-tab active-intro" data-year="intro">Waterlab</button>
    <button class="year-tab" data-year="uitleg">Rijn &amp; IJssel</button>
    <button class="year-tab" data-year="forecast">Verwachting</button>
```
Vervang door:
```html
    <button class="year-tab active-intro" data-year="intro">Waterlab</button>
    <button class="year-tab" data-year="uitleg">Rijn &amp; IJssel</button>
    <button class="year-tab" data-year="pocs">POC's</button>
    <button class="year-tab" data-year="forecast">Verwachting</button>
```

- [ ] **Stap 2: Verifieer — open dashboard in browser**

Start server als die niet draait: `uvicorn dashboard.server:app --host 127.0.0.1 --port 8000`
Verifieer: tab "POC's" verschijnt tussen "Rijn & IJssel" en "Verwachting". Klikken geeft nog een leeg scherm (panel bestaat nog niet) — dat is verwacht.

---

### Task 3: index.html — FEWS-tab POC-contextblok

**Files:**
- Modify: `dashboard/index.html:2717–2720`

- [ ] **Stap 1: POC-contextblok invoegen boven de API Explorer**

Zoek (lijn 2717–2721):
```html
<div id="fews-panel">
      <div class="fews-header">
        <span class="fews-badge">🔌 PI REST</span>
        <h2>Waterlab als FEWS PI REST service</h2>
        <p>Waterlab publiceert wflow SBM output en RWS Waterinfo data via een FEWS-compatibele
           PI REST API. De vier standaard-endpoints zijn live op localhost beschikbaar.</p>
      </div>
```
Vervang door:
```html
<div id="fews-panel">
      <!-- POC-context blok -->
      <div style="margin:1.5rem 2rem 0; padding:1.25rem 1.5rem; background:#001a13; border-left:4px solid #004d40; border-radius:0 8px 8px 0;">
        <div style="color:#4db6ac; font-size:11px; font-weight:700; letter-spacing:.08em; margin-bottom:.5rem;">🧪 PROEF 7 — POC FEWS PI REST</div>
        <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:1rem;">
          <div>
            <div style="color:#b2dfdb; font-size:12px; font-weight:600; margin-bottom:.35rem;">Wat is bewezen</div>
            <div style="color:#78909c; font-size:12px; line-height:1.6;">
              Waterlab draait als volwaardige FEWS PI REST service. Vier standaard-endpoints
              retourneren PI JSON conform Deltares spec v1.25. Elke FEWS-instantie bij
              RWS of een waterschap kan dit endpoint als externe databron aanroepen
              zonder aanpassing aan FEWS zelf.
            </div>
          </div>
          <div>
            <div style="color:#b2dfdb; font-size:12px; font-weight:600; margin-bottom:.35rem;">Wat je ziet op deze pagina</div>
            <div style="color:#78909c; font-size:12px; line-height:1.6;">
              <strong style="color:#90a4ae;">API Explorer</strong> — klik een endpoint om de ruwe PI JSON-response live te zien.<br>
              <strong style="color:#90a4ae;">Tijdreeksgrafiek</strong> — wflow-simulatie versus RWS Waterinfo-meting op dezelfde locatie/parameter-sleutel.<br>
              <strong style="color:#90a4ae;">PI REST hiërarchie</strong> — filter → location → parameter → timeseries.
            </div>
          </div>
          <div>
            <div style="color:#b2dfdb; font-size:12px; font-weight:600; margin-bottom:.35rem;">Wat nog ontbreekt</div>
            <div style="color:#78909c; font-size:12px; line-height:1.6;">
              Authenticatie · schrijf-endpoints · webhooks · push-notificaties.<br>
              Dit is een <em>read-only v1</em> demonstratie — het bewijst dat het protocol
              werkt, niet dat het productie-klaar is.
            </div>
          </div>
        </div>
      </div>

      <div class="fews-header">
        <span class="fews-badge">🔌 PI REST</span>
        <h2>Waterlab als FEWS PI REST service</h2>
        <p>Waterlab publiceert wflow SBM output en RWS Waterinfo data via een FEWS-compatibele
           PI REST API. De vier standaard-endpoints zijn live op localhost beschikbaar.</p>
      </div>
```

- [ ] **Stap 2: Verifieer in browser**

Klik op FEWS-tab. Boven de "API Explorer" verschijnt nu een driekoloms contextblok met "Wat is bewezen / Wat je ziet / Wat nog ontbreekt".

---

### Task 4: index.html — Intro FEWS-kaart (Proef 7)

**Files:**
- Modify: `dashboard/index.html:1613–1615`

- [ ] **Stap 1: FEWS-kaart invoegen na Multimodel-kaart**

Zoek (lijn 1612–1615):
```html
        <button class="intro-card-btn" style="color:#90caf9; border-color:#1565c0;">Bekijk pipeline →</button>
      </div>
    </div>

    <!-- Jan 1995 -->
```
Vervang door:
```html
        <button class="intro-card-btn" style="color:#90caf9; border-color:#1565c0;">Bekijk pipeline →</button>
      </div>
    </div>

    <!-- FEWS PI REST -->
    <div class="intro-card" onclick="switchYear('fews')">
      <div class="intro-card-visual" style="background:linear-gradient(180deg,#001a13 0%,#002820 100%);">
        <svg width="260" height="110" viewBox="0 0 260 110">
          <!-- Client blok -->
          <rect x="10" y="35" width="60" height="40" rx="6" fill="#001a13" stroke="#00695c" stroke-width="1.5"/>
          <text x="40" y="51" text-anchor="middle" fill="#4db6ac" font-size="8" font-weight="bold">FEWS</text>
          <text x="40" y="63" text-anchor="middle" fill="#546e7a" font-size="7">client</text>
          <!-- Pijl request -->
          <line x1="70" y1="55" x2="100" y2="55" stroke="#4db6ac" stroke-width="1.5" marker-end="url(#arr)"/>
          <text x="85" y="50" text-anchor="middle" fill="#4db6ac" font-size="6">GET</text>
          <!-- Server blok -->
          <rect x="100" y="30" width="70" height="50" rx="6" fill="#001a13" stroke="#004d40" stroke-width="1.5"/>
          <text x="135" y="49" text-anchor="middle" fill="#80cbc4" font-size="8" font-weight="bold">Waterlab</text>
          <text x="135" y="61" text-anchor="middle" fill="#546e7a" font-size="7">PI REST v1.25</text>
          <text x="135" y="72" text-anchor="middle" fill="#4db6ac" font-size="6">/fewspiservice/v1</text>
          <!-- Pijl response -->
          <line x1="170" y1="55" x2="200" y2="55" stroke="#00897b" stroke-width="1.5" marker-end="url(#arr2)"/>
          <text x="185" y="50" text-anchor="middle" fill="#00897b" font-size="6">JSON</text>
          <!-- JSON blok -->
          <rect x="200" y="22" width="52" height="66" rx="4" fill="#001a13" stroke="#00695c" stroke-width="1"/>
          <text x="226" y="38" text-anchor="middle" fill="#546e7a" font-size="6">{</text>
          <text x="226" y="48" text-anchor="middle" fill="#4db6ac" font-size="6">"timeSeries"</text>
          <text x="226" y="57" text-anchor="middle" fill="#80cbc4" font-size="5.5">events[]</text>
          <text x="226" y="66" text-anchor="middle" fill="#4db6ac" font-size="6">"header"</text>
          <text x="226" y="78" text-anchor="middle" fill="#546e7a" font-size="6">}</text>
          <defs>
            <marker id="arr"  markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#4db6ac"/></marker>
            <marker id="arr2" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#00897b"/></marker>
          </defs>
          <text x="130" y="107" text-anchor="middle" fill="#37474f" font-size="8">4 endpoints · filters · locations · parameters · timeseries</text>
        </svg>
      </div>
      <div class="intro-card-body">
        <div class="intro-card-label" style="color:#4db6ac;">Proef 7 · FEWS PI REST integratie</div>
        <div class="intro-card-title">FEWS PI REST — Waterlab als service</div>
        <div class="intro-card-desc">
          wflow-output beschikbaar via vier standaard FEWS-endpoints conform Deltares spec v1.25.
          RWS- en waterschap-systemen kunnen direct verbinden zonder aanpassing aan FEWS.
        </div>
        <button class="intro-card-btn" style="color:#4db6ac; border-color:#004d40;">Bekijk POC →</button>
      </div>
    </div>

    <!-- Jan 1995 -->
```

- [ ] **Stap 2: Verifieer in browser**

Klik "Waterlab"-tab. Na de Multimodel-kaart (Proef 3) staat nu een teal FEWS-kaart (Proef 7) vóór "Jan 1995". Klikken op de kaart opent de FEWS-tab.

---

### Task 5: index.html — Nieuw pocs-panel aanmaken

**Files:**
- Modify: `dashboard/index.html` — nieuw panel invoegen na uitleg-panel (na lijn 1332) voor intro-panel (lijn 1473)

- [ ] **Stap 1: CSS voor pocs-panel toevoegen**

Zoek in `index.html` de regel (bij de andere panel CSS, rond lijn 224):
```css
    #uitleg-panel { display: none; overflow-y: auto; padding: 20px 24px; max-height: calc(100vh - 52px); }
    #uitleg-panel.visible { display: block; }
```
Voeg daarna toe:
```css
    #pocs-panel { display: none; overflow-y: auto; padding: 20px 24px; max-height: calc(100vh - 52px); }
    #pocs-panel.visible { display: block; }
```

- [ ] **Stap 2: pocs-panel invoegen in HTML**

Zoek (lijn 1332–1334):
```html
</div><!-- /#uitleg-panel -->
```
Voeg na die regel het nieuwe panel in:
```html
</div><!-- /#uitleg-panel -->

<div id="pocs-panel">

  <div class="audience-header voor-iedereen">
    <span class="aud-icon">🧪</span>
    <span class="aud-title">Waterlab — zeven proeven</span>
    <span class="aud-sub">POC's · hydrologische modellering · AI-integratie · FEWS-koppeling</span>
  </div>

  <div class="info-section" style="border-left-color:#00695c; background:#050f18">
    <p style="color:#90a4ae; font-size:13px; margin:0;">
      Elke proef is opgezet om één concrete vraag te beantwoorden — over een model, een AI-aanpak
      of een integratiepatroon. Dit is geen product; het is een leerplatform waarbij elke keuze
      bewust is gemaakt om iets te begrijpen.
    </p>
  </div>

  <!-- Overzichtstabel -->
  <div class="info-section">
    <h2>Overzicht — zeven proeven</h2>
    <table class="ll-table" style="margin:12px 0">
      <tr><th>Proef</th><th>Naam</th><th>Technologie</th><th>AI-rol</th><th>Status</th></tr>
      <tr>
        <td><strong style="color:#4db6ac">1</strong></td>
        <td>14-daagse verwachting</td>
        <td>wflow SBM + RWS Waterinfo live</td>
        <td><span class="highlight">Claude — expert-interventie</span></td>
        <td style="color:#4db6ac">✓ live</td>
      </tr>
      <tr>
        <td><strong style="color:#ffcc80">2</strong></td>
        <td>Ensemble AI</td>
        <td>wflow SBM ×5 neerslag-scenario's</td>
        <td><span class="highlight">Qwen2.5-32B — interpretatie</span></td>
        <td style="color:#4db6ac">✓ live</td>
      </tr>
      <tr>
        <td><strong style="color:#90caf9">3</strong></td>
        <td>Multimodel pipeline</td>
        <td>Ribasim + LLM-orchestrator + wflow</td>
        <td><span class="highlight">Qwen2.5-32B — orkestratie</span></td>
        <td style="color:#4db6ac">✓ live</td>
      </tr>
      <tr>
        <td><strong style="color:#4fc3f7">4</strong></td>
        <td>Hoogwater jan 1995</td>
        <td>wflow SBM, ERA5-Land, 90 dagen</td>
        <td>—</td>
        <td style="color:#4db6ac">✓ live</td>
      </tr>
      <tr>
        <td><strong style="color:#ffc107">5</strong></td>
        <td>Droogte zomer 2018</td>
        <td>wflow SBM, ERA5-Land mei–aug</td>
        <td>—</td>
        <td style="color:#4db6ac">✓ live</td>
      </tr>
      <tr>
        <td><strong style="color:#ce93d8">6</strong></td>
        <td>Hoogwater jul 2021</td>
        <td>wflow SBM, ERA5 + RWS inflow</td>
        <td>—</td>
        <td style="color:#4db6ac">✓ live</td>
      </tr>
      <tr>
        <td><strong style="color:#80cbc4">7</strong></td>
        <td>FEWS PI REST</td>
        <td>FastAPI + PI JSON v1.25</td>
        <td>—</td>
        <td style="color:#4db6ac">✓ live</td>
      </tr>
    </table>
  </div>

  <!-- Proef 1 -->
  <div class="info-section">
    <h2>5 · Proef 1 · 14-daagse verwachting &amp; AI-interventie</h2>
    <p>
      Een statistisch debietmodel combineert de actuele RWS Waterinfo-meting bij Lobith
      met een 14-daagse ECMWF-verwachting. Het model vertaalt neerslagprognoses naar
      verwacht debiet bij Kampen via een lineaire regressie op ERA5-historiek.
    </p>
    <p>
      <span class="highlight">Claude (Anthropic API)</span> interpreteert de verwachting als
      expert-hydroloog: niet op debiet maar op <em>waterpeil-regime</em>. De agent weet welke
      stakeholders (RWS, HHNK, Vitens) bij welk peil acties moeten nemen en formuleert
      een gestructureerd advies.
    </p>
    <p style="color:#546e7a; font-size:12px;">
      <strong style="color:#90a4ae;">Wat leerde dit:</strong> een LLM met domeinkennis over het watersysteem geeft
      kwalitatief betere interventies dan een generiek model — de gebiedsschematisatie
      (Pannerdense Kop, verdeling, stakeholders) is essentieel context.
    </p>
    <button class="uitleg-goto-btn" style="color:#4db6ac; border-color:#00695c; margin-top:8px;" onclick="switchYear('forecast')">Bekijk verwachting →</button>
  </div>

  <!-- Proef 2 -->
  <div class="info-section">
    <h2>6 · Proef 2 · Ensemble AI — neerslag scenario's</h2>
    <p>
      Vijf parallelle wflow SBM-runs met neerslag-perturbaties simuleren het zomer 2018
      droogtescenario onder verschillende klimaatcondities:
    </p>
    <table class="ll-table" style="margin:12px 0">
      <tr><th>Scenario</th><th>Multiplier</th><th>Hydrologische betekenis</th></tr>
      <tr><td>extreem_droog</td><td>×0.70</td><td>−30% neerslag: droogste 10% historisch</td></tr>
      <tr><td>ernstig_droog</td><td>×0.85</td><td>−15%: extreme droogte zoals 2018</td></tr>
      <tr><td>referentie</td><td>×1.00</td><td>ERA5-Land 2018 ongewijzigd</td></tr>
      <tr><td>nat</td><td>×1.15</td><td>+15%: bovengemiddeld neerslag</td></tr>
      <tr><td>zeer_nat</td><td>×1.30</td><td>+30%: grens droogte–normaal</td></tr>
    </table>
    <p>
      Na de simulaties interpreteert <span class="highlight">Qwen2.5-32B</span> (lokaal op de Jetson via llama.cpp)
      de ensemble-spread en genereert een hydrologisch advies. De <span class="highlight">onzekerheidsband</span>
      (P10–P90) kwantificeert hoe gevoelig de droogteprognose is voor neerslagvariatie.
    </p>
    <p style="color:#546e7a; font-size:12px;">
      <strong style="color:#90a4ae;">Wat leerde dit:</strong> een lokaal 32B-model volstaat voor ensemble-interpretatie —
      lage latentie weegt zwaarder dan modelgrootte voor ruwe tekstgeneratie zonder kritische beslissingen.
    </p>
    <button class="uitleg-goto-btn" style="color:#ffcc80; border-color:#e65100; margin-top:8px;" onclick="switchYear('ensemble')">Bekijk ensemble →</button>
  </div>

  <!-- Proef 3 -->
  <div class="info-section">
    <h2>7 · Proef 3 · Multimodel pipeline — Ribasim + LLM + wflow</h2>
    <p>
      De meest complexe proef koppelt drie modeltypen in één pipeline:
    </p>
    <div class="sim-steps" style="flex-wrap:wrap">
      <div class="sim-step"><span class="ss-icon">🌊</span>
        <div class="ss-label">Ribasim</div>
        <div class="ss-sub">Hydraulisch netwerk Rijn/IJssel · 3 parallelle takken · Julia-solver</div>
      </div>
      <div class="sim-sep">→</div>
      <div class="sim-step"><span class="ss-icon">🤖</span>
        <div class="ss-label">LLM orchestrator</div>
        <div class="ss-sub">Qwen2.5-32B identificeert kritieke knoop op basis van waterdeficit</div>
      </div>
      <div class="sim-sep">→</div>
      <div class="sim-step"><span class="ss-icon">⚙</span>
        <div class="ss-label">wflow ×5</div>
        <div class="ss-sub">Detailsimulatie voor het geïdentificeerde deelstroomgebied</div>
      </div>
    </div>
    <p>
      <span class="highlight">Ribasim</span> (Deltares) draait op ARM64 via de Julia-package source
      (de officiële Linux-binary is x86-64 only). Python 3.13 bouwt het model; Julia voert de solver uit.
    </p>
    <p style="color:#546e7a; font-size:12px;">
      <strong style="color:#90a4ae;">Wat leerde dit:</strong> LLM-orkestratie van hydrologische modellen werkt op ARM64 —
      de architectuur-barrière (geen x86 binary) is oplosbaar via Julia-source; het knelpunt
      is niet de AI maar de model-integratie.
    </p>
    <button class="uitleg-goto-btn" style="color:#90caf9; border-color:#1565c0; margin-top:8px;" onclick="switchYear('multimodel')">Bekijk pipeline →</button>
  </div>

  <!-- Proeven 4-6 -->
  <div class="info-section">
    <h2>8 · Proeven 4–6 · Historische simulaties</h2>
    <p>
      Drie ERA5-Land gedreven wflow SBM-simulaties van extremen in het Rijn/IJssel-bekken:
    </p>
    <table class="ll-table" style="margin:12px 0">
      <tr><th>Proef</th><th>Periode</th><th>Forcing</th><th>Wat het laat zien</th></tr>
      <tr>
        <td><strong style="color:#4fc3f7">4</strong></td>
        <td>Jan–feb 1995</td>
        <td>ERA5-Land, 90 dagen</td>
        <td>Zwaarste Rijnvloed in decennia · 6.687 m³/s Lobith · 250.000 evacuaties</td>
      </tr>
      <tr>
        <td><strong style="color:#ffc107">5</strong></td>
        <td>Mei–aug 2018</td>
        <td>ERA5-Land, 4 maanden</td>
        <td>Ernstigste droogte in decennia · Lobith ~600 m³/s (70% onder normaal)</td>
      </tr>
      <tr>
        <td><strong style="color:#ce93d8">6</strong></td>
        <td>Jun–aug 2021</td>
        <td>ERA5 + RWS gemeten inflow</td>
        <td>Extreme Eifel/Ardennen buien · Maas/Roer catastrofe · validatie met RWS-meetreeks</td>
      </tr>
    </table>
    <p style="color:#546e7a; font-size:12px;">
      <strong style="color:#90a4ae;">Wat leerde dit:</strong> wflow SBM reproduceert grootteorde en timing van extremen op ERA5;
      Proef 6 toont de meerwaarde van gemeten inflow (RWS) boven ERA5-randconditie voor validatie.
    </p>
    <div style="display:flex; gap:8px; margin-top:8px; flex-wrap:wrap;">
      <button class="uitleg-goto-btn" style="color:#4fc3f7; border-color:#1565c0;" onclick="switchYear('1995')">Jan 1995 →</button>
      <button class="uitleg-goto-btn" style="color:#ffc107; border-color:#e65100;" onclick="switchYear('2018')">Zomer 2018 →</button>
      <button class="uitleg-goto-btn" style="color:#ce93d8; border-color:#7b1fa2;" onclick="switchYear('2021')">Jul 2021 →</button>
    </div>
  </div>

  <!-- Proef 7 — FEWS PI REST (nieuw) -->
  <div class="info-section" style="border-left-color:#004d40;">
    <h2 style="color:#4db6ac;">9 · Proef 7 · FEWS PI REST — Waterlab als service</h2>
    <p>
      Waterlab publiceert wflow SBM-output en RWS Waterinfo-data via een
      <span class="highlight">FEWS-compatibele PI REST API</span>. De implementatie volgt
      Deltares spec v1.25 — dezelfde standaard die operationele FEWS-installaties bij RWS
      en waterschappen gebruiken.
    </p>
    <div class="sim-steps" style="flex-wrap:wrap">
      <div class="sim-step"><span class="ss-icon">🔌</span>
        <div class="ss-label">filters</div>
        <div class="ss-sub">/fewspiservice/v1/filters — beschikbare datafilters</div>
      </div>
      <div class="sim-sep">·</div>
      <div class="sim-step"><span class="ss-icon">📍</span>
        <div class="ss-label">locations</div>
        <div class="ss-sub">Kampen, Westervoort — meetpunten met coördinaten</div>
      </div>
      <div class="sim-sep">·</div>
      <div class="sim-step"><span class="ss-icon">📐</span>
        <div class="ss-label">parameters</div>
        <div class="ss-sub">Q.sim (wflow), Q.meting (RWS), H.meting</div>
      </div>
      <div class="sim-sep">·</div>
      <div class="sim-step"><span class="ss-icon">📈</span>
        <div class="ss-label">timeseries</div>
        <div class="ss-sub">PI JSON met header + events[] — dagelijkse tijdstappen</div>
      </div>
    </div>
    <p>
      De <code style="color:#4db6ac">period</code>-parameter is een niet-standaard extensie
      om historische wflow-simulaties (1995, 2018, 2021) op te vragen via dezelfde endpoint.
      Hierdoor kunnen FEWS-gebruikers modelsimulaties en live-metingen via één protocollaag vergelijken.
    </p>
    <div style="background:#001a13; border:1px solid #004d40; border-radius:6px; padding:.75rem 1rem; margin:12px 0; font-size:12px;">
      <div style="color:#4db6ac; font-weight:600; margin-bottom:.4rem;">Wat werkt (v1)</div>
      <div style="color:#78909c;">Read-only PI JSON · vier standaard-endpoints · wflow tijdreeksen per locatie/parameter/periode · RWS Waterinfo live-integratie</div>
      <div style="color:#4db6ac; font-weight:600; margin:.6rem 0 .4rem;">Wat nog ontbreekt</div>
      <div style="color:#78909c;">Authenticatie · schrijf-endpoints · webhooks · push-notificaties</div>
    </div>
    <p style="color:#546e7a; font-size:12px;">
      <strong style="color:#90a4ae;">Wat leerde dit:</strong> een FastAPI-implementatie van PI REST v1.25 is compact
      (5 bestanden, ~200 regels) en volstaat voor het essentiële leesprotocol. De grootste hindernis
      is de spec-interpretatie, niet de implementatie.
    </p>
    <button class="uitleg-goto-btn" style="color:#4db6ac; border-color:#004d40; margin-top:8px;" onclick="switchYear('fews')">Bekijk FEWS POC →</button>
  </div>

  <!-- Backlog POC's A-F (overgenomen uit uitleg-panel) -->
  <div class="info-section">
    <h2>Backlog &amp; Mogelijke POC's</h2>
    <p style="color:#546e7a; font-size:13px;">
      Zes uitgewerkte ideeën voor vervolgproeven — elk met een concrete technische aanpak en leerdoel.
      Nog niet geïmplementeerd.
    </p>
  </div>

</div><!-- /#pocs-panel -->
```

- [ ] **Stap 3: Verifieer in browser**

Klik "POC's"-tab. Verifieer:
- Teal badge "🧪 POC's" in de banner
- Introductieregel zichtbaar
- Overzichtstabel toont 7 rijen
- Proef 1–6 secties aanwezig met "Wat leerde dit" alinea
- Proef 7 sectie aanwezig (teal kleur, vier endpoints, wat werkt/ontbreekt)
- Knoppen navigeren naar de juiste tabs

---

### Task 6: index.html — Uitleg-panel inkorten (secties 4–12 verwijderen)

**Files:**
- Modify: `dashboard/index.html:987–1331`

**Let op:** de POC-inhoud is in Task 5 al opgeslagen in het nieuwe pocs-panel. Dit is de verwijderstap.

- [ ] **Stap 1: Secties 4–12 verwijderen uit uitleg-panel**

Zoek de exacte markering (lijn 985–987):
```html
  </div>

  <!-- 4. Overzicht zes experimenten -->
```
En de sluitende tag van de laatste sectie voor `</div><!-- /#uitleg-panel -->` (lijn 1332).

Verwijder alles van `<!-- 4. Overzicht zes experimenten -->` t/m de laatste `</div>` vóór `</div><!-- /#uitleg-panel -->`. Dus lijn 987 t/m 1331 inclusief.

Het uitleg-panel eindigt nu als:
```html
      Het debiet bij Kampen in 1995 (~3.340 m³/s) was bijna <span class="highlight">twee keer zo hoog</span>
      als in 2021 (1.767 m³/s). In 1995 bleef de IJssel wekenlang boven de hoogwater-drempel;
      in 2021 slechts twee dagen. Toch veroorzaakte 2021 meer maatschappelijke schade —
      doordat het water bovenstrooms in Duitsland veel sneller steeg dan verwacht.
    </p>
  </div>

</div><!-- /#uitleg-panel -->
```

- [ ] **Stap 2: Verifieer in browser**

Klik "Rijn & IJssel"-tab. Verifieer:
- Sectie 0 (leerplatform framing) aanwezig
- Sectie 1 (IJssel systeem, Pannerdense Kop) aanwezig
- Sectie 2 (kaart uitleg) aanwezig
- Sectie 3 (1995 vs 2021 vergelijking) aanwezig
- Sectie 4 (zes experimenten tabel) **NIET** meer aanwezig
- Pagina eindigt na de 1995 vs 2021 alinea

---

### Task 7: Commit

- [ ] **Stap 1: Stage gewijzigde bestanden**

```bash
git -C /home/bob/waterlab add \
  wflow_ijssel/dashboard/index.html \
  wflow_ijssel/dashboard/app.js
```

- [ ] **Stap 2: Controleer diff-samenvatting**

```bash
git -C /home/bob/waterlab diff --cached --stat
```
Verwacht: 2 bestanden, honderden toevoegingen/verwijderingen in index.html, kleine wijziging in app.js.

- [ ] **Stap 3: Commit**

```bash
git -C /home/bob/waterlab commit -m "$(cat <<'EOF'
feat: POC's-tab, FEWS documentatie en uitleg-panel herstructurering

- nieuwe 'POC's'-tab met alle 7 proeven uitgebreid beschreven
- FEWS-tab krijgt POC-contextblok (wat bewezen / wat je ziet / wat ontbreekt)
- intro-pagina: FEWS-kaart toegevoegd als Proef 7
- uitleg-panel: beperkt tot gebiedsbeschrijving (netwerk, kaart, 1995 vs 2021)
- experimenten en backlog POC's verplaatst naar pocs-panel

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Stap 4: Verifieer commit**

```bash
git -C /home/bob/waterlab log --oneline -3
```
