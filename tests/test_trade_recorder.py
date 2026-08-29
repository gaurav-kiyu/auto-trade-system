"""Tests for core.trade_recorder — legacy trades.db closed-trade recorder.

Covers:
1. ensure_legacy_trades_schema creates the legacy trades table (idempotent)
2. record_closed_trade appends rows with correct column values
3. The recorder is defensive — never raises on bad paths / bad values
4. resolve_trades_db_path honors trades_db_path > trades_db > None
5. End-to-end: recorded PAPER trades are visible to the live-readiness gate
   (the exact gap that blocked the 50-trade track record), and LIVE trades
   are correctly excluded from the paper-trade count
"""

from __future__ import annotations

import sqlite3

from core.datetime_ist import now_ist
from core.live_readiness_checker import _load_paper_trades, check_live_readiness
from core.trade_recorder import (
    ensure_legacy_trades_schema,
    record_closed_trade,
    resolve_trades_db_path,
)

_LEGACY_COLS = {
    "id", "ts", "index_name", "direction", "entry", "exit_price", "qty",
    "gross_pnl", "net_pnl", "reason", "regime", "score", "iv", "vix",
    "ltp_estimated", "partial", "sl_warned", "mode", "version",
}


def _columns(db_path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(trades)")}
    finally:
        conn.close()
    return cols


def _fetchrow(db_path, rowid):
    """Fetch a row dict via the project's connection helper (row_factory=Row)."""
    from core.db_utils import get_connection

    conn = get_connection(str(db_path), timeout=5)
    try:
        return conn.execute("SELECT * FROM trades WHERE id = ?", (rowid,)).fetchone()
    finally:
        conn.close()


# ── ensure_legacy_trades_schema ────────────────────────────────────────────────

class TestEnsureSchema:
    def test_creates_table_with_legacy_columns(self, tmp_path):
        db = tmp_path / "trades.db"
        assert ensure_legacy_trades_schema(db) is True
        assert _LEGACY_COLS <= _columns(db)

    def test_idempotent(self, tmp_path):
        db = tmp_path / "trades.db"
        assert ensure_legacy_trades_schema(db) is True
        assert ensure_legacy_trades_schema(db) is True  # no error on second call
        assert _LEGACY_COLS <= _columns(db)

    def test_bad_path_returns_false_no_raise(self, tmp_path):
        # A directory path cannot be opened as a DB file
        assert ensure_legacy_trades_schema(tmp_path) is False


# ── record_closed_trade ───────────────────────────────────────────────────────

class TestRecordClosedTrade:
    def test_inserts_row_with_values(self, tmp_path):
        db = tmp_path / "trades.db"
        rowid = record_closed_trade(
            db,
            ts="2026-08-07T10:30:00",
            index_name="NIFTY",
            direction="CALL",
            entry=100.0,
            exit_price=112.0,
            qty=75,
            gross_pnl=900.0,
            net_pnl=860.0,
            reason="TARGET_HIT",
            mode="PAPER",
            regime="TRENDING",
            score=78,
            version="v2.57.1",
        )
        assert isinstance(rowid, int) and rowid > 0

        row = _fetchrow(db, rowid)
        assert row is not None
        assert row["index_name"] == "NIFTY"
        assert row["direction"] == "CALL"
        assert row["entry"] == 100.0
        assert row["exit_price"] == 112.0
        assert row["qty"] == 75
        assert row["gross_pnl"] == 900.0
        assert row["net_pnl"] == 860.0
        assert row["reason"] == "TARGET_HIT"
        assert row["mode"] == "PAPER"
        assert row["regime"] == "TRENDING"
        assert row["score"] == 78
        assert row["version"] == "v2.57.1"
        # Legacy defaulted flags
        assert row["ltp_estimated"] == 0
        assert row["partial"] == 0
        assert row["sl_warned"] == 0

    def test_default_mode_is_paper(self, tmp_path):
        db = tmp_path / "trades.db"
        rowid = record_closed_trade(
            db, ts="2026-08-07T10:30:00", index_name="BANKNIFTY",
            direction="PUT", entry=100.0, exit_price=95.0, qty=1,
            gross_pnl=-5.0, net_pnl=-5.0, reason="SL_HIT",
        )
        conn = sqlite3.connect(str(db))
        try:
            mode = conn.execute(
                "SELECT mode FROM trades WHERE id = ?", (rowid,)
            ).fetchone()[0]
        finally:
            conn.close()
        assert mode == "PAPER"

    def test_never_raises_on_bad_path(self, tmp_path):
        # Directory as db_path — must return None, not raise
        assert record_closed_trade(
            tmp_path, ts="x", index_name="NIFTY", direction="CALL",
            entry=1.0, exit_price=1.0, qty=1,
            gross_pnl=0.0, net_pnl=0.0, reason="MANUAL",
        ) is None

    def test_optional_fields_may_be_none(self, tmp_path):
        db = tmp_path / "trades.db"
        # Optional analytics fields (regime/score/iv/vix) can be None
        rowid = record_closed_trade(
            db, ts="2026-08-07T10:30:00", index_name="NIFTY", direction="CALL",
            entry=100.0, exit_price=105.0, qty=1,
            gross_pnl=5.0, net_pnl=5.0, reason="MANUAL",
            regime=None, score=None, iv=None, vix=None,
        )
        assert isinstance(rowid, int) and rowid > 0
        row = _fetchrow(db, rowid)
        assert row["regime"] is None and row["score"] is None

    def test_never_raises_on_bad_values(self, tmp_path):
        db = tmp_path / "trades.db"
        # Garbage core values — recorder must return None without raising
        assert record_closed_trade(
            db, ts=None, index_name=None, direction=None, entry=None,
            exit_price=None, qty=None, gross_pnl=None, net_pnl=None,
            reason=None,
        ) is None

    def test_records_multiple_rows(self, tmp_path):
        db = tmp_path / "trades.db"
        for i in range(5):
            record_closed_trade(
                db, ts="2026-08-07T10:30:00", index_name="NIFTY",
                direction="CALL", entry=100.0, exit_price=100.0 + i, qty=1,
                gross_pnl=float(i), net_pnl=float(i), reason="MANUAL",
            )
        conn = sqlite3.connect(str(db))
        try:
            n = conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()[0]
        finally:
            conn.close()
        assert n == 5


# ── resolve_trades_db_path ────────────────────────────────────────────────────

class TestResolveDbPath:
    def test_none_when_no_keys(self):
        assert resolve_trades_db_path({}) is None
        assert resolve_trades_db_path(None) is None
        assert resolve_trades_db_path({"SL_PCT": 0.92}) is None

    def test_trades_db_path_precedence(self):
        cfg = {"trades_db_path": "data/trades.db", "trades_db": "trades.db"}
        assert resolve_trades_db_path(cfg) == "data/trades.db"

    def test_trades_db_fallback(self):
        assert resolve_trades_db_path({"trades_db": "custom.db"}) == "custom.db"


# ── End-to-end: readiness gate sees recorded paper trades ─────────────────────

class TestReadinessGateIntegration:
    def test_gate_counts_recorded_paper_trades(self, tmp_path):
        db = tmp_path / "trades.db"
        cfg = {"live_readiness_days_window": 365}

        # 3 winning PAPER trades + 1 losing PAPER trade
        for i, pnl in enumerate([100.0, 50.0, -30.0, 200.0]):
            record_closed_trade(
                db,
                ts=now_ist().isoformat(),
                index_name="NIFTY",
                direction="CALL",
                entry=100.0,
                exit_price=100.0 + pnl / 25,  # any consistent numbers
                qty=25,
                gross_pnl=pnl,
                net_pnl=pnl,
                reason="TARGET_HIT" if pnl > 0 else "SL_HIT",
                mode="PAPER",
            )
        # 1 LIVE trade — must be excluded from the paper-trade count
        record_closed_trade(
            db,
            ts=now_ist().isoformat(),
            index_name="NIFTY",
            direction="PUT",
            entry=100.0,
            exit_price=90.0,
            qty=25,
            gross_pnl=-250.0,
            net_pnl=-250.0,
            reason="SL_HIT",
            mode="LIVE",
        )

        trades = _load_paper_trades(str(db), 365)
        assert len(trades) == 4  # only PAPER rows

        report = check_live_readiness(str(db), cfg)
        min_trades = next(c for c in report.criteria if c.name == "Minimum paper trades")
        assert min_trades.actual == 4
        assert report.overall_ready is False  # 4 < 50, so still not ready

    def test_gate_sees_zero_without_recorder(self, tmp_path):
        db = tmp_path / "trades.db"
        assert check_live_readiness(str(db), {"live_readiness_days_window": 365}).overall_ready is False
