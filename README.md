# pjm-nowcast

Trailing and semi-live **descriptive statistics** on PJM RTO LMP, selected zonal LMP price spreads, and RTO load.

This is **not** a forecast, trading signal, or recommendation. Figures are aggregated from public market sources. Freshness equals the last successful background poll (`asOf`, `polledAt`, `ageSeconds`). Buyer beware.

HTTP and MCP request handlers only read a local SQLite store. A background poller is the only process that fetches the public markets page.

## What you get

| Tier | Route | What it returns |
|------|--------|-----------------|
| L0 free | `GET /health`, `GET /`, `GET /v1/demo/sample`, `GET /openapi.json` | Health, service card, fixed sample, OpenAPI 3 |
| L1 | `POST /v1/nowcast/latest` | Latest snapshot + trailing 24h stats |
| L2 | `POST /v1/nowcast/history` | 1–72h history (native poll points) |
| L3 | `POST /v1/nowcast/history/extended` | Up to 30-day history, hourly buckets, prior-period comparison |

Every nowcast payload includes `asOf`, `polledAt`, `ageSeconds`, `maxAgeSeconds`, and `stale`. Units are `USD/MWh` (prices/spreads) and `MW` (load).

`GET /openapi.json` is OpenAPI 3. Free routes set `security: []`. The three paid nowcast POSTs include `x-payment-info` and a `402` response. The root service card at `GET /` is unchanged.

`sourcePublishedPeakTodayMw` / `sourcePublishedPeakTomorrowMw` are **source-published** peak figures from the public page, not produced by this service.

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# set PAY_TO_SVM_ADDRESS / PAY_TO_EVM_ADDRESS
# optional: MOCK_MODE=true so the poller never hits the live page

uvicorn pjm_nowcast.main:app --host 0.0.0.0 --port 8000
```

The API process starts the poller when `RUN_POLLER=true` (default). Standalone poller:

```bash
python -m pjm_nowcast.poller
```

Probe free routes and confirm a 402 on a paid route (no keys):

```bash
python scripts/probe_free.py http://127.0.0.1:8000
```

Tests (no live page, no real payments):

```bash
pytest
```

## Payments (x402)

Paid routes accept USDC via the `exact` scheme on **Solana mainnet** and **Base mainnet**. The facilitator default is `https://facilitator.payai.network`.

- Unpaid or empty-body POSTs to paid routes return **402** with a `PAYMENT-REQUIRED` header — not 400. The challenge `accepts` list includes USDC atomic `amount` / `maxAmountRequired` (6 decimals; dollar prices are unchanged).
- GET on the three paid paths returns the same 402 challenge (not 405) so discovery scanners can register them. POST is the real API.
- Unpaid 402 probes do not consume the rate-limit bucket.
- Server env may contain **public** `PAY_TO_*` addresses only.
- The process **refuses to start** if `SVM_PRIVATE_KEY` or `EVM_PRIVATE_KEY` is set.
- Client signing keys belong in a local test-client `.env`, never on Railway.
- Optional `FREE_TIER_N` (default 0) allows first-N unpaid L1 calls per hashed IP window.

Mainnet notes: these are real USDC transfers. Confirm each pay-to address can receive USDC on that chain. Start with small `PRICE_*`. Facilitator catalog listing is not guaranteed by a successful settle.

## MCP

When `MCP_ENABLED=true`, a Streamable HTTP MCP façade is mounted at `MCP_PATH` (default `/mcp`).

Tools: `service_info` and `demo_sample` (free); `nowcast_latest`, `nowcast_history`, `nowcast_history_extended` (same payment rules as HTTP).

## Railway

One service is the default:

- Dockerfile in this repo, or Nixpacks + `pip install -r requirements.txt`
- Start: `uvicorn pjm_nowcast.main:app --host 0.0.0.0 --port $PORT`
- Persistent volume → `DATA_DIR` (SQLite lives there; 30-day rolling retention)
- `TRUST_PROXY=true`, `ENV=production`, `PUBLIC_BASE_URL=https://your-host`
- `RUN_POLLER=true`
- Set public `PAY_TO_SVM_ADDRESS` / `PAY_TO_EVM_ADDRESS`

Two-process alternative: web with `RUN_POLLER=false` plus a worker `python -m pjm_nowcast.poller` sharing the same volume.

If upstream data is unavailable the API stays up and serves the last stored sample with `stale: true`, or `503 data_unavailable` if the store is empty.

## Configuration

See `.env.example`. All runtime state is under `DATA_DIR` / `DATABASE_PATH` (working directory, not a laptop home path).

## License / use

Research and commercial descriptive-stats service. Respect the source site’s terms; keep poll cadence polite. Not investment advice.
