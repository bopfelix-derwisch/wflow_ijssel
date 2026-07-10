"""POC E — data-assimilatie (EnKF-familie / Ensemble Smoother) op het recessiemodel.

De VAL-2-hindcast toonde dat de Westervoort-recessie systematisch overschat. Hier
assimileren we de recente RWS-meting via een batch-ensemble-Kalman-update op de
recessieparameters (τ, seizoensdoel), corrigeren de verwachting, en bewijzen via de
bestaande hindcast-machinerie dat de fout per horizon daalt.

Eerlijk gelabeld: batch-update over het recente venster = Ensemble Smoother
(EnKF-familie), geen sequentieel filter. De EnKF-update is een pure functie (getest).
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import numpy as np

logger = logging.getLogger(__name__)

FLOOR = 80.0          # m³/s — zelfde ondergrens als forecast._recession
WINDOW_M = 10         # recente meetdagen voor de assimilatie
HORIZON = 14
N_ENS = 60


# ── pure kern ───────────────────────────────────────────────────────────────
def recession_traj(q0, n, tau, target):
    """Recessie van q0 naar 'target' met tijdconstante tau; zelfde formule als
    forecast._recession maar met expliciet doel."""
    t = np.arange(1, n + 1, dtype=float)
    return np.maximum(target + (q0 - target) * np.exp(-t / max(tau, 1e-6)), FLOOR)


def ensemble_assimilate(anchor, obs, q0, horizon=HORIZON, tau0=10.0, target0=240.0,
                        N=N_ENS, seed=0, r_scale=1.0, infl_scale=1.0):
    """Batch-ensemble-Kalman-update van (τ, doel) op het recente meetvenster, daarna
    vooruit-forecast vanaf q0.

    anchor : afvoer M dagen terug (start recente venster)
    obs    : gemeten afvoer op dag 1..M ná anchor (len M)
    q0     : laatste meting (vandaag) — startpunt van de vooruit-forecast
    """
    obs = np.asarray(obs, dtype=float)
    M = len(obs)
    rng = np.random.default_rng(seed)

    # prior-ensemble van parameters. Het seizoensdoel is een klimatologische prior
    # (fysisch redelijk vast) → smalle spreiding; de recessiesnelheid τ absorbeert de
    # recente dynamiek. Een breed doel maakt (τ, doel) onidentificeerbaar op één venster.
    tau = np.clip(rng.normal(tau0, 0.5 * tau0, N), 2.0, 60.0)
    target = np.clip(rng.normal(target0, 0.12 * abs(target0) + 10.0, N), 20.0, None)

    # voorspelde recente trajecten vanaf anchor  (N × M)
    Y = np.array([recession_traj(anchor, M, tau[i], target[i]) for i in range(N)])

    # observatiefout R (diagonaal) + geperturbeerde observaties; r_scale = meetfout-multiplier
    r_diag = ((0.08 * obs + 20.0) * r_scale) ** 2
    obs_pert = obs[None, :] + rng.normal(0.0, np.sqrt(r_diag), (N, M))

    # augmented state Θ = (τ, doel)  (N × 2)
    Theta = np.column_stack([tau, target])
    dTheta = Theta - Theta.mean(0)
    dY = Y - Y.mean(0)
    C_ty = dTheta.T @ dY / (N - 1)                       # 2 × M
    C_yy = dY.T @ dY / (N - 1) + np.diag(r_diag)         # M × M
    K = C_ty @ np.linalg.pinv(C_yy)                      # 2 × M
    Theta_post = Theta + (K @ (obs_pert - Y).T).T        # N × 2

    tau_p = np.clip(Theta_post[:, 0], 2.0, 60.0)
    target_p = np.clip(Theta_post[:, 1], 20.0, None)

    # vooruit-forecast vanaf q0 met posterior-parameters  (N × horizon)
    F = np.array([recession_traj(q0, horizon, tau_p[i], target_p[i]) for i in range(N)])
    free = recession_traj(q0, horizon, tau0, target0)

    # Model-error-inflatie: parameteronzekerheid alléén onderschat de totale voorspelfout
    # (structurele modelfout ontbreekt) → de band zou overconfident zijn. We voegen een met
    # de horizon groeiende, gemiddelde-blijft-gelijk storing toe zodat de band eerlijk is.
    F_mean = F.mean(0)
    h_idx = np.arange(1, horizon + 1)
    add_sigma = F_mean * (0.03 + 0.02 * h_idx) * infl_scale
    F = F_mean + (F - F_mean) + rng.normal(0.0, 1.0, (N, horizon)) * add_sigma

    return {
        "free":  free,
        "mean":  F.mean(0),
        "p10":   np.percentile(F, 10, axis=0),
        "p90":   np.percentile(F, 90, axis=0),
        "tau_prior":    float(tau0),
        "tau_post":     float(np.median(tau_p)),
        "target_prior": float(target0),
        "target_post":  float(np.median(target_p)),
    }


# ── samenstelling: live + hindcast-vergelijking ─────────────────────────────
_CACHE = {"t": 0.0, "data": None}
_TTL = 6 * 3600


def _round(a, nd=1):
    return [round(float(v), nd) for v in a]


_SERIES_CACHE = {"t": 0.0, "days": -1, "data": None}


def _fetch_series(days_back: int):
    """Gecachete dagelijkse RWS-Westervoort-reeks → (idx, dates, vals) of None."""
    now = time.time()
    c = _SERIES_CACHE
    if c["data"] is not None and c["days"] == days_back and now - c["t"] < _TTL:
        return c["data"]
    try:
        from dashboard.forecast import _rws_daily
        import pandas as pd
        end = date.today()
        start = end - timedelta(days=days_back)
        s = _rws_daily("westervoort", "Q", "m3/s", start, end)
        if s is None or len(s) < WINDOW_M + HORIZON + 2:
            return None
        idx = pd.date_range(start, end, freq="D")
        s = s.reindex(idx).interpolate(limit=5).bfill().ffill()
        data = (idx, [d.strftime("%Y-%m-%d") for d in idx],
                np.array([float(v) for v in s.values]))
    except Exception as e:  # pragma: no cover
        logger.warning("assimilatie RWS-fetch faalde: %s", e)
        return None
    _SERIES_CACHE.update(t=now, days=days_back, data=data)
    return data


def build_assimilation(days_back: int = 80, force: bool = False) -> dict:
    now = time.time()
    if not force and _CACHE["data"] and now - _CACHE["t"] < _TTL:
        return _CACHE["data"]

    base = {"point": "Westervoort", "unit": "m³/s", "window_m": WINDOW_M, "horizon_days": HORIZON,
            "method": ("Batch-ensemble-Kalman-update (Ensemble Smoother) van de recessieparameters "
                       "(τ, seizoensdoel) op de laatste %d gemeten RWS-dagen bij Westervoort; daarna "
                       "vooruit-forecast. Realisatie = RWS-meting — zelfde bron als WL-VAL-1/2." % WINDOW_M)}

    from dashboard.forecast import _seasonal_mean
    import pandas as pd
    res = _fetch_series(days_back)
    if res is None:
        return {**base, "available": False,
                "reason": "RWS-meetreeks Westervoort onvoldoende voor assimilatie — probeer later opnieuw."}
    idx, dates, vals = res
    n = len(vals)

    # ── live: assimileer het meest recente venster, forecast vooruit ──
    anchor = vals[n - 1 - WINDOW_M]
    obs = vals[n - WINDOW_M:n]
    q0 = float(vals[-1])
    month = idx[-1].month
    live = ensemble_assimilate(anchor, obs, q0, HORIZON, tau0=10.0,
                               target0=_seasonal_mean(month), N=N_ENS, seed=0)
    fdates = [(idx[-1] + pd.Timedelta(days=i + 1)).strftime("%Y-%m-%d") for i in range(HORIZON)]
    live_out = {
        "recent_dates": dates[n - WINDOW_M:], "recent_obs": _round(obs),
        "fdates": fdates,
        "free": _round(live["free"]), "mean": _round(live["mean"]),
        "p10": _round(live["p10"]), "p90": _round(live["p90"]),
        "tau_prior": round(live["tau_prior"], 1), "tau_post": round(live["tau_post"], 1),
        "target_prior": round(live["target_prior"]), "target_post": round(live["target_post"]),
    }

    # ── hindcast-vergelijking: vrij vs geassimileerd, per horizon ──
    from dashboard.validation import horizon_skill
    fp, fo, flo, fhi = [], [], [], []      # vrij
    ap, ao, alo, ahi = [], [], [], []      # geassimileerd
    for i in range(WINDOW_M, n - HORIZON):
        a = vals[i - WINDOW_M]
        ob = vals[i - WINDOW_M + 1:i + 1]     # M dagen tot en met issue-dag i
        qi = float(vals[i])
        realized = [float(vals[i + 1 + j]) for j in range(HORIZON)]
        res = ensemble_assimilate(a, ob, qi, HORIZON, tau0=10.0,
                                  target0=_seasonal_mean(idx[i].month), N=N_ENS, seed=i)
        fp.append(_round(res["free"])); fo.append(realized)
        flo.append(_round(res["free"])); fhi.append(_round(res["free"]))
        ap.append(_round(res["mean"])); ao.append(realized)
        alo.append(_round(res["p10"])); ahi.append(_round(res["p90"]))

    per_free  = horizon_skill(fp, fo, flo, fhi) if fp else None
    per_assim = horizon_skill(ap, ao, alo, ahi) if ap else None

    def _rmse_at(ph, h):
        return ph["rmse"][ph["horizon"].index(h)] if ph and h in ph["horizon"] else None

    summary = {
        "n_forecasts": len(fp),
        "rmse_free_day7":  _rmse_at(per_free, 7),  "rmse_assim_day7":  _rmse_at(per_assim, 7),
        "rmse_free_day14": _rmse_at(per_free, 14), "rmse_assim_day14": _rmse_at(per_assim, 14),
        "coverage_assim": (round(sum(per_assim["coverage"]) / len(per_assim["coverage"]))
                           if per_assim and per_assim["coverage"] else None),
    }

    data = {**base, "available": True, "generated_at": time.strftime("%Y-%m-%d %H:%M"),
            "window": f"{dates[0]} → {dates[-1]}", "live": live_out,
            "per_horizon_free": per_free, "per_horizon_assim": per_assim, "summary": summary}
    _CACHE.update(t=now, data=data)
    return data


def build_sandbox(tau0=10.0, target0=None, N=60, window=WINDOW_M,
                  r_scale=1.0, infl_scale=1.0, days_back=80) -> dict:
    """Interactieve variant: draai het model uit de video met vrij te kiezen
    parameters, en toon de live-forecast + een snelle vrij-vs-geassimileerd RMSE
    (beperkte hindcast over de laatste ~24 uitgifte-dagen — snel genoeg voor sliders)."""
    from dashboard.forecast import _seasonal_mean
    import pandas as pd
    res = _fetch_series(days_back)
    if res is None:
        return {"available": False, "reason": "RWS-reeks onvoldoende — probeer later opnieuw."}
    idx, dates, vals = res
    n = len(vals)

    # begrenzingen (robuust tegen rare invoer)
    window = int(max(5, min(20, window)))
    N = int(max(20, min(400, N)))
    tau0 = float(max(2.0, min(40.0, tau0)))
    r_scale = float(max(0.1, min(6.0, r_scale)))
    infl_scale = float(max(0.0, min(4.0, infl_scale)))
    if target0 is None or target0 <= 0:
        target0 = float(_seasonal_mean(idx[-1].month))
    else:
        target0 = float(max(20.0, min(600.0, target0)))

    anchor = float(vals[n - 1 - window])
    obs = vals[n - window:n]
    q0 = float(vals[-1])
    lv = ensemble_assimilate(anchor, obs, q0, HORIZON, tau0=tau0, target0=target0,
                             N=N, seed=0, r_scale=r_scale, infl_scale=infl_scale)
    fdates = [(idx[-1] + pd.Timedelta(days=i + 1)).strftime("%Y-%m-%d") for i in range(HORIZON)]

    # snelle hindcast over de laatste ~24 uitgifte-dagen
    fp, ap, obl = [], [], []
    for i in range(max(window, n - HORIZON - 24), n - HORIZON):
        a = float(vals[i - window]); ob = vals[i - window + 1:i + 1]; qi = float(vals[i])
        realized = [float(vals[i + 1 + j]) for j in range(HORIZON)]
        r = ensemble_assimilate(a, ob, qi, HORIZON, tau0=tau0, target0=target0,
                                N=N, seed=i, r_scale=r_scale, infl_scale=infl_scale)
        fp.append(r["free"]); ap.append(r["mean"]); obl.append(realized)

    def _rmse_h(preds, h):
        e = [P[h - 1] - O[h - 1] for P, O in zip(preds, obl)]
        return round(float(np.sqrt(np.mean(np.square(e)))), 1) if e else None

    return {
        "available": True, "unit": "m³/s", "window": window, "N": N,
        "recent_dates": dates[n - window:], "recent_obs": _round(obs),
        "fdates": fdates,
        "free": _round(lv["free"]), "mean": _round(lv["mean"]),
        "p10": _round(lv["p10"]), "p90": _round(lv["p90"]),
        "tau_prior": round(tau0, 1), "tau_post": round(lv["tau_post"], 1),
        "target_prior": round(target0), "target_post": round(lv["target_post"]),
        "r_scale": r_scale, "infl_scale": infl_scale, "n_forecasts": len(fp),
        "rmse_free_day7": _rmse_h(fp, 7), "rmse_assim_day7": _rmse_h(ap, 7),
        "rmse_free_day14": _rmse_h(fp, 14), "rmse_assim_day14": _rmse_h(ap, 14),
    }
