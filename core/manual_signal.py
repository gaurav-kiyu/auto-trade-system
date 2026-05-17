"""
Manual Signal System (v2.46 Sprint 1A).

Thread-safe queue for human-submitted trading signals.  Persists to a
separate SQLite database so signals survive restarts and can be reviewed.

Public API
----------
    ManualSignal          — dataclass
    ManualSignalQueue     — thread-safe queue with SQLite persistence
    build_signal_queue(cfg) → ManualSignalQueue

Config keys
-----------
    manual_signal_enabled          : bool   default true
    manual_signal_db_path          : str    default "manual_signals.db"
    manual_signal_timeout_mins     : int    default 30
    manual_signal_auto_approve_secs: int    default 0 (disabled)
    manual_signal_default_analyst  : str    default "Operator"
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import timedelta

from core.datetime_ist import now_ist
from typing import Any

_log = logging.getLogger(__name__)

# ── Status values ──────────────────────────────────────────────────────────────

PENDING   = "PENDING"
APPROVED  = "APPROVED"
REJECTED  = "REJECTED"
EXECUTED  = "EXECUTED"
EXPIRED   = "EXPIRED"
CANCELLED = "CANCELLED"

_ALL_STATUSES = {PENDING, APPROVED, REJECTED, EXECUTED, EXPIRED, CANCELLED}


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class ManualSignal:
    signal_id:    str
    source:       str          # TELEGRAM | DASHBOARD | CSV | TEXT | API
    analyst_name: str
    index_name:   str          # NIFTY | BANKNIFTY | FINNIFTY
    direction:    str          # CALL | PUT
    score:        int          # 0-100
    reason:       str          # free-text rationale
    submitted_at: str          # ISO datetime string

    # Optional overrides
    expiry:         str | None   = None   # YYYY-MM-DD or "WEEKLY" | "MONTHLY"
    lots_override:  int | None   = None
    sl_override:    float | None = None
    target_override: float | None = None

    # Workflow
    status:      str            = PENDING
    reviewed_by: str | None  = None
    reviewed_at: str | None  = None
    reject_reason: str | None = None

    # Execution
    execution_trade_id: str | None = None
    auto_approve_after_secs: int = 0

    @property
    def is_pending(self) -> bool:
        return self.status == PENDING

    @property
    def is_actionable(self) -> bool:
        return self.status in (PENDING, APPROVED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "source": self.source,
            "analyst_name": self.analyst_name,
            "index_name": self.index_name,
            "direction": self.direction,
            "score": self.score,
            "reason": self.reason,
            "submitted_at": self.submitted_at,
            "expiry": self.expiry,
            "lots_override": self.lots_override,
            "sl_override": self.sl_override,
            "target_override": self.target_override,
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "reject_reason": self.reject_reason,
            "execution_trade_id": self.execution_trade_id,
            "auto_approve_after_secs": self.auto_approve_after_secs,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ManualSignal:
        return ManualSignal(
            signal_id=d["signal_id"],
            source=d.get("source", "UNKNOWN"),
            analyst_name=d.get("analyst_name", "Operator"),
            index_name=d["index_name"],
            direction=d["direction"],
            score=int(d.get("score", 70)),
            reason=d.get("reason", ""),
            submitted_at=d.get("submitted_at", ""),
            expiry=d.get("expiry"),
            lots_override=d.get("lots_override"),
            sl_override=d.get("sl_override"),
            target_override=d.get("target_override"),
            status=d.get("status", PENDING),
            reviewed_by=d.get("reviewed_by"),
            reviewed_at=d.get("reviewed_at"),
            reject_reason=d.get("reject_reason"),
            execution_trade_id=d.get("execution_trade_id"),
            auto_approve_after_secs=int(d.get("auto_approve_after_secs", 0)),
        )


# ── ID generation ──────────────────────────────────────────────────────────────

_counter_lock = threading.Lock()
_counter = 0


def _make_signal_id() -> str:
    global _counter
    with _counter_lock:
        _counter += 1
        ts = int(time.time())
        return f"MSQ_{ts}_{_counter:04d}"


# ── Database layer ─────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS manual_signals (
    signal_id     TEXT PRIMARY KEY,
    source        TEXT,
    analyst_name  TEXT,
    index_name    TEXT,
    direction     TEXT,
    score         INTEGER,
    reason        TEXT,
    submitted_at  TEXT,
    expiry        TEXT,
    lots_override INTEGER,
    sl_override   REAL,
    target_override REAL,
    status        TEXT DEFAULT 'PENDING',
    reviewed_by   TEXT,
    reviewed_at   TEXT,
    reject_reason TEXT,
    execution_trade_id TEXT,
    auto_approve_after_secs INTEGER DEFAULT 0,
    created_at    TEXT DEFAULT (datetime('now'))
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_ms_status ON manual_signals(status)",
    "CREATE INDEX IF NOT EXISTS ix_ms_submitted ON manual_signals(submitted_at)",
    "CREATE INDEX IF NOT EXISTS ix_ms_analyst ON manual_signals(analyst_name)",
]


def _open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_DDL)
    for idx in _INDEXES:
        conn.execute(idx)
    conn.commit()
    return conn


def _row_to_signal(row: sqlite3.Row) -> ManualSignal:
    return ManualSignal.from_dict(dict(row))


# ── Queue ──────────────────────────────────────────────────────────────────────

class ManualSignalQueue:
    """Thread-safe persistent queue for human-submitted signals."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg
        self._db_path = str(cfg.get("manual_signal_db_path", "manual_signals.db"))
        self._timeout_mins = int(cfg.get("manual_signal_timeout_mins", 30))
        self._auto_approve_secs = int(cfg.get("manual_signal_auto_approve_secs", 0))
        self._default_analyst = str(cfg.get("manual_signal_default_analyst", "Operator"))
        self._lock = threading.Lock()
        self._conn = _open_db(self._db_path)
        _log.info("[MANUAL_Q] Initialized — db=%s timeout=%dmin", self._db_path, self._timeout_mins)

    # ── Public write operations ────────────────────────────────────────────

    def submit(
        self,
        index_name: str,
        direction: str,
        score: int,
        reason: str = "",
        *,
        source: str = "DASHBOARD",
        analyst_name: str | None = None,
        expiry: str | None = None,
        lots_override: int | None = None,
        sl_override: float | None = None,
        target_override: float | None = None,
        auto_approve_secs: int | None = None,
    ) -> ManualSignal:
        """Submit a new manual signal. Returns the created ManualSignal."""
        sig = ManualSignal(
            signal_id=_make_signal_id(),
            source=source.upper(),
            analyst_name=analyst_name or self._default_analyst,
            index_name=index_name.upper(),
            direction=direction.upper(),
            score=max(0, min(100, int(score))),
            reason=str(reason),
            submitted_at=now_ist().isoformat(),
            expiry=expiry,
            lots_override=lots_override,
            sl_override=sl_override,
            target_override=target_override,
            auto_approve_after_secs=auto_approve_secs
                if auto_approve_secs is not None else self._auto_approve_secs,
        )
        with self._lock:
            self._conn.execute(
                """INSERT OR IGNORE INTO manual_signals
                   (signal_id, source, analyst_name, index_name, direction, score, reason,
                    submitted_at, expiry, lots_override, sl_override, target_override,
                    status, auto_approve_after_secs)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sig.signal_id, sig.source, sig.analyst_name, sig.index_name,
                 sig.direction, sig.score, sig.reason, sig.submitted_at,
                 sig.expiry, sig.lots_override, sig.sl_override, sig.target_override,
                 PENDING, sig.auto_approve_after_secs),
            )
            self._conn.commit()
        _log.info("[MANUAL_Q] Submitted %s %s %s score=%d by %s",
                  sig.signal_id, sig.index_name, sig.direction, sig.score, sig.analyst_name)
        return sig

    def approve(
        self,
        signal_id: str,
        reviewer: str = "Operator",
        *,
        lots_override: int | None = None,
        sl_override: float | None = None,
    ) -> bool:
        """Approve a pending signal. Returns True if state changed."""
        now = now_ist().isoformat()
        with self._lock:
            sig = self._get(signal_id)
            if sig is None or sig.status != PENDING:
                return False
            updates: dict[str, Any] = {
                "status": APPROVED, "reviewed_by": reviewer, "reviewed_at": now
            }
            if lots_override is not None:
                updates["lots_override"] = lots_override
            if sl_override is not None:
                updates["sl_override"] = sl_override
            self._update(signal_id, updates)
        _log.info("[MANUAL_Q] Approved %s by %s", signal_id, reviewer)
        return True

    def reject(self, signal_id: str, reviewer: str = "Operator", reason: str = "") -> bool:
        """Reject a pending signal. Returns True if state changed."""
        now = now_ist().isoformat()
        with self._lock:
            sig = self._get(signal_id)
            if sig is None or sig.status != PENDING:
                return False
            self._update(signal_id, {
                "status": REJECTED, "reviewed_by": reviewer,
                "reviewed_at": now, "reject_reason": reason,
            })
        _log.info("[MANUAL_Q] Rejected %s by %s: %s", signal_id, reviewer, reason)
        return True

    def mark_executed(self, signal_id: str, trade_id: str) -> None:
        """Mark a signal as executed with the resulting trade ID."""
        with self._lock:
            self._update(signal_id, {"status": EXECUTED, "execution_trade_id": trade_id})
        _log.info("[MANUAL_Q] Executed %s → trade %s", signal_id, trade_id)

    def cancel(self, signal_id: str, reason: str = "") -> bool:
        """Cancel any active signal."""
        with self._lock:
            sig = self._get(signal_id)
            if sig is None or sig.status in (EXECUTED, EXPIRED, CANCELLED):
                return False
            self._update(signal_id, {
                "status": CANCELLED,
                "reject_reason": reason or "Cancelled",
                "reviewed_at": now_ist().isoformat(),
            })
        _log.info("[MANUAL_Q] Cancelled %s: %s", signal_id, reason)
        return True

    def expire_old(self) -> int:
        """Expire PENDING signals older than timeout_mins. Returns count expired."""
        cutoff = (now_ist() - timedelta(minutes=self._timeout_mins)).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE manual_signals SET status=? WHERE status=? AND submitted_at<?",
                (EXPIRED, PENDING, cutoff),
            )
            self._conn.commit()
            count = cur.rowcount
        if count:
            _log.info("[MANUAL_Q] Expired %d stale signal(s)", count)
        return count

    def maybe_auto_approve(self) -> list[ManualSignal]:
        """Auto-approve signals whose auto_approve_after_secs window has elapsed."""
        if self._auto_approve_secs <= 0:
            return []
        cutoff = (now_ist() - timedelta(seconds=self._auto_approve_secs)).isoformat()
        approved: list[ManualSignal] = []
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM manual_signals
                   WHERE status=? AND auto_approve_after_secs>0 AND submitted_at<?""",
                (PENDING, cutoff),
            ).fetchall()
            for row in rows:
                sig = _row_to_signal(row)
                self._update(sig.signal_id, {
                    "status": APPROVED,
                    "reviewed_by": "AUTO",
                    "reviewed_at": now_ist().isoformat(),
                })
                approved.append(sig)
        return approved

    # ── Public read operations ─────────────────────────────────────────────

    def get_pending(self) -> list[ManualSignal]:
        """Return all PENDING signals, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM manual_signals WHERE status=? ORDER BY submitted_at",
                (PENDING,),
            ).fetchall()
        return [_row_to_signal(r) for r in rows]

    def get_approved(self) -> list[ManualSignal]:
        """Return APPROVED signals not yet executed."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM manual_signals WHERE status=? ORDER BY submitted_at",
                (APPROVED,),
            ).fetchall()
        return [_row_to_signal(r) for r in rows]

    def get_by_id(self, signal_id: str) -> ManualSignal | None:
        with self._lock:
            return self._get(signal_id)

    def get_recent(self, limit: int = 20) -> list[ManualSignal]:
        """Return most recent signals regardless of status."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM manual_signals ORDER BY submitted_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_signal(r) for r in rows]

    def get_stats(self) -> dict[str, Any]:
        """Return summary stats for analytics."""
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM manual_signals").fetchone()[0]
            by_status = dict(self._conn.execute(
                "SELECT status, COUNT(*) FROM manual_signals GROUP BY status"
            ).fetchall())
            executed = by_status.get(EXECUTED, 0)
            approved = by_status.get(APPROVED, 0) + executed
            submitted_today = self._conn.execute(
                "SELECT COUNT(*) FROM manual_signals WHERE date(submitted_at)=date('now')"
            ).fetchone()[0]
            by_analyst = dict(self._conn.execute(
                "SELECT analyst_name, COUNT(*) FROM manual_signals GROUP BY analyst_name"
            ).fetchall())
            by_source = dict(self._conn.execute(
                "SELECT source, COUNT(*) FROM manual_signals GROUP BY source"
            ).fetchall())
            by_index = dict(self._conn.execute(
                "SELECT index_name, COUNT(*) FROM manual_signals GROUP BY index_name"
            ).fetchall())
        approval_rate = round(approved / total * 100, 1) if total else 0.0
        return {
            "total": total,
            "by_status": by_status,
            "submitted_today": submitted_today,
            "approval_rate_pct": approval_rate,
            "by_analyst": by_analyst,
            "by_source": by_source,
            "by_index": by_index,
        }

    def load_pending(self) -> int:
        """Called at startup to log how many pending signals exist from prior session."""
        pending = self.get_pending()
        if pending:
            _log.warning("[MANUAL_Q] %d signal(s) pending from prior session", len(pending))
        return len(pending)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ── Private helpers ────────────────────────────────────────────────────

    def _get(self, signal_id: str) -> ManualSignal | None:
        row = self._conn.execute(
            "SELECT * FROM manual_signals WHERE signal_id=?", (signal_id,)
        ).fetchone()
        return _row_to_signal(row) if row else None

    def _update(self, signal_id: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        set_clause = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [signal_id]
        self._conn.execute(
            f"UPDATE manual_signals SET {set_clause} WHERE signal_id=?", vals
        )
        self._conn.commit()


# ── Factory ────────────────────────────────────────────────────────────────────

def build_signal_queue(cfg: dict[str, Any]) -> ManualSignalQueue | None:
    """Build a ManualSignalQueue if manual_signal_enabled=true (default)."""
    if not cfg.get("manual_signal_enabled", True):
        _log.debug("[MANUAL_Q] Disabled by config")
        return None
    try:
        return ManualSignalQueue(cfg)
    except Exception as exc:
        _log.error("[MANUAL_Q] Init failed: %s", exc)
        return None
