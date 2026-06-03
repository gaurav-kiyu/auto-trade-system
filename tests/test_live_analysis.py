"""Unit tests for core.live_analysis — performance analysis via mocked SQLite DB."""

from __future__ import annotations

import sqlite3
import tempfile

from typing import Any

import pytest

from core.live_analysis import (
    _calc_max_drawdown,
    _generate_decisions,
    _rows,
    analyze_live_performance,
    print_live_performance,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def journal_db() -> str:
    """Create a temporary trade_journal.db with sample data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT,
            symbol TEXT,
            direction TEXT,
            mode TEXT,
            tier TEXT,
            regime TEXT,
            score INTEGER,
            is_winner INTEGER,
            net_pnl REAL,
            total_slippage REAL,
            entry_slippage REAL,
            exit_slippage REAL,
            execution_delay_ms REAL,
            rr_achieved REAL,
            pnl_vs_expected REAL,
            pct_pnl REAL,
            exit_reason TEXT,
            quality_score REAL,
            quality_accurate REAL,
            soft_blocks TEXT,
            entry_ts TEXT,
            created_at TEXT,
            actual_exit INTEGER
        )
    """)

    sample_trades = [
        ("T1", "NIFTY", "CALL", "PAPER", "STRONG", "TRENDING", 85, 1, 500.0, 2.5, 1.0, 1.5, 50, 2.0, 10.0, 5.0, "take_profit", 0.9, 0.85, "[]", "2026-05-01T09:30:00", "2026-05-01T10:00:00", 1),
        ("T2", "NIFTY", "PUT", "PAPER", "MODERATE", "NEUTRAL", 72, 1, 200.0, 1.5, 0.5, 1.0, 30, 1.5, 5.0, 3.0, "take_profit", 0.8, 0.75, "[]", "2026-05-01T11:00:00", "2026-05-01T11:30:00", 1),
        ("T3", "BANKNIFTY", "CALL", "PAPER", "STRONG", "CHOPPY", 68, 0, -300.0, 3.0, 1.5, 1.5, 100, 0.5, -8.0, -2.0, "stop_loss", 0.7, 0.65, '["low_oi"]', "2026-05-02T09:45:00", "2026-05-02T10:15:00", 1),
        ("T4", "NIFTY", "PUT", "PAPER", "WEAK", "TRENDING", 62, 0, -150.0, 2.0, 1.0, 1.0, 80, 0.3, -5.0, -1.5, "stop_loss", 0.6, 0.55, "[]", "2026-05-02T13:00:00", "2026-05-02T13:30:00", 1),
        ("T5", "FINNIFTY", "CALL", "PAPER", "MODERATE", "NEUTRAL", 78, 1, 350.0, 1.0, 0.5, 0.5, 20, 2.5, 8.0, 4.0, "take_profit", 0.85, 0.80, "[]", "2026-05-03T09:30:00", "2026-05-03T10:00:00", 1),
    ]

    for t in sample_trades:
        conn.execute("""
            INSERT INTO journal
            (trade_id, symbol, direction, mode, tier, regime, score, is_winner,
             net_pnl, total_slippage, entry_slippage, exit_slippage,
             execution_delay_ms, rr_achieved, pnl_vs_expected, pct_pnl,
             exit_reason, quality_score, quality_accurate, soft_blocks,
             entry_ts, created_at, actual_exit)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, t)

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def empty_db() -> str:
    """Create a temporary trade_journal.db with no data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT,
            mode TEXT,
            is_winner INTEGER,
            net_pnl REAL,
            total_slippage REAL,
            execution_delay_ms REAL,
            rr_achieved REAL,
            pnl_vs_expected REAL,
            score INTEGER,
            tier TEXT,
            regime TEXT,
            entry_slippage REAL,
            exit_slippage REAL,
            quality_score REAL,
            quality_accurate REAL,
            soft_blocks TEXT,
            entry_ts TEXT,
            created_at TEXT,
            actual_exit INTEGER,
            exit_reason TEXT,
            direction TEXT,
            pct_pnl REAL,
            symbol TEXT
        )
    """)
    conn.commit()
    conn.close()
    return db_path


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestRows:
    def test_rows_returns_list(self, journal_db: str) -> None:
        rows = _rows(journal_db, "SELECT * FROM journal LIMIT 1")
        assert len(rows) >= 1

    def test_rows_empty_db(self, empty_db: str) -> None:
        rows = _rows(empty_db, "SELECT * FROM journal")
        assert len(rows) == 0

    def test_rows_nonexistent_db(self) -> None:
        rows = _rows("/nonexistent/path.db", "SELECT 1")
        assert rows == []


class TestCalcMaxDrawdown:
    def test_empty_series(self) -> None:
        assert _calc_max_drawdown([]) == 0.0

    def test_single_value(self) -> None:
        assert _calc_max_drawdown([100.0]) == 0.0

    def test_rising_equity_no_dd(self) -> None:
        assert _calc_max_drawdown([100, 200, 300]) == 0.0

    def test_falling_equity_has_dd(self) -> None:
        # PnL series: 100 then -30 then -20 = equity: 100, 70, 50
        dd = _calc_max_drawdown([100, -30, -20])
        assert dd > 0.0

    def test_peak_to_trough(self) -> None:
        # PnL series: 1000, 1000, -1500, 1000 = equity: 1000, 2000, 500, 1500
        # Peak=2000, trough=500, dd = (2000-500)/2000 = 75%
        dd = _calc_max_drawdown([1000, 1000, -1500, 1000])
        assert dd == pytest.approx(75.0, rel=0.1)


class TestGenerateDecisions:
    def test_empty_tiers(self) -> None:
        avoid, prio = _generate_decisions({}, {}, {})
        assert avoid == []
        assert prio == []

    def test_negative_expectancy_triggers_avoid(self) -> None:
        by_tier = {"WEAK": {"win_rate": 30.0, "expectancy": -50.0, "trades": 10}}
        avoid, prio = _generate_decisions(by_tier, {}, {})
        assert len(avoid) >= 1
        assert any("WEAK" in a for a in avoid)

    def test_positive_edge_triggers_priority(self) -> None:
        by_tier = {"STRONG": {"win_rate": 65.0, "expectancy": 100.0, "trades": 15}}
        avoid, prio = _generate_decisions(by_tier, {}, {})
        assert len(prio) >= 1
        assert any("STRONG" in p for p in prio)

    def test_insufficient_trades_no_decision(self) -> None:
        by_tier = {"WEAK": {"win_rate": 30.0, "expectancy": -50.0, "trades": 2}}
        avoid, prio = _generate_decisions(by_tier, {}, {})
        # Too few trades to make decisions
        assert len(avoid) == 0 or not any("WEAK" in a for a in avoid)


class TestAnalyzeLivePerformance:
    def test_with_data(self, journal_db: str) -> None:
        result = analyze_live_performance(db_path=journal_db, mode="PAPER")
        assert result["status"] == "ok"
        assert result["summary"]["trades"] == 5
        assert result["summary"]["wins"] == 3
        assert result["summary"]["losses"] == 2
        assert result["summary"]["win_rate"] == pytest.approx(60.0, abs=1.0)
        assert result["summary"]["total_pnl"] == pytest.approx(600.0, abs=1.0)  # 500+200-300-150+350

    def test_with_empty_db(self, empty_db: str) -> None:
        result = analyze_live_performance(db_path=empty_db, mode="PAPER")
        assert result["status"] == "no_data"

    def test_with_nonexistent_db(self) -> None:
        result = analyze_live_performance(db_path="/nonexistent/path.db", mode="PAPER")
        assert result["status"] == "no_data"

    def test_by_tier_present(self, journal_db: str) -> None:
        result = analyze_live_performance(db_path=journal_db, mode="PAPER")
        assert "by_tier" in result
        assert "STRONG" in result["by_tier"]
        assert "MODERATE" in result["by_tier"]
        assert "WEAK" in result["by_tier"]

    def test_by_regime_present(self, journal_db: str) -> None:
        result = analyze_live_performance(db_path=journal_db, mode="PAPER")
        assert "by_regime" in result
        assert "TRENDING" in result["by_regime"]
        assert "NEUTRAL" in result["by_regime"]

    def test_score_outcome_present(self, journal_db: str) -> None:
        result = analyze_live_performance(db_path=journal_db, mode="PAPER")
        assert "score_outcome" in result
        assert "pearson_r" in result["score_outcome"]

    def test_best_worst_setups(self, journal_db: str) -> None:
        result = analyze_live_performance(db_path=journal_db, mode="PAPER")
        assert len(result["best_setups"]) >= 1
        assert len(result["worst_setups"]) >= 1

    def test_exit_reasons(self, journal_db: str) -> None:
        result = analyze_live_performance(db_path=journal_db, mode="PAPER")
        assert "exit_reasons" in result
        assert "take_profit" in result["exit_reasons"]
        assert "stop_loss" in result["exit_reasons"]


class TestPrintLivePerformance:
    def test_prints_with_data(self, journal_db: str, capsys: Any) -> None:
        print_live_performance(db_path=journal_db, mode="PAPER")
        captured = capsys.readouterr()
        assert "LIVE PERFORMANCE REVIEW" in captured.out

    def test_prints_empty_db(self, empty_db: str, capsys: Any) -> None:
        print_live_performance(db_path=empty_db, mode="PAPER")
        captured = capsys.readouterr()
        assert "No closed trades" in captured.out
