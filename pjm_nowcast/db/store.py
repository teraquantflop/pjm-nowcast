"""SQLite store. Request handlers only read; poller writes."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class Observation:
    id: int
    ts: datetime
    fetched_at: datetime
    load_mw: float | None
    rto_lmp: float | None
    published_peak_today_mw: float | None
    published_peak_tomorrow_mw: float | None
    quality: float
    source: str
    as_of_text: str | None
    load_ramp_mw: float | None
    zonals: dict[str, float] = field(default_factory=dict)


class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _migrate(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(sql)
            row = self._conn.execute(
                "SELECT MAX(version) AS v FROM schema_migrations"
            ).fetchone()
            current = int(row["v"] or 0)
            if current < SCHEMA_VERSION:
                self._conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, _iso(datetime.now(timezone.utc))),
                )

    def insert_observation(
        self,
        *,
        ts: datetime,
        fetched_at: datetime,
        load_mw: float | None,
        rto_lmp: float | None,
        published_peak_today_mw: float | None,
        published_peak_tomorrow_mw: float | None,
        quality: float,
        source: str,
        as_of_text: str | None,
        load_ramp_mw: float | None,
        zonals: dict[str, float],
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO observations (
                  ts, fetched_at, load_mw, rto_lmp,
                  published_peak_today_mw, published_peak_tomorrow_mw,
                  quality, source, as_of_text, load_ramp_mw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _iso(ts),
                    _iso(fetched_at),
                    load_mw,
                    rto_lmp,
                    published_peak_today_mw,
                    published_peak_tomorrow_mw,
                    quality,
                    source,
                    as_of_text,
                    load_ramp_mw,
                ),
            )
            oid = int(cur.lastrowid)
            for zone, lmp in zonals.items():
                self._conn.execute(
                    "INSERT INTO zonal_lmps (observation_id, zone, lmp) VALUES (?, ?, ?)",
                    (oid, zone, float(lmp)),
                )
            return oid

    def latest(self) -> Observation | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM observations ORDER BY ts DESC, id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            return self._hydrate(row)

    def observations_since(self, start: datetime, end: datetime | None = None) -> list[Observation]:
        params: list[Any] = [_iso(start)]
        sql = "SELECT * FROM observations WHERE ts >= ?"
        if end is not None:
            sql += " AND ts < ?"
            params.append(_iso(end))
        sql += " ORDER BY ts ASC, id ASC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [self._hydrate(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0])

    def prune(self, retention_days: int, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=retention_days)
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM observations WHERE ts < ?",
                (_iso(cutoff),),
            )
            deleted = int(cur.rowcount or 0)
            idem_cut = now - timedelta(hours=24)
            self._conn.execute(
                "DELETE FROM idempotency WHERE created_at < ?",
                (_iso(idem_cut),),
            )
            ft_cut = now - timedelta(days=2)
            self._conn.execute(
                "DELETE FROM free_tier WHERE window_start < ?",
                (_iso(ft_cut),),
            )
            return deleted

    def start_poll_run(self, started_at: datetime) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO poll_runs (started_at, ok) VALUES (?, 0)",
                (_iso(started_at),),
            )
            return int(cur.lastrowid)

    def finish_poll_run(
        self,
        run_id: int,
        *,
        ok: bool,
        finished_at: datetime,
        error: str | None = None,
        observation_id: int | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE poll_runs
                SET finished_at=?, ok=?, error=?, observation_id=?
                WHERE id=?
                """,
                (_iso(finished_at), 1 if ok else 0, error, observation_id, run_id),
            )
            if ok:
                self._conn.execute(
                    "INSERT INTO kv(key, value) VALUES('last_success_at', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (_iso(finished_at),),
                )
            else:
                self._conn.execute(
                    "INSERT INTO kv(key, value) VALUES('last_error', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (error or "poll failed",),
                )

    def last_poll(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM poll_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            last_ok = self._kv_unlocked("last_success_at")
            last_err = self._kv_unlocked("last_error")
        return {
            "lastRun": dict(row) if row else None,
            "lastSuccessAt": last_ok,
            "lastError": last_err,
        }

    def kv_get(self, key: str) -> str | None:
        with self._lock:
            return self._kv_unlocked(key)

    def kv_set(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_idempotency(self, key: str, route: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM idempotency WHERE key=? AND route=?",
                (key, route),
            ).fetchone()

    def put_idempotency(
        self,
        key: str,
        route: str,
        request_hash: str,
        status_code: int,
        response_json: str,
        created_at: datetime,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO idempotency
                  (key, route, request_hash, status_code, response_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key, route) DO UPDATE SET
                  request_hash=excluded.request_hash,
                  status_code=excluded.status_code,
                  response_json=excluded.response_json,
                  created_at=excluded.created_at
                """,
                (key, route, request_hash, status_code, response_json, _iso(created_at)),
            )

    def consume_free_tier(
        self,
        bucket: str,
        window_start: datetime,
        limit: int,
    ) -> bool:
        """Increment count if under limit. Returns True if the request is free."""
        ws = _iso(window_start)
        with self._lock:
            row = self._conn.execute(
                "SELECT count FROM free_tier WHERE bucket=? AND window_start=?",
                (bucket, ws),
            ).fetchone()
            current = int(row["count"]) if row else 0
            if current >= limit:
                return False
            if row:
                self._conn.execute(
                    "UPDATE free_tier SET count=count+1 WHERE bucket=? AND window_start=?",
                    (bucket, ws),
                )
            else:
                self._conn.execute(
                    "INSERT INTO free_tier (bucket, window_start, count) VALUES (?, ?, 1)",
                    (bucket, ws),
                )
            return True

    def _kv_unlocked(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM kv WHERE key=?", (key,)
        ).fetchone()
        return str(row["value"]) if row else None

    def _hydrate(self, row: sqlite3.Row) -> Observation:
        oid = int(row["id"])
        zrows = self._conn.execute(
            "SELECT zone, lmp FROM zonal_lmps WHERE observation_id=?",
            (oid,),
        ).fetchall()
        zonals = {str(z["zone"]): float(z["lmp"]) for z in zrows}
        return Observation(
            id=oid,
            ts=_parse_dt(row["ts"]),
            fetched_at=_parse_dt(row["fetched_at"]),
            load_mw=_f(row["load_mw"]),
            rto_lmp=_f(row["rto_lmp"]),
            published_peak_today_mw=_f(row["published_peak_today_mw"]),
            published_peak_tomorrow_mw=_f(row["published_peak_tomorrow_mw"]),
            quality=float(row["quality"]),
            source=str(row["source"]),
            as_of_text=row["as_of_text"],
            load_ramp_mw=_f(row["load_ramp_mw"]),
            zonals=zonals,
        )


def _f(v: Any) -> float | None:
    if v is None:
        return None
    return float(v)
