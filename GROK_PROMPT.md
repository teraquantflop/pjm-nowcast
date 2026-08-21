# Task: expose last `price_vol` on `POST /v1/nowcast/latest`

A local consumer (`~/optionbook`) builds an indicative Balance-of-Day call grid from this service. It already falls back to `POST /v1/nowcast/latest` (there is no live `/v1/nowcast/snapshot` route). It parses **last RTO LMP as F** and **last `price_vol` as dollar vol**, then `sigma = price_vol / F`.

Production `POST /v1/nowcast/latest` today returns `rtoLmp.last` but **no `price_vol`**. The book therefore aborts. Add `price_vol` to that payload.

## What `price_vol` is

Already computed in the poller, not a new statistic:

- Source: `pjm_nowcast/ingest/features.py` → `FeatureVector.price_vol` / `price_vol_missing`
- Definition: rolling realized LMP std in **$/MWh** (RMS of successive LMP diffs over a short window, currently 8 prints, need ≥3)
- **Not** annualized Black vol
- **Not** trailing-window mix μ/σ (`rtoLmp.mean` / `rtoLmp.std`)
- **Not** HMM `mix_mean_price` / `mix_std_price` from `predictive_summary`
- Persisted on the HMM snapshot as `last_features` via `save_snapshot` (`settings.snapshot_path`, default `{data_dir}/snapshot.json`)
- Logged today (`price_vol=n/a price_vol_missing=True` until the window fills). Docs currently say “poller logs only, not a public field” — that sentence must change

Do **not** alias `rtoLmp.std` as `price_vol`.

## Payload contract (`POST /v1/nowcast/latest` only)

Top-level on the existing envelope (alongside `asOf`, `rtoLmp`, …), so the consumer can read them without walking mix stats:

```json
{
  "price_vol": 2.15,
  "price_vol_missing": false
}
```

Rules:

- If `price_vol_missing` is true **or** last vol is missing / non-finite / `<= 0`: set `"price_vol_missing": true` and **omit `price_vol` or set it `null`**. Do **not** write `0.0`.
- If last vol is finite and `> 0` and the missing flag is false: `"price_vol": <number>`, `"price_vol_missing": false`.
- `price_vol` is a JSON number (not `{ "last": … }` unless you also keep the number at top-level).
- When `families` omits `rto_lmp`, still include top-level `price_vol` / `price_vol_missing` (they are last-print sticky vol, not a mix family).
- Same fields on the MCP `nowcast_latest` body (it already calls `assemble_latest`).
- **Do not** add these fields to `/v1/nowcast/history` or `/v1/nowcast/history/extended`.
- **Do not** add a new `/v1/nowcast/snapshot` route.
- **Do not** put HMM internals on the HTTP/MCP body: no posteriors, entropy, mix_mean_*, mix_std_*, high-spread, emission vectors.

## Isolation constraint (do not break)

`tests/test_api_isolation.py` forbids `pjm_nowcast/stats`, `pjm_nowcast/api` (except `app.py`), and `pjm_nowcast/mcp_facade` from importing `pjm_nowcast.model`, `pjm_nowcast.poller`, or `pjm_nowcast.ingest`.

Do **not** `from pjm_nowcast.model.persistence import load_snapshot` inside `assemble.py`.

Recommended: in `assemble_latest`, read `settings.snapshot_path` as **plain JSON** and pull only:

- `last_features.price_vol`
- `last_features.price_vol_missing`

If the file is missing, unreadable, or has no `last_features`: treat as missing (`price_vol_missing: true`, no numeric `price_vol`).

Do not add SQLite columns unless you have a strong reason; the HMM snapshot already holds last features after each poll.

## Wire-up

- `pjm_nowcast/stats/assemble.py` — `assemble_latest` (and a small helper)
- `pjm_nowcast/api/discovery.py` — `AGENT_NOTES`: stop saying poller-logs-only; say latest HTTP/MCP now includes last `price_vol` ($/MWh rolling realized LMP std, not Black vol, not mix std) and `price_vol_missing`
- `skill.md` / llm generation if they copy `AGENT_NOTES`
- OpenAPI/schema only if latest response is documented there; keep it additive
- Demo sample (`fixtures/demo/sample.json`) may stay unchanged (fixed demo, not live store). Do not require demo to include `price_vol` unless a test asserts the demo body

## Tests

Add focused tests (new file or `tests/test_stats.py` + HTTP test):

1. Seed observations + a `snapshot.json` with `last_features.price_vol = 2.5`, `price_vol_missing = false` → `POST /v1/nowcast/latest` 200 has `price_vol == 2.5` and `price_vol_missing is false`. `rtoLmp.std` must **not** equal `price_vol` unless coincidentally the same number; assert you did not copy `std` into `price_vol` (use a snapshot vol that differs from the window std).
2. Snapshot missing, or `price_vol_missing: true`, or `price_vol: 0` / null → `price_vol_missing is true` and `price_vol` is absent or null.
3. Isolation test still passes (stats does not import `pjm_nowcast.model`).
4. Existing L0/llm tests still pass (`"price_vol" in llms.text` already).

Run: `pytest` (or the project’s usual test command). Do not add HMM-forward vol, peak/RTC, puts, smiles, or x402 changes.

## Out of scope

- New routes
- History / extended
- Changing how `price_vol` is computed in `features.py`
- Publishing mix μ/σ as F or vol
- OptionBookClient / OPTIONBOOK_ID behavior (already works for latest)

## Done when

`POST /v1/nowcast/latest` (paid or OptionBook-gated, same assembler) returns last RTO LMP as today **and** last sticky `price_vol` / `price_vol_missing` from the poller snapshot, without leaking mix HMM stats.
