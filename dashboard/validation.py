"""WL-VAL-1: skill-metrieken (NSE, KGE, bias) + samenstelling validatie per punt.

Eerlijk principe: een skill-score *alleen* waar een onafhankelijke meting bestaat.
Bij Kampen publiceert RWS geen debiet (alleen waterpeil); vóór ~2000 is er geen
RWS-reeks. Die gevallen komen expliciet als "niet te valideren" terug met reden —
nooit een verzonnen getal. Dit is de validatie-tegenhanger van WL-PROV-1/2.

De skill-functies zijn pure functies (zie tests/test_validation.py).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

ROOT      = Path(__file__).parent.parent
DATA_ROOT = ROOT / "wflow_ijssel" / "data"


# ── skill-metrieken (puur) ──────────────────────────────────────────────────

def _clean(sim, obs):
    sim = np.asarray(sim, dtype=float)
    obs = np.asarray(obs, dtype=float)
    m = np.isfinite(sim) & np.isfinite(obs)
    return sim[m], obs[m]


def nse(sim, obs) -> float:
    """Nash-Sutcliffe efficiency (1 = perfect, 0 = niet beter dan het gemiddelde)."""
    sim, obs = _clean(sim, obs)
    if len(obs) < 2:
        return float("nan")
    denom = float(np.sum((obs - obs.mean()) ** 2))
    if denom == 0:
        return float("nan")
    return float(1.0 - np.sum((sim - obs) ** 2) / denom)


def kge(sim, obs) -> float:
    """Kling-Gupta efficiency (1 = perfect): combineert correlatie, spreiding en bias."""
    sim, obs = _clean(sim, obs)
    if len(obs) < 2:
        return float("nan")
    if obs.std() == 0 or sim.std() == 0 or obs.mean() == 0:
        return float("nan")
    r = float(np.corrcoef(sim, obs)[0, 1])
    alpha = float(sim.std() / obs.std())
    beta = float(sim.mean() / obs.mean())
    return float(1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))


def bias(sim, obs) -> float:
    """Gemiddelde fout (sim − meting), in de eenheid van het punt."""
    sim, obs = _clean(sim, obs)
    if len(obs) == 0:
        return float("nan")
    return float(np.mean(sim - obs))


def pbias(sim, obs) -> float:
    """Procentuele bias: 100·Σ(sim−obs)/Σobs."""
    sim, obs = _clean(sim, obs)
    s = float(np.sum(obs))
    if len(obs) == 0 or s == 0:
        return float("nan")
    return float(100.0 * np.sum(sim - obs) / s)


def rmse(sim, obs) -> float:
    sim, obs = _clean(sim, obs)
    if len(obs) == 0:
        return float("nan")
    return float(np.sqrt(np.mean((sim - obs) ** 2)))


def pearson_r(sim, obs) -> float:
    """Pearson-correlatie: hoe goed valt het patroon/de timing samen (los van amplitude/bias)."""
    sim, obs = _clean(sim, obs)
    if len(obs) < 2 or sim.std() == 0 or obs.std() == 0:
        return float("nan")
    return float(np.corrcoef(sim, obs)[0, 1])


def _r(x, nd=3):
    return None if (x != x) else round(float(x), nd)   # NaN → None


def skill_scores(sim, obs) -> dict:
    sim2, _ = _clean(sim, obs)
    return {
        "n":     int(len(sim2)),
        "r":     _r(pearson_r(sim, obs)),
        "nse":   _r(nse(sim, obs)),
        "kge":   _r(kge(sim, obs)),
        "bias":  _r(bias(sim, obs)),
        "pbias": _r(pbias(sim, obs), 1),
        "rmse":  _r(rmse(sim, obs)),
    }


def anomaly_scores(sim, obs):
    """Skill op de dynamiek: beide reeksen t.o.v. hun eigen gemiddelde.

    Voor grootheden waar sim en meting op een verschillend referentievlak staan
    (bv. wflow-rivierpeil vs RWS m+NAP): de absolute waarde is dan onvergelijkbaar,
    maar het stijgen/dalen (de dynamiek) wél. Geeft scores + het datum-offset +
    de geanomaliseerde reeksen terug.
    """
    sim = np.asarray(sim, dtype=float)
    obs = np.asarray(obs, dtype=float)
    sa = sim - sim.mean()
    oa = obs - obs.mean()
    sc = skill_scores(sa.tolist(), oa.tolist())
    sc.pop("pbias", None)   # betekenisloos op anomalieën (Σ ≈ 0)
    sc.pop("bias", None)    # per constructie ≈ 0 → vervangen door datum_offset
    sc["amplitude_ratio"] = _r(sim.std() / obs.std(), 1) if obs.std() else None
    offset = float(sim.mean() - obs.mean())
    return sc, round(offset, 2), [round(float(v), 3) for v in sa], [round(float(v), 3) for v in oa]


def align(sim_dates, sim_vals, obs_dates, obs_vals):
    """Lijn sim/meting uit op gemeenschappelijke datums; drop paren met een NaN."""
    obs_map = {d: v for d, v in zip(obs_dates, obs_vals)}
    dates, sim, obs = [], [], []
    for d, sv in zip(sim_dates, sim_vals):
        if d not in obs_map:
            continue
        sv_f = float(sv) if sv is not None else float("nan")
        ov_f = float(obs_map[d]) if obs_map[d] is not None else float("nan")
        if np.isfinite(sv_f) and np.isfinite(ov_f):
            dates.append(d)
            sim.append(round(sv_f, 3))
            obs.append(round(ov_f, 3))
    return dates, sim, obs


# ── samenstelling validatie per netwerkpunt ─────────────────────────────────

def _load_json(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def _kampen_peil_2021() -> dict:
    """Gesimuleerd vs gemeten WATERPEIL bij Kampen — een echte model-skill op de hoofd-gauge."""
    point = {
        "id":        "kampen-waterpeil-2021",
        "label":     "Kampen · waterpeil",
        "point":     "Kampen",
        "variable":  "waterpeil",
        "unit":      "m+NAP",
        "period":    "2021-05-01 → 2021-08-31",
        "sim_label": "Gesimuleerd · wflow (dynamiek)",
        "obs_label": "Gemeten · RWS WATHTE (dynamiek)",
        "mode": "anomaly",
        "anomaly_unit": "m t.o.v. gemiddelde",
        "note": ("Het gesimuleerde wflow-rivierpeil staat op een ander referentievlak dan de RWS-meting "
                 "(datum-offset, zie hieronder) — de absolute waarde is dus onvergelijkbaar. Daarom toetsen "
                 "we alleen de dynamiek (stijgen/dalen), beide t.o.v. hun eigen gemiddelde. Kampen ligt "
                 "bovendien aan het Ketelmeer: het IJsselmeerpeil als benedenrand wordt door de "
                 "kinematic-wave routing niet gevangen — een bescheiden score is hier eerlijk."),
    }
    sim = _load_json(DATA_ROOT / "output_2021_real" / "timeseries_kampen.json")
    if not sim or "dates" not in sim or "h_nap" not in sim:
        return {**point, "available": False,
                "reason": "Geen gesimuleerde Kampen-reeks (output_2021_real) gevonden."}
    try:
        from dashboard.forecast import _rws_daily
        s = _rws_daily("kampen.ijssel", "WATHTE", "cm", date(2021, 5, 1), date(2021, 8, 31))
    except Exception as e:  # pragma: no cover
        logger.warning("RWS Kampen-peil fetch faalde: %s", e)
        s = None
    if s is None or len(s) == 0:
        return {**point, "available": False,
                "reason": "RWS-meting (WATHTE Kampen, 2021) nu niet beschikbaar — probeer later opnieuw."}
    obs_dates = [d.strftime("%Y-%m-%d") for d in s.index]
    obs_vals = [float(v) / 100.0 for v in s.values]   # cm → m+NAP
    dates, simv, obsv = align(sim["dates"], sim["h_nap"], obs_dates, obs_vals)
    if len(dates) < 3:
        return {**point, "available": False,
                "reason": "Te weinig overlappende dagen tussen simulatie en meting."}
    scores, offset, sa, oa = anomaly_scores(simv, obsv)
    return {**point, "available": True,
            "datum_offset": offset,   # m: gemiddeld sim − meting (referentievlak-verschil)
            "scores": scores,
            "series": {"dates": dates, "sim": sa, "obs": oa}}


def _westervoort_q_2021() -> dict:
    """Gesynthetiseerde instroom vs gemeten debiet bij Westervoort — kwaliteit van de randvoorwaarde."""
    point = {
        "id":        "westervoort-debiet-2021",
        "label":     "Westervoort · debiet (instroom-randvoorwaarde)",
        "point":     "Westervoort",
        "variable":  "debiet",
        "unit":      "m³/s",
        "period":    "2021-05-01 → 2021-08-31",
        "sim_label": "Gesynthetiseerde instroom",
        "obs_label": "Gemeten · RWS",
        "mode": "absolute",
        "note": ("Westervoort is de modelrandvoorwaarde (zie WL-PROV-2). Dit toetst hoe goed de "
                 "gesynthetiseerde instroom de meting benadert — het is een test van de invoer, "
                 "geen onafhankelijke modelskill stroomafwaarts."),
    }
    sim = _load_json(DATA_ROOT / "output_2021" / "timeseries_westervoort.json")
    meas = _load_json(DATA_ROOT / "output_2021" / "measured_2021.json")
    if not sim or "dates" not in sim or not meas or "westervoort" not in meas:
        return {**point, "available": False,
                "reason": "Geen synthetische instroom- of meetreeks (2021) gevonden."}
    w = meas["westervoort"]
    dates, simv, obsv = align(sim["dates"], sim["q"], w["dates"], w["q"])
    if len(dates) < 3:
        return {**point, "available": False, "reason": "Te weinig overlappende dagen."}
    return {**point, "available": True,
            "scores": skill_scores(simv, obsv),
            "series": {"dates": dates, "sim": simv, "obs": obsv}}


def _not_validatable() -> list:
    """Expliciete matrix: waar en waarom (nog) geen skill-score mogelijk is."""
    return [
        {"id": "kampen-debiet", "label": "Kampen · debiet", "point": "Kampen",
         "variable": "debiet", "unit": "m³/s", "available": False,
         "reason": ("RWS publiceert bij Kampen geen debiet, alleen waterpeil — er is geen gemeten "
                    "debietreeks om de gesimuleerde Kampen-afvoer tegen te toetsen.")},
        {"id": "hoogwater-1995", "label": "Hoogwater 1995 · alle punten", "point": "—",
         "variable": "alle", "unit": "—", "available": False,
         "reason": ("Geen gemeten RWS-reeks: Waterinfo heeft geen data vóór ~2000, en de 1995-instroom "
                    "was zelf gesynthetiseerd (zie WL-PROV-2).")},
        {"id": "droogte-2018", "label": "Droogte 2018 · alle punten", "point": "—",
         "variable": "alle", "unit": "—", "available": False,
         "reason": "Voor dit ERA5-gedreven experiment is geen gemeten reeks opgeslagen om tegen te toetsen."},
        {"id": "forecast-live", "label": "Live 14-daagse verwachting", "point": "Kampen",
         "variable": "debiet", "unit": "m³/s", "available": False,
         "reason": ("De live verwachting loopt vooruit; ze is pas achteraf te scoren tegen de realisatie "
                    "(maandelijkse hindcast — WL-VAL-2). Bovendien is er geen onafhankelijke gemeten "
                    "Kampen-afvoer om de nowcast tegen te leggen.")},
    ]


_CACHE = {"t": 0.0, "data": None}
_TTL = 6 * 3600


def build_validation(force: bool = False) -> dict:
    now = time.time()
    if not force and _CACHE["data"] and now - _CACHE["t"] < _TTL:
        return _CACHE["data"]
    points = [_kampen_peil_2021(), _westervoort_q_2021(), *_not_validatable()]
    n_ok = sum(1 for p in points if p.get("available"))
    data = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "n_validated": n_ok,
        "disclaimer": ("Skill alleen waar een onafhankelijke meting bestaat. "
                       "NSE/KGE: 1 = perfect, 0 = niet beter dan het gemiddelde; "
                       "bias in de eenheid van het punt; pbias in %."),
        "points": points,
    }
    _CACHE.update(t=now, data=data)
    return data
