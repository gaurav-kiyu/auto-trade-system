"""
Trade Feedback Journal — tracks expected vs actual execution metrics.

Closes the feedback loop:
    Signal score → expected_pnl (modelled)
    Fill price   → actual_pnl
    Δ           → slippage, execution delay, quality degradation

All writes are async (ThreadPoolExecutor) to avoid blocking the main loop.
Reads (analytics queries) are synchronous.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist

log = logging.getLogger("trade_journal")

_JOURNAL_DB = "trade_journal.db"

# Canonical set of exit reason values written to the journal.
# All exit paths in index_trader.py must produce one of these strings.
# Any unrecognised value is normalised to "unknown" by sanitize_exit_reason().
VALID_EXIT_REASONS: frozenset[str] = frozenset({
    "stop_loss",    # hit the stop-loss price
    "take_profit",  # hit the fixed take-profit target
    "trail_sl",     # trailing stop activated and hit
    "time_exit",    # forced exit at EOD or max position age
    "manual",       # operator closed the position manually
    "unknown",      # fallback — should never appear in a healthy dataset
})

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS journal (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity
    trade_id         TEXT,           -- unique trade reference (e.g. NIFTY-20260421-001)
    symbol           TEXT,
    direction        TEXT,           -- CALL / PUT
    entry_ts         TEXT,           -- signal generation timestamp (ISO)
    fill_ts          TEXT,           -- actual fill timestamp (ISO)

    -- Signal quality at entry
    score            INTEGER,
    tier             TEXT,           -- STRONG / MODERATE / WEAK
    confidence       REAL,           -- 0-1
    regime           TEXT,
    quality_score    REAL,           -- ExecutionPolicy quality score 0-1
    soft_blocks      TEXT,           -- JSON list of soft-block conditions

    -- Expected (model)
    expected_entry   REAL,           -- signal price at generation time
    expected_sl      REAL,
    expected_tp      REAL,
    expected_pnl     REAL,           -- model PnL if TP hit: (tp-entry)×lots×lot_size
    expected_rr      REAL,           -- TP distance / SL distance

    -- Actual (fill)
    actual_entry     REAL,           -- broker fill price
    actual_exit      REAL,
    actual_pnl       REAL,
    exit_reason      TEXT,           -- stop_loss / take_profit / trail_sl / time_exit / manual

    -- Slippage & timing
    entry_slippage   REAL,           -- actual_entry - expected_entry (positive = bad for buyer)
    exit_slippage    REAL,
    total_slippage   REAL,
    execution_delay_ms INTEGER,      -- signal_ts → fill_ts in milliseconds
    slippage_drift   REAL,           -- paper fill mid-price drift: fill_price - mid_price

    -- Position
    lots             INTEGER,
    position_pct     REAL,           -- fraction of max_lots
    lot_size         INTEGER,
    mode             TEXT,           -- PAPER / LIVE

    -- Outcome
    is_winner        INTEGER,        -- 1 / 0
    gross_pnl        REAL,
    net_pnl          REAL,
    pct_pnl          REAL,
    bars_held        INTEGER,
    rr_achieved      REAL,

    -- Feedback
    score_vs_outcome REAL,           -- score × is_winner (for correlation analysis)
    pnl_vs_expected  REAL,           -- actual_pnl - expected_pnl
    quality_accurate INTEGER,        -- 1 if quality_score > 0.5 predicted outcome correctly

    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shadow_trades (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id         TEXT UNIQUE,
    symbol           TEXT,
    direction        TEXT,
    entry_ts         TEXT,
    entry_price      REAL,
    sl_price         REAL,
    tp_price         REAL,
    score            INTEGER,
    tier             TEXT,
    regime           TEXT,
    sentiment        TEXT,
    reasoning        TEXT,
    lots             INTEGER,
    lot_size         INTEGER,
    actual_exit      REAL DEFAULT 0.0,
    exit_ts          TEXT,
    exit_reason      TEXT,
    net_pnl          REAL DEFAULT 0.0,
    is_winner        INTEGER DEFAULT 0,
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_journal_symbol     ON journal(symbol);
CREATE INDEX IF NOT EXISTS ix_journal_tier       ON journal(tier);
CREATE INDEX IF NOT EXISTS ix_journal_entry_ts   ON journal(entry_ts);
CREATE INDEX IF NOT EXISTS ix_journal_mode       ON journal(mode);
CREATE INDEX IF NOT EXISTS ix_journal_created_at ON journal(created_at);
CREATE INDEX IF NOT EXISTS ix_shadow_trade_id     ON shadow_trades(trade_id);
"""


@dataclass
class JournalEntry:
    trade_id: str
    symbol: str
    direction: str
    entry_ts: str
    score: int
    tier: str
    confidence: float
    regime: str
    quality_score: float

    # Expected
    expected_entry: float
    expected_sl: float
    expected_tp: float
    expected_pnl: float
    expected_rr: float

    lots: int
    position_pct: float
    lot_size: int
    mode: str

    # Optional (filled after exit)
    fill_ts: str = ""
    actual_entry: float = 0.0
    actual_exit: float = 0.0
    actual_pnl: float = 0.0
    exit_reason: str = ""
    entry_slippage: float = 0.0
    exit_slippage: float = 0.0
    total_slippage: float = 0.0
    execution_delay_ms: int = 0
    slippage_drift: float = 0.0
    soft_blocks: str = "[]"
    is_winner: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    pct_pnl: float = 0.0
    bars_held: int = 0
    rr_achieved: float = 0.0
    score_vs_outcome: float = 0.0
    pnl_vs_expected: float = 0.0
    quality_accurate: int = 0


class TradeJournal:
    """
    Thread-safe trade feedback journal backed by SQLite.

    Usage:
        journal = TradeJournal("trade_journal.db")

        # At signal generation
        entry = journal.open_trade(signal, decision, expected_entry, ...)

        # At fill (entry confirmed by broker)
        journal.record_fill(trade_id, actual_fill_price, fill_ts)

        # At exit
        journal.close_trade(trade_id, exit_price, exit_reason, net_pnl, ...)
    """

    def __init__(self, db_path: str = _JOURNAL_DB):
        self._db = Path(db_path)
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="journal")
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)
            # Safe migration: add columns introduced in Phase 2 to existing DBs
            try:
                conn.execute("ALTER TABLE journal ADD COLUMN slippage_drift REAL DEFAULT 0.0")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists — normal on fresh or already-migrated DBs

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Open trade (at signal generation) ────────────────────────────────
    def open_trade(
        self,
        *,
        trade_id: str,
        symbol: str,
        direction: str,
        entry_ts: str,
        score: int,
        tier: str,
        confidence: float,
        regime: str,
        quality_score: float,
        expected_entry: float,
        expected_sl: float,
        expected_tp: float,
        lots: int,
        position_pct: float,
        lot_size: int,
        soft_blocks: list[str] | None = None,
        mode: str = "PAPER",
    ) -> JournalEntry:
        sl_dist = abs(expected_entry - expected_sl)
        tp_dist = abs(expected_tp - expected_entry)
        expected_rr   = round(tp_dist / sl_dist, 3) if sl_dist > 0 else 0.0
        # Model P&L: full TP hit
        expected_pnl  = round(tp_dist * lots * lot_size, 2)

        entry = JournalEntry(
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            entry_ts=entry_ts,
            score=score,
            tier=tier,
            confidence=confidence,
            regime=regime,
            quality_score=quality_score,
            expected_entry=expected_entry,
            expected_sl=expected_sl,
            expected_tp=expected_tp,
            expected_pnl=expected_pnl,
            expected_rr=expected_rr,
            lots=lots,
            position_pct=position_pct,
            lot_size=lot_size,
            soft_blocks=json.dumps(soft_blocks or []),
            mode=mode,
        )
        self._pool.submit(self._write_open, entry)
        return entry

    def _write_open(self, e: JournalEntry) -> None:
        cols = [f for f in asdict(e).keys()]
        vals = [getattr(e, f) for f in cols]
        sql  = f"INSERT OR IGNORE INTO journal ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})"
        try:
            with self._lock, self._connect() as conn:
                conn.execute(sql, vals)
                conn.commit()
        except Exception as exc:
            log.error("journal open_trade write error: %s", exc)

    # ── Record fill (at broker confirmation) ─────────────────────────────
    def record_fill(
        self,
        trade_id: str,
        actual_entry: float,
        fill_ts: str,
        execution_delay_ms: int = 0,
    ) -> None:
        self._pool.submit(
            self._write_fill, trade_id, actual_entry, fill_ts, execution_delay_ms
        )

    def _write_fill(
        self, trade_id: str, actual_entry: float, fill_ts: str, delay_ms: int
    ) -> None:
        sql = """
            UPDATE journal
            SET actual_entry = ?,
                fill_ts      = ?,
                execution_delay_ms = ?,
                entry_slippage = actual_entry - expected_entry
            WHERE trade_id = ?
        """
        try:
            with self._lock, self._connect() as conn:
                conn.execute(sql, (actual_entry, fill_ts, delay_ms, trade_id))
                conn.commit()
        except Exception as exc:
            log.error("journal record_fill error: %s", exc)

    # ── Close trade (at exit) ─────────────────────────────────────────────
    def close_trade(
        self,
        trade_id: str,
        *,
        actual_exit: float,
        exit_reason: str,
        net_pnl: float,
        gross_pnl: float,
        pct_pnl: float,
        bars_held: int,
        rr_achieved: float,
        exit_slippage: float = 0.0,
    ) -> None:
        self._pool.submit(
            self._write_close,
            trade_id, actual_exit, exit_reason, net_pnl, gross_pnl,
            pct_pnl, bars_held, rr_achieved, exit_slippage,
        )

    def _write_close(
        self, trade_id: str, actual_exit: float, exit_reason: str,
        net_pnl: float, gross_pnl: float, pct_pnl: float,
        bars_held: int, rr_achieved: float, exit_slippage: float,
    ) -> None:
        is_winner = 1 if net_pnl >= 0 else 0
        try:
            with self._lock, self._connect() as conn:
                # Fetch stored entry_slippage so total_slippage = entry + exit
                row = conn.execute(
                    "SELECT expected_pnl, entry_slippage FROM journal WHERE trade_id=?",
                    (trade_id,)
                ).fetchone()
                ep = float(row["expected_pnl"]) if row else 0.0
                entry_slip = float(row["entry_slippage"] or 0.0) if row else 0.0
                total_slip = round(entry_slip + exit_slippage, 2)
                pnl_vs_exp = round(net_pnl - ep, 2)
                conn.execute("""
                    UPDATE journal
                    SET actual_exit        = ?,
                        exit_reason        = ?,
                        net_pnl            = ?,
                        gross_pnl          = ?,
                        pct_pnl            = ?,
                        bars_held          = ?,
                        rr_achieved        = ?,
                        is_winner          = ?,
                        actual_pnl         = ?,
                        exit_slippage      = ?,
                        total_slippage     = ?,
                        pnl_vs_expected    = ?,
                        score_vs_outcome   = (score * ?),
                        quality_accurate   = CASE
                            WHEN quality_score > 0.5 AND ? = 1 THEN 1
                            WHEN quality_score <= 0.5 AND ? = 0 THEN 1
                            ELSE 0
                        END
                    WHERE trade_id = ?
                """, (
                    actual_exit, exit_reason, net_pnl, gross_pnl,
                    pct_pnl, bars_held, rr_achieved, is_winner, net_pnl,
                    exit_slippage, total_slip, pnl_vs_exp,
                    is_winner, is_winner, is_winner,
                    trade_id,
                ))
                conn.commit()
        except Exception as exc:
            log.error("journal close_trade error: %s", exc)

    # ── Analytics queries ─────────────────────────────────────────────────
    def stats_by_tier(self, mode: str = "PAPER") -> dict[str, Any]:
        """Return win rate, expectancy, avg slippage by tier."""
        sql = """
            SELECT
                tier,
                COUNT(*)                             AS trades,
                SUM(is_winner)                       AS wins,
                ROUND(AVG(net_pnl), 2)               AS avg_net_pnl,
                ROUND(AVG(pct_pnl), 2)               AS avg_pct_pnl,
                ROUND(AVG(total_slippage), 2)        AS avg_slippage,
                ROUND(AVG(execution_delay_ms), 0)    AS avg_delay_ms,
                ROUND(AVG(pnl_vs_expected), 2)       AS avg_pnl_vs_model,
                ROUND(AVG(quality_accurate), 3)      AS quality_accuracy
            FROM journal
            WHERE mode = ? AND actual_exit > 0
            GROUP BY tier
            ORDER BY CASE tier
                WHEN 'STRONG'   THEN 1
                WHEN 'MODERATE' THEN 2
                WHEN 'WEAK'     THEN 3
                ELSE 4
            END
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(sql, (mode,)).fetchall()
            return {
                r["tier"]: {
                    "trades": r["trades"],
                    "wins":   r["wins"],
                    "win_rate": round(r["wins"] / r["trades"] * 100, 1) if r["trades"] else 0.0,
                    "avg_net_pnl":    r["avg_net_pnl"],
                    "avg_pct_pnl":    r["avg_pct_pnl"],
                    "avg_slippage":   r["avg_slippage"],
                    "avg_delay_ms":   r["avg_delay_ms"],
                    "pnl_vs_model":   r["avg_pnl_vs_model"],
                    "quality_accuracy": r["quality_accuracy"],
                }
                for r in rows
            }
        except Exception as exc:
            log.error("stats_by_tier error: %s", exc)
            return {}

    def stats_by_regime(self, mode: str = "PAPER") -> dict[str, Any]:
        sql = """
            SELECT regime,
                   COUNT(*) AS trades,
                   SUM(is_winner) AS wins,
                   ROUND(AVG(net_pnl), 2) AS avg_net_pnl
            FROM journal
            WHERE mode = ? AND actual_exit > 0
            GROUP BY regime
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(sql, (mode,)).fetchall()
            return {r["regime"]: dict(r) for r in rows}
        except Exception as exc:
            log.error("stats_by_regime error: %s", exc)
            return {}

    def expectancy_summary(self, mode: str = "PAPER") -> dict[str, float]:
        sql = """
            SELECT
                ROUND(AVG(CASE WHEN is_winner=1 THEN net_pnl END), 2) AS avg_win,
                ROUND(AVG(CASE WHEN is_winner=0 THEN net_pnl END), 2) AS avg_loss,
                ROUND(1.0*SUM(is_winner)/COUNT(*), 3)                  AS win_rate,
                ROUND(AVG(total_slippage), 2)                          AS avg_slip,
                COUNT(*)                                               AS trades
            FROM journal
            WHERE mode = ? AND actual_exit > 0
        """
        try:
            with self._connect() as conn:
                row = conn.execute(sql, (mode,)).fetchone()
            if not row or not row["trades"]:
                return {}
            wr = float(row["win_rate"] or 0)
            aw = float(row["avg_win"] or 0)
            al = abs(float(row["avg_loss"] or 0))
            return {
                "trades":       row["trades"],
                "win_rate":     round(wr * 100, 1),
                "avg_win":      aw,
                "avg_loss":     float(row["avg_loss"] or 0),
                "expectancy":   round(wr * aw - (1 - wr) * al, 2),
                "avg_slippage": float(row["avg_slip"] or 0),
            }
        except Exception as exc:
            log.error("expectancy_summary error: %s", exc)
            return {}

    def recent_trades(self, n: int = 10, mode: str = "PAPER") -> list[dict]:
        sql = """
            SELECT trade_id, symbol, direction, entry_ts, tier, score, regime,
                   net_pnl, pct_pnl, exit_reason, is_winner,
                   entry_slippage, execution_delay_ms, quality_score
            FROM journal
            WHERE mode = ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(sql, (mode, n)).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            log.error("recent_trades error: %s", exc)
            return []

    def log_shadow_trade(
        self,
        trade_id: str,
        symbol: str,
        direction: str,
        entry_ts: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        score: int,
        tier: str,
        regime: str,
        sentiment: str,
        reasoning: str,
        lots: int,
        lot_size: int,
    ) -> None:
        """Log a virtual signal to the shadow_trades table for theoretical P&L tracking."""
        sql = """
            INSERT OR IGNORE INTO shadow_trades (
                trade_id, symbol, direction, entry_ts, entry_price,
                sl_price, tp_price, score, tier, regime,
                sentiment, reasoning, lots, lot_size
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        vals = (
            trade_id, symbol, direction, entry_ts, entry_price,
            sl_price, tp_price, score, tier, regime,
            sentiment, reasoning, lots, lot_size
        )
        try:
            with self._lock, self._connect() as conn:
                conn.execute(sql, vals)
                conn.commit()
        except Exception as exc:
            log.error("journal log_shadow_trade error: %s", exc)


    @staticmethod
    def sanitize_exit_reason(reason: str) -> str:
        """Normalise exit_reason to a known value before writing to the journal.

        Call this at every close_trade() call site in index_trader.py to ensure
        the training dataset never contains free-form or empty exit labels.

        Example:
            journal.close_trade(trade_id, exit_reason=TradeJournal.sanitize_exit_reason(raw_reason), ...)
        """
        if reason in VALID_EXIT_REASONS:
            return reason
        log.warning(
            "Unrecognised exit_reason %r — recording as 'unknown'. "
            "Expected one of: %s",
            reason,
            ", ".join(sorted(VALID_EXIT_REASONS)),
        )
        return "unknown"

    def shutdown(self) -> None:
        """Flush any pending writes and release resources. Safe to call multiple times."""
        try:
            # Drain pending async writes before closing
            self._pool.shutdown(wait=True)
        except Exception:
            pass
        try:
            conn = self._connect()
            conn.commit()
            conn.close()
        except Exception:
            pass
        log.info("[TradeJournal] Shutdown complete.")

    def export_to_json(self, filepath: str, mode: str = "PAPER") -> dict[str, Any]:
        """
        Export trade journal to JSON format.

        Parameters
        ----------
        filepath : str
            Path to output JSON file
        mode     : str
            Filter by mode (PAPER/LIVE), default: PAPER

        Returns
        -------
        dict with: export_status, trade_count, filepath
        """
        try:
            with self._lock, self._connect() as conn:
                # Fetch all trades for the mode
                sql = """
                    SELECT * FROM journal WHERE mode = ? ORDER BY entry_ts DESC
                """
                cursor = conn.execute(sql, (mode,))
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()

                # Convert to list of dicts
                trades = []
                for row in rows:
                    trade = dict(zip(columns, row))
                    # Convert soft_blocks from JSON string if present
                    if trade.get('soft_blocks'):
                        try:
                            trade['soft_blocks'] = json.loads(trade['soft_blocks'])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    trades.append(trade)

                # Create export data
                export_data = {
                    "export_metadata": {
                        "mode": mode,
                        "trade_count": len(trades),
                        "exported_at": str(now_ist().isoformat()),
                        "schema_version": "1.0"
                    },
                    "trades": trades
                }

                # Write to file
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, indent=2, default=str)

                log.info(f"[TradeJournal] Exported {len(trades)} trades to {filepath}")

                return {
                    "export_status": "SUCCESS",
                    "trade_count": len(trades),
                    "filepath": filepath
                }

        except Exception as exc:
            log.error(f"[TradeJournal] JSON export failed: {exc}")
            return {
                "export_status": "FAILED",
                "trade_count": 0,
                "error": str(exc)
            }
