"""Peilverwachting Kampen — hybride: wflow-debiet + empirische afvoerrelatie.

Waarom niet gewoon het peil uit wflow: het model levert `river_water__depth`,
de rivierdiepte boven de bedding, niet meters NAP. En belangrijker,
`river_routing = "kinematic_wave"` kent géén opstuwing, terwijl het peil bij
Kampen juist wordt gedomineerd door de kombergingswerking vanuit Ketelmeer en
IJsselmeer plus windopzet. WL-VAL-1 mat daar een amplitude van 37,7× de
gemeten waarde. Een peillijn rechtstreeks uit wflow ziet er fysisch uit en is
het niet.

Wat hier gebeurt (gemeten op 1096 dagen, 2023-09 … 2026-09):

    h_kampen = a + b·h_ketelmeer + c·Q_olst
             = −0,094 + 1,015·h_ketelmeer + 0,000507·Q      R² = 0,990, RMSE 2,3 cm

De coëfficiënt b ≈ 1 zegt het hele verhaal: Kampen volgt het benedenstroomse
meerpeil vrijwel één op één, met het debiet als opzetterm (~0,5 m bij 1000 m³/s).
Alleen het meerpeil geeft RMSE 13,5 cm, alleen het debiet 14,7 cm — samen 2,3.

Het debiet komt uit de nachtelijke wflow-run bij Olst. Dat is verdedigbaar omdat
wflow daar accuraat is: op 2026-09-09 gaf het 139 m³/s tegen een RWS-meting van
138 en 4% boven de officiële verwachting. Bij Kampen wijkt hetzelfde model
sterk af (zie docs/WL-SCHEMA-1) — vandaar Olst als aandrijver, niet Kampen.

Het meerpeil komt voor dag 1–3 uit de officiële RWS-verwachting; verder vooruit
publiceert RWS niets en valt het terug op de **gemeten maandklimatologie** van
Ketelhaven. Dat is bewust geen hardgecodeerd peilbesluit: de klimatologie wordt
uit de meetreeks zelf afgeleid, zodat hij verifieerbaar is en meebeweegt.

Foutbegroting: met c = 0,0005 kost een debietfout van 100 m³/s maar ~5 cm peil,
terwijl een fout in het meerpeil één op één doorwerkt. **Voorbij dag 3 bepaalt
het IJsselmeerpeil de onzekerheid, niet wflow.** De band weerspiegelt dat: hij
verbreedt met de klimatologische spreiding van het meerpeil, die klein is in de
zomer (~5 cm) en groot in de winter (~28 cm, storm en windopzet).

Label op de tab: "hybride — wflow-debiet + empirische afvoerrelatie", nooit
"wflow-peil". Anders herhalen we de fout uit WL-VAL-1: een getal dat er fysisch
uitziet maar uit een andere bron komt dan de naam suggereert.
"""
from __future__ import annotations

import logging
import statistics
import time
from datetime import date, timedelta

import numpy as np

logger = logging.getLogger(__name__)

KAMPEN = "kampen.ijssel"
KETELHAVEN = "ketelhaven.ketelmeer"
OLST = "olst"

CALIB_YEARS = 3
MIN_CALIB_DAGEN = 200
BLEND_DAYS = 2          # overgang RWS-verwachting → klimatologie
_TTL = 6 * 3600
_cache: dict = {}


# ── pure kern ────────────────────────────────────────────────────────────────

def fit_stage_relation(h_kampen, h_lake, q) -> dict:
    """Kleinste-kwadraten-fit van h_kampen = a + b·h_lake + c·q.

    Alle drie de reeksen zijn even lang en op dezelfde dagen uitgelijnd.
    Retourneert de coëfficiënten plus R², de residustandaardafwijking (de basis
    voor de band) en het aantal dagen waarop gefit is.
    """
    y = np.asarray(h_kampen, dtype=float)
    xl = np.asarray(h_lake, dtype=float)
    xq = np.asarray(q, dtype=float)
    if not (len(y) == len(xl) == len(xq)):
        raise ValueError("reeksen moeten even lang zijn")
    if len(y) < 3:
        raise ValueError(f"te weinig dagen om te fitten: {len(y)}")

    A = np.column_stack([xl, xq, np.ones(len(y))])

    # Zijn meerpeil en debiet over dit venster vrijwel collineair, dan is de fit
    # exact (R² ≈ 1) terwijl b en c individueel betekenisloos zijn: lstsq kiest
    # dan een willekeurige minimum-norm-oplossing. Precies de faalvorm die dit
    # lab het meest vreest — plausibel ogend en fout. Liever luid falen.
    cond = float(np.linalg.cond(A))
    if not np.isfinite(cond) or cond > 1e8:
        raise ValueError(
            f"meerpeil en debiet zijn over dit venster te sterk gecorreleerd "
            f"(conditiegetal {cond:.3g}); b en c zijn dan niet te scheiden en de "
            "coëfficiënten zouden betekenisloos zijn ondanks een hoge R²")

    coef = np.linalg.lstsq(A, y, rcond=None)[0]
    resid = y - A @ coef
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return {
        "b": float(coef[0]), "c": float(coef[1]), "a": float(coef[2]),
        "r2": round(1 - float(np.sum(resid ** 2)) / ss_tot, 4) if ss_tot > 0 else None,
        "resid_std": float(np.std(resid)),
        "n": len(y),
    }


def apply_relation(coef: dict, h_lake, q) -> list:
    """Pas de relatie toe. Ontbreekt een van beide drijvers, dan None."""
    uit = []
    for hl, qq in zip(h_lake, q):
        if hl is None or qq is None:
            uit.append(None)
        else:
            uit.append(coef["a"] + coef["b"] * float(hl) + coef["c"] * float(qq))
    return uit


def monthly_climatology(dates, values) -> dict:
    """{maand: (gemiddelde, standaardafwijking)} uit de meetreeks zelf.

    Bewust empirisch en niet uit het peilbesluit: zo is de klimatologie te
    controleren tegen de data, en beweegt hij mee als het beheer verandert.
    """
    per_maand: dict = {}
    for d, v in zip(dates, values):
        if v is None:
            continue
        per_maand.setdefault(int(str(d)[5:7]), []).append(float(v))
    uit = {}
    for m, vs in per_maand.items():
        if len(vs) >= 5:
            uit[m] = (statistics.mean(vs),
                      statistics.pstdev(vs) if len(vs) > 1 else 0.0)
    return uit


def lake_series(dates, rws_map: dict, clim: dict, blend_days: int = BLEND_DAYS):
    """Meerpeil per dag: RWS-verwachting waar die er is, daarna klimatologie.

    Retourneert (waarden, spreidingen, bronnen). De spreiding is 0 zolang we op
    de officiële verwachting zitten en gelijk aan de klimatologische
    standaardafwijking zodra we daarop terugvallen — dat is precies de term die
    de band voorbij dag 3 laat verbreden.

    De overgang wordt over `blend_days` gemengd, anders springt het meerpeil op
    de dag dat de RWS-verwachting ophoudt.
    """
    if not dates:
        raise ValueError("dates mag niet leeg zijn")

    laatste_rws = max((d for d in dates if d in rws_map), default=None)
    waarden, spreidingen, bronnen = [], [], []
    for d in dates:
        maand = int(str(d)[5:7])
        klim = clim.get(maand)
        if d in rws_map:
            waarden.append(float(rws_map[d]))
            spreidingen.append(0.0)
            bronnen.append("rws")
            continue
        if klim is None:
            waarden.append(None); spreidingen.append(None); bronnen.append("geen")
            continue

        k_val, k_sd = klim
        if laatste_rws is not None and blend_days > 0 and d > laatste_rws:
            stappen = sum(1 for x in dates if laatste_rws < x <= d)
            if stappen <= blend_days:
                w = stappen / (blend_days + 1)
                waarden.append(float(rws_map[laatste_rws]) * (1 - w) + k_val * w)
                spreidingen.append(k_sd * w)
                bronnen.append("overgang")
                continue
        waarden.append(k_val)
        spreidingen.append(k_sd)
        bronnen.append("klimatologie")
    return waarden, spreidingen, bronnen


def band(coef: dict, lake_sd, z: float = 1.96) -> list:
    """Halve bandbreedte per dag.

    Twee onafhankelijke termen, kwadratisch opgeteld: de residuspreiding van de
    relatie zelf (~2,3 cm) en de onzekerheid in het meerpeil, die via b (≈1)
    vrijwel ongedempt doorwerkt. De debietonzekerheid laten we bewust weg: met
    c ≈ 0,0005 kost zelfs 100 m³/s maar ~5 cm, klein tegen de rest.
    """
    uit = []
    for sd in lake_sd:
        if sd is None:
            uit.append(None)
            continue
        var = coef["resid_std"] ** 2 + (coef["b"] * float(sd)) ** 2
        uit.append(z * float(np.sqrt(var)))
    return uit


# ── samenstelling ────────────────────────────────────────────────────────────

def _series_map(loc, grootheid, eenheid, start, end, proces="meting", schaal=1.0):
    from dashboard import rws_client
    r = rws_client.daily_series(loc, grootheid, eenheid, start, end, proces)
    if r is None:
        return {}
    return {ts.strftime("%Y-%m-%d"): float(v) * schaal for ts, v in r.items()}


def build_stage_forecast(wflow: dict, today=None) -> dict:
    """Peilverwachting Kampen op basis van de wflow-Olst-reeks."""
    today = today or date.today()
    sleutel = today.isoformat()
    hit = _cache.get(sleutel)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]

    leeg = {"available": False, "method": "hybride — wflow-debiet + empirische afvoerrelatie"}

    if not (wflow.get("available") and wflow.get("q_olst") and wflow.get("dates")):
        uit = {**leeg, "note": "Geen wflow-Olst-reeks beschikbaar; zonder debiet "
                               "geen peilverwachting."}
        _cache[sleutel] = (time.monotonic(), uit)
        return uit

    start = today - timedelta(days=365 * CALIB_YEARS)
    hk = _series_map(KAMPEN, "WATHTE", "cm", start, today, schaal=0.01)
    hl = _series_map(KETELHAVEN, "WATHTE", "cm", start, today, schaal=0.01)
    qo = _series_map(OLST, "Q", "m3/s", start, today)

    gedeeld = sorted(set(hk) & set(hl) & set(qo))
    if len(gedeeld) < MIN_CALIB_DAGEN:
        uit = {**leeg, "note": f"Te weinig overlappende meetdagen om te kalibreren "
                               f"({len(gedeeld)}, minimaal {MIN_CALIB_DAGEN})."}
        _cache[sleutel] = (time.monotonic(), uit)
        return uit

    coef = fit_stage_relation([hk[d] for d in gedeeld],
                              [hl[d] for d in gedeeld],
                              [qo[d] for d in gedeeld])
    clim = monthly_climatology(gedeeld, [hl[d] for d in gedeeld])

    rws_lake = _series_map(KETELHAVEN, "WATHTE", "cm", today,
                           today + timedelta(days=20), proces="verwachting", schaal=0.01)

    dates = wflow["dates"]
    lake, lake_sd, bronnen = lake_series(dates, rws_lake, clim)
    h = apply_relation(coef, lake, wflow["q_olst"])
    halve = band(coef, lake_sd)

    uit = {
        "available": any(v is not None for v in h),
        "method": leeg["method"],
        "dates": dates,
        "h": [round(v, 3) if v is not None else None for v in h],
        "lower": [round(v - b, 3) if v is not None and b is not None else None
                  for v, b in zip(h, halve)],
        "upper": [round(v + b, 3) if v is not None and b is not None else None
                  for v, b in zip(h, halve)],
        "lake_source": bronnen,
        "coef": {k: round(v, 6) if isinstance(v, float) else v for k, v in coef.items()},
        "rws_dagen": sum(1 for b in bronnen if b == "rws"),
        "note": ("Peil bij Kampen uit de gekalibreerde relatie "
                 "h = a + b·meerpeil + c·debiet. Het debiet komt uit wflow bij Olst, "
                 "het meerpeil voor de eerste dagen uit de officiële RWS-verwachting "
                 "en daarna uit de gemeten maandklimatologie van Ketelhaven."),
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    logger.info("peilrelatie: R²=%s RMSE=%.1f cm op %d dagen; %d dagen RWS-meerpeil",
                coef["r2"], coef["resid_std"] * 100, coef["n"], uit["rws_dagen"])
    _cache[sleutel] = (time.monotonic(), uit)
    return uit
