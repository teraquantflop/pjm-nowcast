"""HMM snapshot dataclasses. Internal; not served on HTTP."""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from pjm_nowcast.model.params import (
    LOAD_CENTER_MW,
    LOAD_RAMP_SCALE_MW,
    LOAD_SCALE_MW,
    PRICE_SCALE,
    PRICE_VOL_SCALE,
)

log = logging.getLogger("pjm_nowcast.model.state")


def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _iso_to_dt(s: Optional[str]) -> Optional[datetime]:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def _contains_nonfinite(obj: Any) -> bool:
    if obj is None:
        return False
    if isinstance(obj, bool):
        return False
    if isinstance(obj, (float, int, np.floating, np.integer)):
        try:
            return not math.isfinite(float(obj))
        except (TypeError, ValueError, OverflowError):
            return True
    if isinstance(obj, (list, tuple)):
        return any(_contains_nonfinite(x) for x in obj)
    if isinstance(obj, dict):
        return any(_contains_nonfinite(v) for v in obj.values())
    return False


@dataclass
class FeatureVector:
    ts: datetime
    load_mw: float
    load_ramp: float
    price: float
    price_vol: float
    hour_sin: float
    hour_cos: float
    is_weekend: int
    quality: float = 1.0
    # True when this tick's realized-vol estimate is missing (window not
    # filled, non-finite, or <= 0). price_vol may still hold a carried last-good.
    price_vol_missing: bool = False
    forecast_peak_today_mw: Optional[float] = None
    forecast_peak_tomorrow_mw: Optional[float] = None
    zonal_lmps: Optional[Dict[str, float]] = None

    def to_emission_vec(self) -> np.ndarray:
        return np.array(
            [
                (self.load_mw - LOAD_CENTER_MW) / LOAD_SCALE_MW,
                self.load_ramp / LOAD_RAMP_SCALE_MW,
                self.price / PRICE_SCALE,
                self.price_vol / PRICE_VOL_SCALE,
                self.hour_sin,
                self.hour_cos,
            ],
            dtype=float,
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["ts"] = _dt_to_iso(self.ts)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FeatureVector":
        d = dict(d)
        d["ts"] = _iso_to_dt(d["ts"])
        d.setdefault("forecast_peak_today_mw", None)
        d.setdefault("forecast_peak_tomorrow_mw", None)
        d.setdefault("zonal_lmps", None)
        d.setdefault("price_vol_missing", False)
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Snapshot:
    version: int = 2
    updated_at: Optional[datetime] = None
    n_obs: int = 0
    ewm: Dict[str, Dict[str, float]] = field(default_factory=dict)
    n_states: int = 5
    transition_counts: Optional[List[List[float]]] = None
    emission_mean: Optional[List[List[float]]] = None
    emission_var: Optional[List[List[float]]] = None
    state_posteriors: Optional[List[float]] = None
    residual_abs_ewm: Optional[List[float]] = None
    last_features: Optional[FeatureVector] = None
    last_entropy: float = 0.0
    notes: str = ""
    last_good_price_vol: Optional[float] = None
    zonal_p05: Optional[float] = None
    zonal_p95: Optional[float] = None
    zonal_spread: Optional[float] = None
    zonal_spread_mean: Optional[float] = None
    zonal_spread_var: Optional[float] = None
    zonal_spread_ewm_abs_resid: Optional[float] = None
    forecast_peak_today_mw: Optional[float] = None
    forecast_peak_tomorrow_mw: Optional[float] = None
    cond_price_resid_low_spread: Optional[float] = None
    cond_price_resid_high_spread: Optional[float] = None
    last_high_spread: bool = False
    spread_day: Optional[str] = None
    spread_max_today: Optional[float] = None
    spread_min_today: Optional[float] = None
    spread_high_count_today: int = 0
    spread_n_today: int = 0
    history: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": _dt_to_iso(self.updated_at),
            "n_obs": self.n_obs,
            "ewm": self.ewm,
            "n_states": self.n_states,
            "transition_counts": self.transition_counts,
            "emission_mean": self.emission_mean,
            "emission_var": self.emission_var,
            "state_posteriors": self.state_posteriors,
            "residual_abs_ewm": self.residual_abs_ewm,
            "last_features": self.last_features.to_dict() if self.last_features else None,
            "last_entropy": self.last_entropy,
            "notes": self.notes,
            "last_good_price_vol": self.last_good_price_vol,
            "zonal_p05": self.zonal_p05,
            "zonal_p95": self.zonal_p95,
            "zonal_spread": self.zonal_spread,
            "zonal_spread_mean": self.zonal_spread_mean,
            "zonal_spread_var": self.zonal_spread_var,
            "zonal_spread_ewm_abs_resid": self.zonal_spread_ewm_abs_resid,
            "forecast_peak_today_mw": self.forecast_peak_today_mw,
            "forecast_peak_tomorrow_mw": self.forecast_peak_tomorrow_mw,
            "cond_price_resid_low_spread": self.cond_price_resid_low_spread,
            "cond_price_resid_high_spread": self.cond_price_resid_high_spread,
            "last_high_spread": self.last_high_spread,
            "spread_day": self.spread_day,
            "spread_max_today": self.spread_max_today,
            "spread_min_today": self.spread_min_today,
            "spread_high_count_today": self.spread_high_count_today,
            "spread_n_today": self.spread_n_today,
            "history": self.history or [],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Snapshot":
        lf = d.get("last_features")
        hist = d.get("history")
        if hist is not None and not isinstance(hist, list):
            hist = []
        trans = d.get("transition_counts")
        em_mean = d.get("emission_mean")
        em_var = d.get("emission_var")
        post = d.get("state_posteriors")
        resid = d.get("residual_abs_ewm")
        last_entropy = d.get("last_entropy", 0.0)
        if last_entropy is None or _contains_nonfinite(last_entropy):
            last_entropy = 0.0
        if any(_contains_nonfinite(v) for v in (trans, em_mean, em_var, post, resid)):
            log.warning("HMM arrays discarded (non-finite); next update cold-starts")
            trans = em_mean = em_var = post = resid = None
            last_entropy = 0.0
        last_good = d.get("last_good_price_vol")
        if last_good is not None:
            try:
                last_good = float(last_good)
                if not math.isfinite(last_good) or last_good <= 0:
                    last_good = None
            except (TypeError, ValueError):
                last_good = None
        return cls(
            version=d.get("version", 1),
            updated_at=_iso_to_dt(d.get("updated_at")),
            n_obs=d.get("n_obs", 0),
            ewm=d.get("ewm") or {},
            n_states=d.get("n_states", 5),
            transition_counts=trans,
            emission_mean=em_mean,
            emission_var=em_var,
            state_posteriors=post,
            residual_abs_ewm=resid,
            last_features=FeatureVector.from_dict(lf) if lf else None,
            last_entropy=last_entropy,
            notes=d.get("notes", ""),
            last_good_price_vol=last_good,
            zonal_p05=d.get("zonal_p05"),
            zonal_p95=d.get("zonal_p95"),
            zonal_spread=d.get("zonal_spread"),
            zonal_spread_mean=d.get("zonal_spread_mean"),
            zonal_spread_var=d.get("zonal_spread_var"),
            zonal_spread_ewm_abs_resid=d.get("zonal_spread_ewm_abs_resid"),
            forecast_peak_today_mw=d.get("forecast_peak_today_mw"),
            forecast_peak_tomorrow_mw=d.get("forecast_peak_tomorrow_mw"),
            cond_price_resid_low_spread=d.get("cond_price_resid_low_spread"),
            cond_price_resid_high_spread=d.get("cond_price_resid_high_spread"),
            last_high_spread=bool(d.get("last_high_spread", False)),
            spread_day=d.get("spread_day"),
            spread_max_today=d.get("spread_max_today"),
            spread_min_today=d.get("spread_min_today"),
            spread_high_count_today=int(d.get("spread_high_count_today") or 0),
            spread_n_today=int(d.get("spread_n_today") or 0),
            history=hist if hist is not None else [],
        )
