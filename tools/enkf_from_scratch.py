#!/usr/bin/env python3
"""Het assimilatiemodel van POC E — van nul herbouwd uit de formules van de
wiskunde-video. Puur numpy, geen repo-afhankelijkheid.

Elke stap verwijst naar de slide in tools/math_slides.html. Doel: aantonen dat de
wiskunde het model volledig vastlegt. Onderaan: (1) een synthetische test die laat
zien dát het werkt, en (2) een vergelijking met de productie-code.
"""
import numpy as np


def recession(q0, n, tau, target):
    """Deel 1 · slide 3 — oplossing van dQ/dt = -(Q-Q_d)/τ:
       Q(t) = Q_d + (Q_0 - Q_d) e^{-t/τ}, met ondergrens 80 m³/s."""
    t = np.arange(1, n + 1)
    return np.maximum(target + (q0 - target) * np.exp(-t / tau), 80.0)


def enkf(anchor, obs, q0, horizon=14, tau0=10.0, target0=240.0, N=60, seed=0):
    """Ensemble-Kalman-update van θ=(τ, Q_d) op het recente venster, dan vooruit."""
    rng = np.random.default_rng(seed)
    M = len(obs)

    # slide 9 — prior-ensemble van parameters θ_i
    tau = np.clip(rng.normal(tau0, 0.5 * tau0, N), 2.0, 60.0)
    tgt = np.clip(rng.normal(target0, 0.12 * abs(target0) + 10.0, N), 20.0, None)

    # slide 10 — ŷ_i = h(θ_i): voorspel het recente venster vanaf de anker-meting
    Y = np.array([recession(anchor, M, tau[i], tgt[i]) for i in range(N)])

    # slide 13 — R = diag((0,08 y + 20)²) ;  slide 14 — y + ε_i
    r = (0.08 * obs + 20.0) ** 2
    obs_pert = obs + rng.normal(0.0, np.sqrt(r), (N, M))

    # slide 11 — covarianties uit het ensemble
    Th = np.column_stack([tau, tgt])
    dTh, dY = Th - Th.mean(0), Y - Y.mean(0)
    C_ty = dTh.T @ dY / (N - 1)
    C_yy = dY.T @ dY / (N - 1) + np.diag(r)

    # slide 12 — gain K = C_θy (C_yy + R)^{-1} ;  slide 14 — update θ_i
    K = C_ty @ np.linalg.pinv(C_yy)
    Th = Th + (K @ (obs_pert - Y).T).T
    tau_p = np.clip(Th[:, 0], 2.0, 60.0)
    tgt_p = np.clip(Th[:, 1], 20.0, None)

    # slide 15 — vooruit vanaf q0 met posterior-parameters
    F = np.array([recession(q0, horizon, tau_p[i], tgt_p[i]) for i in range(N)])
    free = recession(q0, horizon, tau0, target0)

    # slide 16 — model-error-inflatie σ_h = Q̄_h (0,03 + 0,02 h), gemiddelde blijft gelijk
    h = np.arange(1, horizon + 1)
    Fm = F.mean(0)
    F = Fm + (F - Fm) + rng.normal(0.0, 1.0, (N, horizon)) * (Fm * (0.03 + 0.02 * h))

    return free, F.mean(0), np.percentile(F, 10, 0), np.percentile(F, 90, 0)


def _rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


if __name__ == "__main__":
    # (1) Werkt het? Synthetische case: de echte afvoer zakt sneller (τ=5) dan de
    # prior (τ0=10) → de vrije verwachting overschat. Assimilatie moet dat corrigeren.
    tau_true, tgt_true, anchor = 5.0, 200.0, 1000.0
    rng = np.random.default_rng(1)
    obs = recession(anchor, 10, tau_true, tgt_true) + rng.normal(0, 4, 10)
    q0 = float(obs[-1])
    truth = recession(q0, 14, tau_true, tgt_true)
    free, mean, p10, p90 = enkf(anchor, obs, q0, tau0=10.0, target0=tgt_true, seed=0)
    print("(1) synthetische overschatting-case:")
    print(f"    RMSE vrij        = {_rmse(free, truth):6.2f} m³/s")
    print(f"    RMSE geassimileerd= {_rmse(mean, truth):6.2f} m³/s   ({'beter' if _rmse(mean,truth)<_rmse(free,truth) else 'niet beter'})")
