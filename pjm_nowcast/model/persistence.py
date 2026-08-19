"""JSON snapshot load / save with atomic write and one-shot HMM reset."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pjm_nowcast.model.hmm import ensure_jittered_init
from pjm_nowcast.model.params import FEATURE_DIM, N_STATES, TRANSITION_PSEUDO_COUNT
from pjm_nowcast.model.state import Snapshot

log = logging.getLogger("pjm_nowcast.model.persistence")


def load_snapshot(path: Path) -> Snapshot:
    if not path.exists():
        log.info("No snapshot at %s — starting with diffuse priors", path)
        return _diffuse_prior()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        snap = Snapshot.from_dict(data)
        if (
            snap.n_obs > 0
            and snap.state_posteriors is None
            and snap.emission_mean is None
        ):
            log.warning("HMM arrays discarded (non-finite); next update cold-starts")
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


def reset_hmm(snap: Snapshot) -> Snapshot:
    """Drop HMM sufficient statistics, keep history and zonal day stats.

    n_obs is HMM-only (warm-start counter) and is cleared so the next ticks re-warm.
    """
    snap.transition_counts = None
    snap.emission_mean = None
    snap.emission_var = None
    snap.state_posteriors = None
    snap.residual_abs_ewm = None
    snap.n_obs = 0
    snap.last_entropy = 0.0
    snap.notes = "HMM reset"
    log.info("HMM reset")
    ensure_jittered_init(snap)
    if snap.state_posteriors:
        snap.last_entropy = _entropy(snap.state_posteriors)
    return snap


def _diffuse_prior() -> Snapshot:
    K = N_STATES
    D = FEATURE_DIM
    trans = [[TRANSITION_PSEUDO_COUNT for _ in range(K)] for _ in range(K)]
    for i in range(K):
        trans[i][i] += 1.0
    snap = Snapshot(
        version=2,
        n_obs=0,
        n_states=K,
        transition_counts=trans,
        emission_mean=None,
        emission_var=None,
        state_posteriors=None,
        residual_abs_ewm=[0.0 for _ in range(D)],
        last_entropy=0.0,
        notes="diffuse prior",
        history=[],
    )
    ensure_jittered_init(snap)
    if snap.state_posteriors:
        snap.last_entropy = _entropy(snap.state_posteriors)
    return snap


def _entropy(probs) -> float:
    import math

    h = 0.0
    for p in probs:
        if p > 1e-12:
            h -= p * math.log(p)
    return h
