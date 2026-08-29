"""Legacy trades.db recorder — restores closed-trade recording on exit.

Background
----------
Before the v2.53+ DI refactor, ``index_trader.py`` wrote every closed trade to
the legacy ``trades`` table in root ``trades.db`` (columns: ``ts``, ``mode``,
``net_pnl``, ``index_name``, ``direction``, ``entry``, ``exit_price``, ``qty``,
``gross_pnl``, ``reason``, ``regime``, ``score``, ...).  That write-on-exit is
what the live-readiness gate (``core/live_readiness_checker.py``), performance
metrics, Monte Carlo, auto-tuner, signal autopsy, trade replayer and other
analytics consumers all read.

The refactor removed those writers while the readers kept pointing at the
legacy schema.  As a result:

* ``PositionService.exit_position`` never persisted closed trades to
  ``trades.db`` → the readiness gate permanently reported 0 paper trades.
* ``ExecutionService`` tried to write fills to ``data/trades.db`` through a
  *different* schema, raising ``PersistenceError`` on the first fill.

This module re-establishes the single source of truth: a best-effort,
never-raising recorder that appends a legacy-format row to the configured
trades DB on every successful position exit.  It is intentionally defensive —
a recording failure must never block or alter trading behaviour.

Public API
----------
    ensure_legacy_trades_schema(db_path) -> bool
    record_closed_trade(db_path, *, ts, index_name, direction, entry,
                        exit_price, qty, gross_pnl, net_pnl, reason,
                        mode="PAPER", regime=None, score=None, ...) -> int | None

Config
------
    trades_db        : str  default "db/trades.db"   (legacy trades DB path)
    trades_db_path   : str  (alias used by morning checklist / readiness gate)
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from core.db_utils import get_connection

_log = logging.getLogger(__name__)

_LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT,
    index_name    TEXT,
    direction     TEXT,
    entry         REAL,
    exit_price    REAL,
    qty           INTEGER,
    gross_pnl     REAL,
    net_pnl       REAL,
    reason        TEXT,
    regime        TEXT,
    score         INTEGER,
    iv            REAL,
    vix           REAL,
    ltp_estimated INTEGER,
    partial       INTEGER,
    sl_warned     INTEGER,
    mode          TEXT,
    version       TEXT
)
"""


def resolve_trades_db_path(cfg: dict[str, Any] | None) -> str | None:
    """Resolve the legacy trades DB path from config.

    Returns the configured ``trades_db_path`` / ``trades_db`` value, or None
    when neither key is set (callers then skip recording).  Mirrors the lookup
    used by the live-readiness gate and morning checklist.
    """
    if not cfg:
        return None
    path = cfg.get("trades_db_path") or cfg.get("trades_db")
    return str(path) if path else None


def ensure_legacy_trades_schema(db_path: str | Path) -> bool:
    """Create the legacy ``trades`` table if missing.

    Best-effort: returns True on success, False on any error (never raises).
    """
    try:
        conn = get_connection(str(db_path), timeout=5)
        try:
            conn.execute(_LEGACY_SCHEMA)
            conn.commit()
            return True
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError) as exc:
        _log.warning("[TRADE_RECORDER] Schema ensure failed for %s: %s", db_path, exc)
        return False


def record_closed_trade(
    db_path: str | Path,
    *,
    ts: str,
    index_name: str,
    direction: str,
    entry: float,
    exit_price: float,
    qty: int,
    gross_pnl: float,
    net_pnl: float,
    reason: str,
    mode: str = "PAPER",
    regime: str | None = None,
    score: int | None = None,
    iv: float | None = None,
    vix: float | None = None,
    version: str = "v2.57.1",
) -> int | None:
    """Append a closed-trade row to the legacy trades DB.

    Only closed trades (final net_pnl) are recorded — open fills are never
    written here so the readiness gate's ``net_pnl IS NOT NULL`` filter counts
    only completed trades.

    Returns the new rowid, or None on any failure (never raises).
    """
    try:
        if not ensure_legacy_trades_schema(db_path):
            return None
        conn = get_connection(str(db_path), timeout=5)
        try:
            cur = conn.execute(
                """
                INSERT INTO trades (
                    ts, index_name, direction, entry, exit_price, qty,
                    gross_pnl, net_pnl, reason, regime, score, iv, vix,
                    ltp_estimated, partial, sl_warned, mode, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
                """,
                (
                    ts, str(index_name), str(direction), float(entry),
                    float(exit_price), int(qty), float(gross_pnl), float(net_pnl),
                    str(reason), regime, score, iv, vix, str(mode), str(version),
                ),
            )
            conn.commit()
            rowid = cur.lastrowid
            _log.debug(
                "[TRADE_RECORDER] Recorded %s %s exit=%s net_pnl=%.2f mode=%s (id=%s)",
                index_name, direction, reason, float(net_pnl), mode, rowid,
            )
            return rowid
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
        _log.warning("[TRADE_RECORDER] Record failed for %s: %s", index_name, exc)
        return None


__all__ = [
    "ensure_legacy_trades_schema",
    "record_closed_trade",
    "resolve_trades_db_path",
]
