# Archived prototype (not the production service)

This directory is the original local research loop. **`pjm_nowcast` does not import it.**

---

# SHPNWELS (ShoppingWells)

**Short-Horizon Probabilistic Nowcaster With Emerging Latent Structure**

Local Python prototype that:

- Politely scrapes `https://www.pjm.com/markets-and-operations` (or runs in mock mode)
- Builds a small feature vector (load, ramp, price, short realized vol, time-of-day)
- Maintains an **online HMM** with diagonal-Gaussian emissions whose latent regimes are *inferred*, not hand-defined
- Persists all sufficient statistics to a single `snapshot.json` so restarts continue where they left off
- Samples more frequently during high-information hours and less overnight (summer-oriented)

The goal of this prototype is to watch the model go from high-entropy / wide tails (“garbage”) toward structured regimes and tighter predictive distributions as observations accumulate.

## Quick start (Ubuntu)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Stop with `Ctrl-C`. State is written on every cycle and on interrupt.

## License / use

Research prototype for personal use. Respect PJM’s site terms; keep the cadence polite.
