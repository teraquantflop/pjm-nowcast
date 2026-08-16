"""
Lightweight online HMM with diagonal-Gaussian emissions.

This is intentionally simple so the prototype can run for days
and you can watch entropy / separation evolve.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List, Tuple

import numpy as np

from config import (
    EWM_ALPHA,
    EWM_ALPHA_WARM,
    WARM_OBS,
    EMISSION_VAR_FLOOR,
    FEATURE_DIM,
    N_STATES,
)
from .state import FeatureVector, Snapshot
from .zonal import update_zonal_and_peak
from .histograms import append_history


def update(snap: Snapshot, feats: FeatureVector) -> Snapshot:
    """
    One online filter + parameter update step.
    Returns a new Snapshot (mutates the input for convenience but also returns it).
    """
    K = snap.n_states or N_STATES
    D = FEATURE_DIM
    x = feats.to_emission_vec()  # shape (D,) — already scaled

    # ---------- 1. ensure arrays exist ----------
    if snap.transition_counts is None:
        snap.transition_counts = [[0.5] * K for _ in range(K)]
    if snap.emission_mean is None:
        # start near zero in scaled space (typical operating region after scaling)
        snap.emission_mean = [[0.0] * D for _ in range(K)]
    if snap.emission_var is None:
        # modest initial variance in scaled space so likelihoods are informative
        snap.emission_var = [[4.0] * D for _ in range(K)]
    if snap.state_posteriors is None:
        snap.state_posteriors = [1.0 / K] * K
    if snap.residual_abs_ewm is None:
        snap.residual_abs_ewm = [0.0] * D

    trans = np.array(snap.transition_counts, dtype=float)          # (K, K)
    mean = np.array(snap.emission_mean, dtype=float)               # (K, D)
    var = np.array(snap.emission_var, dtype=float)                 # (K, D)
    prev_post = np.array(snap.state_posteriors, dtype=float)       # (K,)

    # ---------- 2. predict (forward with transition matrix) ----------
    row_sums = trans.sum(axis=1, keepdims=True)
    row_sums = np.maximum(row_sums, 1e-12)
    A = trans / row_sums                                            # (K, K)
    pred = prev_post @ A                                            # (K,)

    # ---------- 3. emission likelihoods (diagonal Gaussian) ----------
    log_lik = np.zeros(K)
    for k in range(K):
        ll = 0.0
        for d in range(D):
            v = max(var[k, d], EMISSION_VAR_FLOOR)
            diff = x[d] - mean[k, d]
            ll += -0.5 * (math.log(2 * math.pi * v) + (diff * diff) / v)
        log_lik[k] = ll

    # numerically stable posterior
    log_post = np.log(np.maximum(pred, 1e-12)) + log_lik
    log_post -= log_post.max()
    post = np.exp(log_post)
    post /= post.sum()

    # ---------- 4. soft transition count update ----------
    expected_trans = np.outer(prev_post, post)
    trans = trans + expected_trans

    # ---------- 5. online emission parameter update (soft assignment) ----------
    # warm start: higher learning rate for the first WARM_OBS observations
    alpha = EWM_ALPHA_WARM if snap.n_obs < WARM_OBS else EWM_ALPHA
    for k in range(K):
        w = float(post[k])
        if w < 1e-6:
            continue
        for d in range(D):
            old_m = mean[k, d]
            new_m = (1 - alpha * w) * old_m + (alpha * w) * x[d]
            old_v = var[k, d]
            resid2 = (x[d] - new_m) ** 2
            new_v = (1 - alpha * w) * old_v + (alpha * w) * resid2
            mean[k, d] = new_m
            var[k, d] = max(new_v, EMISSION_VAR_FLOOR)

    # ---------- 6. residual scale tracker (for crude tails) ----------
    # residuals are in scaled feature space
    k_star = int(post.argmax())
    for d in range(D):
        resid = abs(x[d] - mean[k_star, d])
        snap.residual_abs_ewm[d] = (
            (1 - alpha) * snap.residual_abs_ewm[d] + alpha * resid
        )

    # ---------- 7. also maintain simple global EWM of raw features ----------
    _update_ewm(snap, feats)

    # ---------- write back HMM core ----------
    snap.transition_counts = trans.tolist()
    snap.emission_mean = mean.tolist()
    snap.emission_var = var.tolist()
    snap.state_posteriors = post.tolist()
    snap.last_features = feats
    snap.n_obs += 1
    snap.updated_at = datetime.now(timezone.utc).astimezone()
    snap.last_entropy = float(-np.sum(post * np.log(np.maximum(post, 1e-12))))
    snap.notes = f"k*={k_star}"

    # ---------- 8. zonal spread / peak / conditional vol (side track) ----------
    update_zonal_and_peak(snap, feats)

    # ---------- 9. intraday history for deviation histograms ----------
    append_history(snap, feats)

    return snap


def _update_ewm(snap: Snapshot, feats: FeatureVector) -> None:
    alpha = EWM_ALPHA
    mapping = {
        "load_mw": feats.load_mw,
        "load_ramp": feats.load_ramp,
        "price": feats.price,
        "price_vol": feats.price_vol,
    }
    for name, val in mapping.items():
        slot = snap.ewm.get(name)
        if slot is None:
            snap.ewm[name] = {"mean": val, "var": 0.0, "n": 1.0}
            continue
        old_m = slot["mean"]
        new_m = (1 - alpha) * old_m + alpha * val
        slot["var"] = (1 - alpha) * slot["var"] + alpha * (val - new_m) ** 2
        slot["mean"] = new_m
        slot["n"] = slot.get("n", 0.0) + 1.0


def predictive_summary(snap: Snapshot) -> dict:
    """
    Cheap summary of current beliefs for logging / later metrics.
    Mixture moments are converted back from scaled emission space
    into MW and $/MWh for human-readable output.
    """
    if not snap.state_posteriors or not snap.emission_mean:
        return {"status": "uninitialized"}

    from config import LOAD_CENTER_MW, LOAD_SCALE_MW, PRICE_SCALE

    post = np.array(snap.state_posteriors)
    mean = np.array(snap.emission_mean)
    var = np.array(snap.emission_var)

    # mixture mean & variance in scaled space
    mix_mean_load_s = float(post @ mean[:, 0])
    mix_mean_price_s = float(post @ mean[:, 2])

    mix_var_load_s = float(
        post @ var[:, 0] + post @ (mean[:, 0] - mix_mean_load_s) ** 2
    )
    mix_var_price_s = float(
        post @ var[:, 2] + post @ (mean[:, 2] - mix_mean_price_s) ** 2
    )

    # invert scaling for display
    mix_mean_load = mix_mean_load_s * LOAD_SCALE_MW + LOAD_CENTER_MW
    mix_std_load = math.sqrt(max(mix_var_load_s, 0.0)) * LOAD_SCALE_MW
    mix_mean_price = mix_mean_price_s * PRICE_SCALE
    mix_std_price = math.sqrt(max(mix_var_price_s, 0.0)) * PRICE_SCALE

    return {
        "entropy": snap.last_entropy,
        "dominant_state": int(post.argmax()),
        "posteriors": [round(float(p), 4) for p in post],
        "mix_mean_load": mix_mean_load,
        "mix_std_load": mix_std_load,
        "mix_mean_price": mix_mean_price,
        "mix_std_price": mix_std_price,
        "n_obs": snap.n_obs,
        "warm": snap.n_obs < WARM_OBS,
    }
