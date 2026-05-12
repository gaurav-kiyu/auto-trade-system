"""
OI Snapshot Store (Phase A1) — Point-in-time option chain recorder.

Records live OI and PCR values during each scan cycle so that the backtest
replay engine can look up historically accurate OI without look-ahead bias.

Key design rules
----------------
- Non-blocking: record_snapshot() catches ALL exceptions and never raises.
- No look-ahead: get_snapshot_at() / get_pcr_at() return the closest snapshot
  STRICTLY BEFORE target_ts (never at or after).
- Deduplication: skips writes if the same index was recorded within
  oi_snapshot_min_interval seconds (default 60 s).
- Auto-archive: snapshots older than oi_snapshot_archive_days are moved to
  oi_snapshots_archive on the next record_snapshot() call for that index
  (keeps the hot table small).

Config keys (all optional — safe defaults built in)
---------------------------------------------------
  oi_snapshot_enabled      : bool  default true
  oi_snapshot_db_path      : str   default "oi_snapshots.db"
  oi_snapshot_min_interval : int   default 60   (seconds between writes)
  oi_snapshot_archive_days : int   default 90
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_DB           = "oi_snapshots.db"
_DEFAULT_MIN_INTERVAL = 60
_DEFAULT_ARCHIVE_DAYS = 90

# ── In-process last-write cache — avoids DB query on every scan cycle ─────────
_last_snapshot_ts: dict[str, float] = {}   # {index_name: epoch_seconds}


# ── Schema bootstrap ──────────────────────────────────────────────────────────

_DDL_MAIN = """
CREATE TABLE IF NOT EXISTS oi_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL NOT NULL,
    index_name      TEXT NOT NULL,
    strike          INTEGER,
    expiry_date     TEXT,
    call_oi         INTEGER,
    put_oi          INTEGER,
    call_volume     INTEGER,
    put_volume      INTEGER,
    pcr_ratio       REAL,
    total_oi        INTEGER,
    snapshot_source TEXT
);
CREATE INDEX IF NOT EXISTS ix_oi_snap_name_ts ON oi_snapshots (index_name, ts);
"""

_DDL_ARCHIVE = """
CREATE TABLE IF NOT EXISTS oi_snapshots_archive (
    id              INTEGER,
    ts              REAL,
    index_name      TEXT,
    strike          INTEGER,
    expiry_date     TEXT,
    call_oi         INTEGER,
    put_oi          INTEGER,
    call_volume     INTEGER,
    put_volume      INTEGER,
    pcr_ratio       REAL,
    total_oi        INTEGER,
    snapshot_source TEXT
);
"""


def _get_conn(db_path: str) -> sqlite3.Connection:
    """Open a connection and ensure schema exists."""
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in _DDL_MAIN.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    for stmt in _DDL_ARCHIVE.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    conn.commit()
    return conn


# ── Archive helper ────────────────────────────────────────────────────────────

def _maybe_archive(conn: sqlite3.Connection, archive_days: int) -> None:
    cutoff = time.time() - archive_days * 86400
    try:
        conn.execute(
            "INSERT INTO oi_snapshots_archive "
            "SELECT * FROM oi_snapshots WHERE ts < ?",
            (cutoff,),
        )
        conn.execute("DELETE FROM oi_snapshots WHERE ts < ?", (cutoff,))
        conn.commit()
    except Exception as exc:
        _log.debug("[OI_SNAP] Archive step failed: %s", exc)


# ── Public API ────────────────────────────────────────────────────────────────

def record_snapshot(
    index_name: str,
    chain_data: dict[str, Any],
    *,
    db_path: str = _DEFAULT_DB,
    ts: float | None = None,
    min_interval: int = _DEFAULT_MIN_INTERVAL,
    archive_days: int = _DEFAULT_ARCHIVE_DAYS,
) -> bool:
    """
    Persist the current option chain state for ``index_name``.

    Args:
        index_name : e.g. "NIFTY", "BANKNIFTY", "FINNIFTY"
        chain_data : Dict produced by ``get_oi_data()`` in index_trader.py.
                     Expected keys (all optional — defaults to 0):
                       pcr_ratio, call_oi, put_oi, call_volume, put_volume,
                       total_oi, strike, expiry_date, snapshot_source
        db_path    : Path to oi_snapshots.db
        ts         : Epoch seconds (defaults to now)
        min_interval : Minimum seconds between writes for the same index
        archive_days : Auto-archive rows older than this many days

    Returns:
        True if a row was written, False if skipped (dedup / error).
    """
    now = time.time() if ts is None else float(ts)

    # Deduplication check (in-process cache — no DB query needed)
    last = _last_snapshot_ts.get(index_name, 0.0)
    if now - last < min_interval:
        return False

    try:
        p = Path(db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = _get_conn(str(p))
        try:
            pcr        = float(chain_data.get("pcr_ratio") or chain_data.get("pcr") or 1.0)
            call_oi    = int(chain_data.get("call_oi")    or 0)
            put_oi     = int(chain_data.get("put_oi")     or 0)
            call_vol   = int(chain_data.get("call_volume") or 0)
            put_vol    = int(chain_data.get("put_volume")  or 0)
            total_oi   = int(chain_data.get("total_oi")   or call_oi + put_oi)
            strike     = chain_data.get("strike")
            expiry     = chain_data.get("expiry_date")
            source     = str(chain_data.get("snapshot_source") or "live_scan")

            # Archive old rows once per write (low-frequency housekeeping)
            _maybe_archive(conn, archive_days)

            conn.execute(
                """
                INSERT INTO oi_snapshots
                    (ts, index_name, strike, expiry_date,
                     call_oi, put_oi, call_volume, put_volume,
                     pcr_ratio, total_oi, snapshot_source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (now, index_name, strike, expiry,
                 call_oi, put_oi, call_vol, put_vol,
                 pcr, total_oi, source),
            )
            conn.commit()
            _last_snapshot_ts[index_name] = now
            _log.debug(
                "[OI_SNAP] Recorded %s pcr=%.3f call_oi=%d put_oi=%d",
                index_name, pcr, call_oi, put_oi,
            )
            return True
        finally:
            conn.close()
    except Exception as exc:
        _log.warning("[OI_SNAP] record_snapshot failed for %s: %s", index_name, exc)
        return False


def get_snapshot_at(
    index_name: str,
    target_ts: float,
    *,
    db_path: str = _DEFAULT_DB,
) -> dict[str, Any] | None:
    """
    Return the closest snapshot for ``index_name`` strictly BEFORE ``target_ts``.

    Never returns data AT or AFTER target_ts (no look-ahead).

    Returns None if no prior snapshot exists.
    """
    p = Path(db_path)
    if not p.is_file():
        return None
    try:
        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT * FROM oi_snapshots
                WHERE index_name = ? AND ts < ?
                ORDER BY ts DESC
                LIMIT 1
                """,
                (index_name, target_ts),
            ).fetchone()
            if row is None:
                return None
            return dict(row)
        finally:
            conn.close()
    except Exception as exc:
        _log.debug("[OI_SNAP] get_snapshot_at failed: %s", exc)
        return None


def get_pcr_at(
    index_name: str,
    target_ts: float,
    *,
    db_path: str = _DEFAULT_DB,
) -> float | None:
    """
    Return the PCR ratio for ``index_name`` at the closest point before ``target_ts``.

    Returns None when no snapshot exists (caller decides on fallback).
    """
    snap = get_snapshot_at(index_name, target_ts, db_path=db_path)
    if snap is None:
        return None
    v = snap.get("pcr_ratio")
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def get_oi_at(
    index_name: str,
    strike: int,
    expiry: str,
    target_ts: float,
    *,
    db_path: str = _DEFAULT_DB,
) -> tuple[int, int] | None:
    """
    Return ``(call_oi, put_oi)`` for a specific strike/expiry before ``target_ts``.

    Falls back to the most recent aggregate snapshot if no strike-level row exists.
    Returns None when nothing is available.
    """
    p = Path(db_path)
    if not p.is_file():
        return None
    try:
        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT call_oi, put_oi FROM oi_snapshots
                WHERE index_name = ? AND strike = ? AND expiry_date = ? AND ts < ?
                ORDER BY ts DESC LIMIT 1
                """,
                (index_name, int(strike), str(expiry), target_ts),
            ).fetchone()
            if row:
                return int(row["call_oi"] or 0), int(row["put_oi"] or 0)
            # Fallback: aggregate row (no strike filter)
            row = conn.execute(
                """
                SELECT call_oi, put_oi FROM oi_snapshots
                WHERE index_name = ? AND ts < ?
                ORDER BY ts DESC LIMIT 1
                """,
                (index_name, target_ts),
            ).fetchone()
            if row:
                return int(row["call_oi"] or 0), int(row["put_oi"] or 0)
            return None
        finally:
            conn.close()
    except Exception as exc:
        _log.debug("[OI_SNAP] get_oi_at failed: %s", exc)
        return None


def coverage_pct(
    index_name: str,
    start_ts: float,
    end_ts: float,
    bar_interval_sec: int = 60,
    *,
    db_path: str = _DEFAULT_DB,
) -> float:
    """
    Return the fraction [0.0–1.0] of 1-minute bars in [start_ts, end_ts]
    that have at least one snapshot within ±bar_interval_sec.

    Used by the --strict-backtest flag to abort when coverage < 80%.
    """
    if end_ts <= start_ts:
        return 0.0
    p = Path(db_path)
    if not p.is_file():
        return 0.0
    try:
        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=5)
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM oi_snapshots
                WHERE index_name = ? AND ts >= ? AND ts <= ?
                """,
                (index_name, start_ts, end_ts),
            ).fetchone()
            snapshot_count = int(row[0]) if row else 0
            expected_bars = max(1, int((end_ts - start_ts) / bar_interval_sec))
            return min(1.0, snapshot_count / expected_bars)
        finally:
            conn.close()
    except Exception:
        return 0.0
