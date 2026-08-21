"""HMM knobs. Defaults match the proven SHPNWELS contract; Settings may override spreads."""

N_STATES = 5
FEATURE_DIM = 6
FEATURE_NAMES = (
    "load_mw",
    "load_ramp",
    "price",
    "price_vol",
    "hour_sin",
    "hour_cos",
)
PRICE_VOL_DIM = 3

EWM_ALPHA = 0.07
EWM_ALPHA_WARM = 0.35
WARM_OBS = 15
TRANSITION_PSEUDO_COUNT = 0.5
EMISSION_VAR_FLOOR = 1e-4

LOAD_CENTER_MW = 90_000.0
LOAD_SCALE_MW = 15_000.0
LOAD_RAMP_SCALE_MW = 3_000.0
PRICE_SCALE = 40.0
PRICE_VOL_SCALE = 15.0

HISTORY_MAX = 96

SPREAD_K_DEFAULT = 1.25
SPREAD_ABS_USD_DEFAULT = 15.0
PEAK_HOUR_EPT = 17.0
