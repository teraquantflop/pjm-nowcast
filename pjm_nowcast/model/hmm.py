"""Lightweight online HMM with diagonal-Gaussian emissions (internal)."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import List, Set, Tuple

import numpy as np

from pjm_nowcast.model.histograms import append_history
from pjm_nowcast.model.params import (
    EMISSION_VAR_FLOOR,
    EWM_ALPHA,
    EWM_ALPHA_WARM,
    FEATURE_DIM,
    FEATURE_NAMES,
    LOAD_CENTER_MW,
    LOAD_SCALE_MW,
    N_STATES,
    PRICE_SCALE,
    PRICE_VOL_DIM,
    PRICE_VOL_SCALE,
    TRANSITION_PSEUDO_COUNT,
    WARM_OBS,
)
from pjm_nowcast.model.state import FeatureVector, Snapshot
from pjm_nowcast.model.zonal import update_zonal_and_peak

log = logging.getLogger("pjm_nowcast.model.hmm")


def _sanitize_x(feats: FeatureVector, snap: Snapshot) -> Tuple[np.ndarray, Set[int]]:
    """Replace non-finite emission entries with 0.0 (except price_vol).

    price_vol is rolling realized LMP std in $/MWh, not annualized Black vol.
    Treat <=0 / non-finite as missing: use last good, else skip that dim
    (do not feed 0.0 into the emission vector).
    """
    x = np.array(feats.to_emission_vec(), dtype=float)
    skip_dims: Set[int] = set()
    replaced: List[str] = []

    pv = float(feats.price_vol)
    pv_missing = bool(getattr(feats, "price_vol_missing", False)) or (
        not math.isfinite(pv) or pv <= 0.0
    )
    if pv_missing:
        carried = pv if (math.isfinite(pv) and pv > 0.0) else None
        last_good = carried
        if last_good is None:
            lg = snap.last_good_price_vol
            if lg is not None and math.isfinite(lg) and lg > 0.0:
                last_good = float(lg)
        if last_good is not None:
            x[PRICE_VOL_DIM] = last_good / PRICE_VOL_SCALE
        else:
            skip_dims.add(PRICE_VOL_DIM)
            log.info("price_vol missing; skipping emission dim %d", PRICE_VOL_DIM)

    for d in range(len(x)):
        if d in skip_dims:
            continue
        if d == PRICE_VOL_DIM and pv_missing:
            continue
        if not math.isfinite(float(x[d])):
            name = FEATURE_NAMES[d] if d < len(FEATURE_NAMES) else f"d{d}"
            replaced.append(name)
            x[d] = 0.0

    if replaced:
        log.warning("Non-finite emission dims replaced with 0.0: %s", ",".join(replaced))
    return x, skip_dims


def _sanitize_prev_post(prev_post: np.ndarray, K: int) -> np.ndarray:
    p = np.asarray(prev_post, dtype=float).reshape(-1)
    if p.size != K or not np.all(np.isfinite(p)):
        return np.full(K, 1.0 / K)
    s = float(p.sum())
    if s <= 0.0 or abs(s - 1.0) > 0.05 or np.any(p < 0.0):
        return np.full(K, 1.0 / K)
    return p / s


def _sanitize_emission_cells(mean: np.ndarray, var: np.ndarray) -> None:
    mean_bad = ~np.isfinite(mean)
    var_bad = ~np.isfinite(var) | (var <= 0.0)
    if np.any(mean_bad):
        mean[mean_bad] = 0.0
    if np.any(var_bad):
        var[var_bad] = 4.0


def _sanitize_trans(trans: np.ndarray) -> np.ndarray:
    trans = np.array(trans, dtype=float, copy=True)
    bad = ~np.isfinite(trans)
    if np.any(bad):
        trans[bad] = TRANSITION_PSEUDO_COUNT
    return trans


def _price_vol_usable(feats: FeatureVector) -> bool:
    pv = float(feats.price_vol)
    return (
        (not bool(getattr(feats, "price_vol_missing", False)))
        and math.isfinite(pv)
        and pv > 0.0
    )


def update(snap: Snapshot, feats: FeatureVector) -> Snapshot:
    K = snap.n_states or N_STATES
    D = FEATURE_DIM

    if snap.transition_counts is None:
        snap.transition_counts = [[TRANSITION_PSEUDO_COUNT] * K for _ in range(K)]
    if snap.emission_mean is None:
        snap.emission_mean = [[0.0] * D for _ in range(K)]
    if snap.emission_var is None:
        snap.emission_var = [[4.0] * D for _ in range(K)]
    if snap.state_posteriors is None:
        snap.state_posteriors = [1.0 / K] * K
    if snap.residual_abs_ewm is None:
        snap.residual_abs_ewm = [0.0] * D

    trans = _sanitize_trans(np.array(snap.transition_counts, dtype=float))
    mean = np.array(snap.emission_mean, dtype=float)
    var = np.array(snap.emission_var, dtype=float)
    _sanitize_emission_cells(mean, var)
    prev_post = _sanitize_prev_post(np.array(snap.state_posteriors, dtype=float), K)
    x, skip_dims = _sanitize_x(feats, snap)

    if _price_vol_usable(feats):
        snap.last_good_price_vol = float(feats.price_vol)

    row_sums = trans.sum(axis=1, keepdims=True)
    row_sums = np.maximum(row_sums, 1e-12)
    A = trans / row_sums
    pred = prev_post @ A

    log_lik = np.zeros(K)
    for k in range(K):
        ll = 0.0
        for d in range(D):
            if d in skip_dims:
                continue
            v = max(float(var[k, d]), EMISSION_VAR_FLOOR)
            diff = float(x[d] - mean[k, d])
            ll += -0.5 * (math.log(2 * math.pi * v) + (diff * diff) / v)
        log_lik[k] = ll

    log_post = np.log(np.maximum(pred, 1e-12)) + log_lik
    log_post -= np.nanmax(log_post) if np.any(np.isfinite(log_post)) else 0.0
    post = np.exp(log_post)
    post_sum = float(np.nansum(post))
    if post_sum > 0.0 and np.all(np.isfinite(post)):
        post = post / post_sum
    else:
        post = np.full(K, np.nan)

    if (not np.all(np.isfinite(post))) or float(np.sum(post)) <= 0.0:
        snap.notes = "hmm_skip_nan"
        log.warning("HMM skip this tick (NaN posterior); keeping last good arrays")
        snap.last_features = feats
        snap.updated_at = datetime.now(timezone.utc).astimezone()
        _update_ewm(snap, feats)
        update_zonal_and_peak(snap, feats)
        append_history(snap, feats)
        return snap

    expected_trans = np.outer(prev_post, post)
    trans = trans + expected_trans

    alpha = EWM_ALPHA_WARM if snap.n_obs < WARM_OBS else EWM_ALPHA
    for k in range(K):
        w = float(post[k])
        if w < 1e-6:
            continue
        for d in range(D):
            if d in skip_dims:
                continue
            old_m = mean[k, d]
            new_m = (1 - alpha * w) * old_m + (alpha * w) * x[d]
            old_v = var[k, d]
            resid2 = (x[d] - new_m) ** 2
            new_v = (1 - alpha * w) * old_v + (alpha * w) * resid2
            mean[k, d] = new_m
            var[k, d] = max(new_v, EMISSION_VAR_FLOOR)

    k_star = int(post.argmax())
    residual = list(snap.residual_abs_ewm)
    if len(residual) < D:
        residual.extend([0.0] * (D - len(residual)))
    for d in range(D):
        if d in skip_dims:
            continue
        resid = abs(float(x[d] - mean[k_star, d]))
        prev_r = float(residual[d])
        if not math.isfinite(prev_r):
            prev_r = 0.0
        residual[d] = (1 - alpha) * prev_r + alpha * resid

    _update_ewm(snap, feats)

    snap.transition_counts = trans.tolist()
    snap.emission_mean = mean.tolist()
    snap.emission_var = var.tolist()
    snap.state_posteriors = [float(p) for p in post]
    snap.residual_abs_ewm = residual
    snap.last_features = feats
    snap.n_obs += 1
    snap.updated_at = datetime.now(timezone.utc).astimezone()
    snap.last_entropy = float(-np.sum(post * np.log(np.maximum(post, 1e-12))))
    snap.notes = f"k*={k_star}"

    update_zonal_and_peak(snap, feats)
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
        if name == "price_vol" and getattr(feats, "price_vol_missing", False):
            if not (math.isfinite(float(val)) and float(val) > 0.0):
                continue
        try:
            val_f = float(val)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(val_f):
            continue
        slot = snap.ewm.get(name)
        slot_bad = (
            slot is None
            or not math.isfinite(float(slot.get("mean", float("nan"))))
            or not math.isfinite(float(slot.get("var", 0.0)))
        )
        if slot_bad:
            snap.ewm[name] = {"mean": val_f, "var": 0.0, "n": 1.0}
            continue
        old_m = slot["mean"]
        new_m = (1 - alpha) * old_m + alpha * val_f
        slot["var"] = (1 - alpha) * slot["var"] + alpha * (val_f - new_m) ** 2
        slot["mean"] = new_m
        slot["n"] = slot.get("n", 0.0) + 1.0


def _price_vol_missing_flag(snap: Snapshot) -> bool:
    lf = snap.last_features
    if lf is None:
        return False
    return bool(getattr(lf, "price_vol_missing", False))


def predictive_summary(snap: Snapshot) -> dict:
    pv_missing = _price_vol_missing_flag(snap)
    post = (
        np.array(snap.state_posteriors, dtype=float)
        if snap.state_posteriors is not None
        else None
    )
    if post is not None and (post.size == 0 or not np.all(np.isfinite(post))):
        return {
            "status": "poisoned",
            "notes": snap.notes or "hmm_poisoned",
            "entropy": None,
            "posteriors": [float(p) for p in post],
            "n_obs": snap.n_obs,
            "price_vol_missing": pv_missing,
        }
    if post is None or not snap.emission_mean:
        return {
            "status": "uninitialized",
            "n_obs": snap.n_obs,
            "notes": snap.notes,
            "price_vol_missing": pv_missing,
        }
    mean = np.array(snap.emission_mean, dtype=float)
    var = np.array(snap.emission_var, dtype=float) if snap.emission_var is not None else None
    if not np.all(np.isfinite(mean)) or var is None or not np.all(np.isfinite(var)):
        return {
            "status": "poisoned",
            "notes": snap.notes or "hmm_poisoned",
            "entropy": None,
            "posteriors": [float(p) for p in post],
            "n_obs": snap.n_obs,
            "price_vol_missing": pv_missing,
        }
    mix_mean_load_s = float(post @ mean[:, 0])
    mix_mean_price_s = float(post @ mean[:, 2])
    mix_var_load_s = float(
        post @ var[:, 0] + post @ (mean[:, 0] - mix_mean_load_s) ** 2
    )
    mix_var_price_s = float(
        post @ var[:, 2] + post @ (mean[:, 2] - mix_mean_price_s) ** 2
    )
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
        "price_vol_missing": pv_missing,
        "notes": snap.notes,
    }
