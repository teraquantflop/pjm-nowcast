"""
JSON snapshot load / save with atomic write.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from .state import Snapshot

log = logging.getLogger("shpnwels.persistence")


def load_snapshot(path: Path) -> Snapshot:
    if not path.exists():
        log.info("No snapshot at %s — starting with diffuse priors", path)
        return _diffuse_prior()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        snap = Snapshot.from_dict(data)
        log.info(
            "Loaded snapshot (n_obs=%d, updated_at=%s, version=%s)",
            snap.n_obs,
            snap.updated_at,
            snap.version,
        )
        return snap
    except Exception as e:
        log.exception("Failed to load snapshot; falling back to diffuse prior: %s", e)
        return _diffuse_prior()


def save_snapshot(path: Path, snap: Snapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = snap.to_dict()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=False)
    tmp.replace(path)
    log.debug("Saved snapshot → %s", path)


def _diffuse_prior() -> Snapshot:
    """
    High-entropy start: nearly uniform transitions, modest scaled-space
    emission variance, small mean jitter so states are not clones.
    New zonal/peak fields start unset (None).
    """
    from config import N_STATES, FEATURE_DIM, TRANSITION_PSEUDO_COUNT

    K = N_STATES
    D = FEATURE_DIM

    trans = [[TRANSITION_PSEUDO_COUNT for _ in range(K)] for _ in range(K)]
    for i in range(K):
        trans[i][i] += 1.0

    rng = np.random.default_rng()
    em_mean = rng.normal(0.0, 0.35, size=(K, D)).tolist()
    em_var = [[4.0 for _ in range(D)] for _ in range(K)]
    post = [1.0 / K for _ in range(K)]

    return Snapshot(
        version=2,
        n_obs=0,
        n_states=K,
        transition_counts=trans,
        emission_mean=em_mean,
        emission_var=em_var,
        state_posteriors=post,
        residual_abs_ewm=[0.0 for _ in range(D)],
        last_entropy=_entropy(post),
        notes="diffuse prior",
        # zonal / peak / cond start empty — filled as scrapes succeed
        zonal_p05=None,
        zonal_p95=None,
        zonal_spread=None,
        zonal_spread_mean=None,
        zonal_spread_var=None,
        zonal_spread_ewm_abs_resid=None,
        forecast_peak_today_mw=None,
        forecast_peak_tomorrow_mw=None,
        cond_price_resid_low_spread=None,
        cond_price_resid_high_spread=None,
        last_high_spread=False,
        spread_day=None,
        spread_max_today=None,
        spread_min_today=None,
        spread_high_count_today=0,
        spread_n_today=0,
        history=[],
    )


def _entropy(probs) -> float:
    import math
    h = 0.0
    for p in probs:
        if p > 1e-12:
            h -= p * math.log(p)
    return h
