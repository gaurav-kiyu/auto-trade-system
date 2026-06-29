"""
Tests for core/trade_journal.py - Trade Feedback Journal.

Covers:
  - JournalEntry dataclass
  - TradeJournal initialization and DB schema
  - Open trade, record fill, close trade lifecycle
  - Analytics queries (stats_by_tier, stats_by_regime, expectancy_summary, recent_trades)
  - Shadow trade logging
  - Exit reason sanitization
  - JSON export
  - Shutdown and cleanup
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from core.trade_journal import (
    VALID_EXIT_REASONS,
    JournalEntry,
    TradeJournal,
)

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "trade_journal.db")


@pytest.fixture()
def journal(db_path: str) -> TradeJournal:
    return TradeJournal(db_path=db_path)


@pytest.fixture()
def sample_entry() -> dict[str, Any]:
    return {
        "trade_id": "NIFTY-20260611-001",
        "symbol": "NIFTY",
        "direction": "CALL",
        "entry_ts": "2026-06-11T09:30:00",
        "score": 85,
        "tier": "STRONG",
        "confidence": 0.85,
        "regime": "TRENDING",
        "quality_score": 0.9,
        "expected_entry": 23500.0,
        "expected_sl": 23450.0,
        "expected_tp": 23600.0,
        "lots": 1,
        "position_pct": 0.5,
        "lot_size": 50,
        "mode": "PAPER",
    }


# ── JournalEntry Dataclass ───────────────────────────────────────────


class TestJournalEntry:
    def test_default_values(self) -> None:
        entry = JournalEntry(
            trade_id="T1", symbol="NIFTY", direction="CALL",
            entry_ts="2026-06-11T09:30", score=80, tier="STRONG",
            confidence=0.8, regime="TRENDING", quality_score=0.9,
            expected_entry=23500.0, expected_sl=23450.0,
            expected_tp=23600.0, expected_pnl=7500.0, expected_rr=2.0,
            lots=1, position_pct=0.5, lot_size=50, mode="PAPER",
        )
        assert entry.fill_ts == ""
        assert entry.actual_entry == 0.0
        assert entry.actual_pnl == 0.0
        assert entry.is_winner == 0

    def test_with_all_fields(self) -> None:
        entry = JournalEntry(
            trade_id="T1", symbol="NIFTY", direction="CALL",
            entry_ts="2026-06-11T09:30", score=80, tier="STRONG",
            confidence=0.8, regime="TRENDING", quality_score=0.9,
            expected_entry=23500.0, expected_sl=23450.0,
            expected_tp=23600.0, expected_pnl=7500.0, expected_rr=2.0,
            lots=1, position_pct=0.5, lot_size=50, mode="PAPER",
            fill_ts="2026-06-11T09:30:05",
            actual_entry=23502.5,
            actual_exit=23605.0,
            actual_pnl=5000.0,
            exit_reason="take_profit",
            is_winner=1,
        )
        assert entry.fill_ts == "2026-06-11T09:30:05"
        assert entry.actual_entry == 23502.5
        assert entry.is_winner == 1

    def test_expected_rr_calculation(self) -> None:
        sl_dist = abs(23500.0 - 23450.0)
        tp_dist = abs(23600.0 - 23500.0)
        expected_rr = round(tp_dist / sl_dist, 3)
        entry = JournalEntry(
            trade_id="T1", symbol="NIFTY", direction="CALL",
            entry_ts="2026-06-11T09:30", score=80, tier="STRONG",
            confidence=0.8, regime="TRENDING", quality_score=0.9,
            expected_entry=23500.0, expected_sl=23450.0,
            expected_tp=23600.0, expected_pnl=7500.0, expected_rr=expected_rr,
            lots=1, position_pct=0.5, lot_size=50, mode="PAPER",
        )
        assert entry.expected_rr == 2.0


# ── TradeJournal Initialization ──────────────────────────────────────


class TestInit:
    def test_init_creates_db(self, db_path: str) -> None:
        assert not Path(db_path).exists()
        TradeJournal(db_path=db_path)
        assert Path(db_path).exists()

    def test_init_creates_tables(self, journal: TradeJournal) -> None:
        conn = journal._connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()
        names = [r[0] for r in tables]
        assert "journal" in names
        assert "shadow_trades" in names

    def test_reinit_migration_safe(self, journal: TradeJournal) -> None:
        """Re-initializing the same DB should not error."""
        j2 = TradeJournal(db_path=journal._db)
        conn = j2._connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        assert len(tables) >= 2


# ── Trade Lifecycle ──────────────────────────────────────────────────


class TestTradeLifecycle:
    def test_open_trade_returns_entry(self, journal: TradeJournal, sample_entry: dict[str, Any]) -> None:
        entry = journal.open_trade(**sample_entry)
        assert isinstance(entry, JournalEntry)
        assert entry.trade_id == sample_entry["trade_id"]

    def test_open_trade_writes_to_db(self, journal: TradeJournal, sample_entry: dict[str, Any]) -> None:
        journal.open_trade(**sample_entry)
        # Force flush by waiting for async pool
        journal.shutdown()
        conn = journal._connect()
        row = conn.execute(
            "SELECT trade_id, score, tier FROM journal WHERE trade_id=?",
            (sample_entry["trade_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["score"] == sample_entry["score"]

    def test_open_trade_expected_rr(self, journal: TradeJournal, sample_entry: dict[str, Any]) -> None:
        entry = journal.open_trade(**sample_entry)
        assert entry.expected_rr == 2.0
        assert entry.expected_pnl > 0

    def test_record_fill_updates_entry(self, journal: TradeJournal, sample_entry: dict[str, Any]) -> None:
        journal.open_trade(**sample_entry)
        journal.record_fill(
            trade_id=sample_entry["trade_id"],
            actual_entry=23502.5,
            fill_ts="2026-06-11T09:30:05",
            execution_delay_ms=5000,
        )
        journal.shutdown()
        conn = journal._connect()
        row = conn.execute(
            "SELECT actual_entry, execution_delay_ms FROM journal WHERE trade_id=?",
            (sample_entry["trade_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["actual_entry"] == 23502.5
        assert row["execution_delay_ms"] == 5000

    def test_close_trade_marks_winner(self, journal: TradeJournal, sample_entry: dict[str, Any]) -> None:
        journal.open_trade(**sample_entry)
        journal.record_fill(
            trade_id=sample_entry["trade_id"],
            actual_entry=23502.5,
            fill_ts="2026-06-11T09:30:05",
        )
        journal.close_trade(
            trade_id=sample_entry["trade_id"],
            actual_exit=23605.0,
            exit_reason="take_profit",
            net_pnl=5000.0,
            gross_pnl=5100.0,
            pct_pnl=0.5,
            bars_held=45,
            rr_achieved=2.1,
        )
        journal.shutdown()
        conn = journal._connect()
        row = conn.execute(
            "SELECT is_winner, net_pnl, exit_reason FROM journal WHERE trade_id=?",
            (sample_entry["trade_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["is_winner"] == 1
        assert row["net_pnl"] == 5000.0
        assert row["exit_reason"] == "take_profit"

    def test_close_trade_marks_loser(self, journal: TradeJournal, sample_entry: dict[str, Any]) -> None:
        journal.open_trade(**sample_entry)
        journal.close_trade(
            trade_id=sample_entry["trade_id"],
            actual_exit=23450.0,
            exit_reason="stop_loss",
            net_pnl=-2500.0,
            gross_pnl=-2400.0,
            pct_pnl=-0.25,
            bars_held=15,
            rr_achieved=0.0,
        )
        journal.shutdown()
        conn = journal._connect()
        row = conn.execute(
            "SELECT is_winner, net_pnl FROM journal WHERE trade_id=?",
            (sample_entry["trade_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["is_winner"] == 0
        assert row["net_pnl"] == -2500.0

    def test_full_lifecycle(self, journal: TradeJournal, sample_entry: dict[str, Any]) -> None:
        """Open, fill, close - all steps together."""
        journal.open_trade(**sample_entry)
        # Flush async writes before proceeding
        journal._pool.shutdown(wait=True)
        journal._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="journal")
        journal.record_fill(sample_entry["trade_id"], 23502.5,
                            "2026-06-11T09:30:05", 5000)
        journal._pool.shutdown(wait=True)
        journal._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="journal")
        journal.close_trade(sample_entry["trade_id"],
                            actual_exit=23605.0,
                            exit_reason="take_profit",
                            net_pnl=5000.0,
                            gross_pnl=5100.0,
                            pct_pnl=0.5,
                            bars_held=45,
                            rr_achieved=2.1)
        journal.shutdown()
        conn = journal._connect()
        row = conn.execute(
            "SELECT is_winner, entry_slippage, total_slippage FROM journal WHERE trade_id=?",
            (sample_entry["trade_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        # entry_slippage = 23502.5 - 23500.0 = 2.5
        assert round(row["entry_slippage"], 1) == 2.5


# ── Analytics Queries ────────────────────────────────────────────────


class TestAnalytics:
    def test_stats_by_tier_empty(self, journal: TradeJournal) -> None:
        stats = journal.stats_by_tier(mode="PAPER")
        assert stats == {}

    def test_stats_by_tier_with_trades(self, journal: TradeJournal, sample_entry: dict[str, Any]) -> None:
        journal.open_trade(**sample_entry)
        journal.close_trade(sample_entry["trade_id"],
                            actual_exit=23605.0,
                            exit_reason="take_profit",
                            net_pnl=5000.0,
                            gross_pnl=5100.0,
                            pct_pnl=0.5,
                            bars_held=45,
                            rr_achieved=2.1)
        journal.shutdown()
        stats = journal.stats_by_tier(mode="PAPER")
        assert "STRONG" in stats
        assert stats["STRONG"]["trades"] >= 1

    def test_stats_by_regime_empty(self, journal: TradeJournal) -> None:
        stats = journal.stats_by_regime(mode="PAPER")
        assert stats == {}

    def test_stats_by_regime_with_trades(self, journal: TradeJournal, sample_entry: dict[str, Any]) -> None:
        journal.open_trade(**sample_entry)
        journal.close_trade(sample_entry["trade_id"],
                            actual_exit=23605.0,
                            exit_reason="take_profit",
                            net_pnl=5000.0,
                            gross_pnl=5100.0,
                            pct_pnl=0.5,
                            bars_held=45,
                            rr_achieved=2.1)
        journal.shutdown()
        stats = journal.stats_by_regime(mode="PAPER")
        assert "TRENDING" in stats

    def test_expectancy_summary_empty(self, journal: TradeJournal) -> None:
        summary = journal.expectancy_summary(mode="PAPER")
        assert summary == {}

    def test_expectancy_summary_with_trades(self, journal: TradeJournal, sample_entry: dict[str, Any]) -> None:
        journal.open_trade(**sample_entry)
        journal.close_trade(sample_entry["trade_id"],
                            actual_exit=23605.0,
                            exit_reason="take_profit",
                            net_pnl=5000.0,
                            gross_pnl=5100.0,
                            pct_pnl=0.5,
                            bars_held=45,
                            rr_achieved=2.1)
        journal.shutdown()
        summary = journal.expectancy_summary(mode="PAPER")
        assert "trades" in summary
        assert summary["trades"] >= 1
        assert "expectancy" in summary

    def test_recent_trades_empty(self, journal: TradeJournal) -> None:
        trades = journal.recent_trades(n=5, mode="PAPER")
        assert trades == []

    def test_recent_trades_with_data(self, journal: TradeJournal, sample_entry: dict[str, Any]) -> None:
        journal.open_trade(**sample_entry)
        journal.close_trade(sample_entry["trade_id"],
                            actual_exit=23605.0,
                            exit_reason="take_profit",
                            net_pnl=5000.0,
                            gross_pnl=5100.0,
                            pct_pnl=0.5,
                            bars_held=45,
                            rr_achieved=2.1)
        journal.shutdown()
        trades = journal.recent_trades(n=5, mode="PAPER")
        assert len(trades) >= 1
        assert trades[0]["trade_id"] == sample_entry["trade_id"]


# ── Shadow Trades ────────────────────────────────────────────────────


class TestShadowTrades:
    def test_log_shadow_trade(self, journal: TradeJournal) -> None:
        journal.log_shadow_trade(
            trade_id="SHADOW-001",
            symbol="NIFTY",
            direction="CALL",
            entry_ts="2026-06-11T09:30",
            entry_price=23500.0,
            sl_price=23450.0,
            tp_price=23600.0,
            score=85,
            tier="STRONG",
            regime="TRENDING",
            sentiment="BULLISH",
            reasoning="Strong breakout",
            lots=1,
            lot_size=50,
        )
        journal.shutdown()
        conn = journal._connect()
        row = conn.execute(
            "SELECT trade_id, score, sentiment FROM shadow_trades WHERE trade_id=?",
            ("SHADOW-001",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["score"] == 85
        assert row["sentiment"] == "BULLISH"

    def test_duplicate_shadow_trade_ignored(self, journal: TradeJournal) -> None:
        journal.log_shadow_trade(
            trade_id="SHADOW-001", symbol="NIFTY", direction="CALL",
            entry_ts="09:30", entry_price=23500.0,
            sl_price=23450.0, tp_price=23600.0,
            score=85, tier="STRONG", regime="TRENDING",
            sentiment="BULLISH", reasoning="test", lots=1, lot_size=50,
        )
        journal.log_shadow_trade(
            trade_id="SHADOW-001", symbol="NIFTY", direction="CALL",
            entry_ts="09:30", entry_price=23500.0,
            sl_price=23450.0, tp_price=23600.0,
            score=85, tier="STRONG", regime="TRENDING",
            sentiment="BULLISH", reasoning="test", lots=1, lot_size=50,
        )
        journal.shutdown()
        conn = journal._connect()
        rows = conn.execute(
            "SELECT COUNT(*) AS cnt FROM shadow_trades WHERE trade_id='SHADOW-001'"
        ).fetchone()
        conn.close()
        assert rows["cnt"] == 1


# ── Exit Reason Sanitization ─────────────────────────────────────────


class TestSanitizeExitReason:
    def test_valid_reasons_accepted(self) -> None:
        for reason in VALID_EXIT_REASONS:
            assert TradeJournal.sanitize_exit_reason(reason) == reason

    def test_unknown_reason_normalized(self) -> None:
        assert TradeJournal.sanitize_exit_reason("unknown_reason") == "unknown"
        assert TradeJournal.sanitize_exit_reason("") == "unknown"
        assert TradeJournal.sanitize_exit_reason("invalid!") == "unknown"

    def test_valid_reasons_set(self) -> None:
        assert "stop_loss" in VALID_EXIT_REASONS
        assert "take_profit" in VALID_EXIT_REASONS
        assert "trail_sl" in VALID_EXIT_REASONS
        assert "time_exit" in VALID_EXIT_REASONS
        assert "manual" in VALID_EXIT_REASONS
        assert "unknown" in VALID_EXIT_REASONS


# ── JSON Export ──────────────────────────────────────────────────────


class TestJSONExport:
    def test_export_empty(self, journal: TradeJournal, tmp_path: Path) -> None:
        out = str(tmp_path / "export.json")
        result = journal.export_to_json(out, mode="PAPER")
        assert result["export_status"] == "SUCCESS"
        assert result["trade_count"] == 0

    def test_export_with_trades(
        self, journal: TradeJournal, sample_entry: dict[str, Any], tmp_path: Path
    ) -> None:
        journal.open_trade(**sample_entry)
        journal.close_trade(sample_entry["trade_id"],
                            actual_exit=23605.0,
                            exit_reason="take_profit",
                            net_pnl=5000.0,
                            gross_pnl=5100.0,
                            pct_pnl=0.5,
                            bars_held=45,
                            rr_achieved=2.1)
        journal.shutdown()
        out = str(tmp_path / "export.json")
        result = journal.export_to_json(out, mode="PAPER")
        assert result["export_status"] == "SUCCESS"
        assert result["trade_count"] >= 1

    def test_export_creates_valid_json(
        self, journal: TradeJournal, sample_entry: dict[str, Any], tmp_path: Path
    ) -> None:
        journal.open_trade(**sample_entry)
        journal.shutdown()
        out = str(tmp_path / "export.json")
        journal.export_to_json(out, mode="PAPER")
        data = json.loads(Path(out).read_text())
        assert "trades" in data
        assert "export_metadata" in data


# ── Shutdown ─────────────────────────────────────────────────────────


class TestShutdown:
    def test_shutdown_drains_pool(self, journal: TradeJournal, sample_entry: dict[str, Any]) -> None:
        journal.open_trade(**sample_entry)
        journal.shutdown()
        # After shutdown, the pool is drained and conn is closed
        # verify by reading from DB directly
        conn = journal._connect()
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM journal"
        ).fetchone()
        conn.close()
        assert row["cnt"] >= 1

    def test_shutdown_safe_multiple_times(self, journal: TradeJournal) -> None:
        journal.shutdown()
        journal.shutdown()  # Should not raise


# ── Error Handling ───────────────────────────────────────────────────


class TestErrorHandling:
    def test_invalid_db_path_raises(self) -> None:
        """Should raise on invalid path since __init__ calls _init_db."""
        import sqlite3
        with pytest.raises(sqlite3.OperationalError):
            TradeJournal(db_path=r"Z:\nonexistent\trade_journal.db")
