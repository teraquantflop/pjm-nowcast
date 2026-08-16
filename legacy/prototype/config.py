"""
SHPNWELS configuration.
All times are interpreted in US/Eastern.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SNAPSHOT_PATH = PROJECT_ROOT / "snapshot.json"
LOG_PATH = PROJECT_ROOT / "shpnwels.log"
PLOTS_DIR = PROJECT_ROOT / "plots"

# Ring buffer of (ts, load, price) for intraday deviation histograms
HISTORY_MAX = 96                   # ~2 days at 30–75 min cadence
HIST_MIN_POINTS = 3                # need at least this many today for a PNG

# ---------------------------------------------------------------------------
# Sampling (summer-oriented)
# ---------------------------------------------------------------------------
HIGH_INFO_START_HOUR = 10          # 10:00 ET
HIGH_INFO_END_HOUR = 23            # 23:00 ET
HIGH_INFO_INTERVAL_MIN = 30
HIGH_INFO_JITTER_MIN = 5

OFF_HOURS_INTERVAL_MIN = 75
OFF_HOURS_JITTER_MIN = 8

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
N_STATES = 5
FEATURE_DIM = 6                    # load, ramp, price, price_vol, hour_sin, hour_cos

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

PRIMARY_PRICE_KEY = "rto_lmp"

# ---------------------------------------------------------------------------
# Zonal / spread / peak (v0.2)
# ---------------------------------------------------------------------------
ZONAL_ZONES = ("BGE", "COMED", "DOM", "PEPCO", "PSEG", "JCPL")
SPREAD_K = 1.25                    # high_spread if spread > EWM + SPREAD_K * σ
PEAK_HOUR_EPT = 17.0               # default peak hour for mild-sine proxy
MIN_ZONES_FOR_SPREAD = 4           # need at least this many parsed zones

# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------
PJM_MARKETS_URL = "https://www.pjm.com/markets-and-operations"
USER_AGENT = (
    "SHPNWELS-research/0.2 (+local prototype; polite 30-75 min cadence; "
    "contact: local-workstation)"
)
REQUEST_TIMEOUT_SEC = 25
MOCK_MODE = False
