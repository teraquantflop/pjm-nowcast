PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  load_mw REAL,
  rto_lmp REAL,
  published_peak_today_mw REAL,
  published_peak_tomorrow_mw REAL,
  quality REAL NOT NULL,
  source TEXT NOT NULL,
  as_of_text TEXT,
  load_ramp_mw REAL
);
CREATE INDEX IF NOT EXISTS idx_obs_ts ON observations(ts);
CREATE INDEX IF NOT EXISTS idx_obs_fetched ON observations(fetched_at);

CREATE TABLE IF NOT EXISTS zonal_lmps (
  id INTEGER PRIMARY KEY,
  observation_id INTEGER NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
  zone TEXT NOT NULL,
  lmp REAL NOT NULL,
  UNIQUE (observation_id, zone)
);

CREATE TABLE IF NOT EXISTS poll_runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  ok INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  observation_id INTEGER REFERENCES observations(id)
);

CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
  key TEXT NOT NULL,
  route TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  status_code INTEGER,
  response_json TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (key, route)
);
CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency(created_at);

CREATE TABLE IF NOT EXISTS free_tier (
  bucket TEXT NOT NULL,
  window_start TEXT NOT NULL,
  count INTEGER NOT NULL,
  PRIMARY KEY (bucket, window_start)
);
