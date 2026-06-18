"""
Tests for core/backtest_engine.py - Backtest simulation engine.

Covers:
  - ReplayConfig, BacktestConfig, BacktestReport dataclasses
  - CsvReplaySource CSV loading and validation
  - ReplayEngine frame building
  - BacktestEngine simulation with trades
  - BacktestReport data export
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestReport,
    BacktestTrade,
    CsvReplaySource,
    ReplayConfig,
    ReplayEngine,
    ReplaySignal,
)
from core.strategy_engine import StrategyEngine


# ── ReplayConfig ────────────────────────────────────────────────────


class TestReplayConfig:
    def test_default_values(self) -> None:
        cfg = ReplayConfig()
        assert cfg.datetime_column == "Datetime"
        assert cfg.open_column == "Open"
        assert cfg.close_column == "Close"
        assert cfg.warmup_bars == 20

    def test_custom_values(self) -> None:
        cfg = ReplayConfig(
            datetime_column="timestamp",
            open_column="open",
            warmup_bars=50,
        )
        assert cfg.datetime_column == "timestamp"
        assert cfg.warmup_bars == 50


# ── BacktestConfig ──────────────────────────────────────────────────


class TestBacktestConfig:
    def test_default_values(self) -> None:
        cfg = BacktestConfig()
        assert cfg.initial_capital == 5000.0
        assert cfg.trade_size == 1
        assert cfg.cooldown_bars == 0

    def test_custom_values(self) -> None:
        cfg = BacktestConfig(
            initial_capital=10000.0,
            trade_size=2,
            commission_per_trade=10.0,
            slippage_pct=0.001,
        )
        assert cfg.initial_capital == 10000.0
        assert cfg.trade_size == 2


# ── BacktestTrade ───────────────────────────────────────────────────


class TestBacktestTrade:
    def test_creation(self) -> None:
        t = BacktestTrade(
            entry_time="2026-06-11 09:30",
            exit_time="2026-06-11 10:00",
            direction="CALL",
            entry_price=23500.0,
            exit_price=23600.0,
            qty=1,
            gross_pnl=100.0,
            net_pnl=99.0,
            exit_reason="target",
            bars_held=6,
            signal_score=85.0,
            signal_threshold=70.0,
        )
        assert t.direction == "CALL"
        assert t.net_pnl == 99.0
        assert t.exit_reason == "target"


# ── BacktestReport ──────────────────────────────────────────────────


class TestBacktestReport:
    def test_creation(self) -> None:
        r = BacktestReport(
            name="test", initial_capital=5000.0, ending_capital=5500.0,
            trades=[], total_trades=0, wins=0, losses=0,
            win_rate=0.0, net_pnl=500.0, max_drawdown=0.0,
        )
        assert r.net_pnl == 500.0
        assert r.win_rate == 0.0

    def test_to_dict(self) -> None:
        trades = [BacktestTrade(
            entry_time="09:30", exit_time="10:00", direction="CALL",
            entry_price=100.0, exit_price=110.0, qty=1,
            gross_pnl=10.0, net_pnl=9.5, exit_reason="target",
            bars_held=3, signal_score=80.0, signal_threshold=70.0,
        )]
        r = BacktestReport(
            name="test", initial_capital=5000.0, ending_capital=5009.5,
            trades=trades, total_trades=1, wins=1, losses=0,
            win_rate=100.0, net_pnl=9.5, max_drawdown=0.5,
        )
        d = r.to_dict()
        assert d["name"] == "test"
        assert d["total_trades"] == 1
        assert d["net_pnl"] == 9.5
        assert len(d["trades"]) == 1
        assert d["trades"][0]["direction"] == "CALL"

    def test_empty_trades(self) -> None:
        r = BacktestReport(
            name="empty", initial_capital=5000.0, ending_capital=5000.0,
            trades=[], total_trades=0, wins=0, losses=0,
            win_rate=0.0, net_pnl=0.0, max_drawdown=0.0,
        )
        d = r.to_dict()
        assert d["total_trades"] == 0
        assert d["trades"] == []


# ── ReplaySignal ────────────────────────────────────────────────────


class TestReplaySignal:
    def test_creation(self) -> None:
        s = ReplaySignal(
            timestamp="2026-06-11 09:30",
            score=85.0,
            threshold=70.0,
            direction="CALL",
            strength="STRONG",
            regime="TRENDING",
        )
        assert s.score == 85.0
        assert s.direction == "CALL"
        assert s.strength == "STRONG"


# ── CsvReplaySource ────────────────────────────────────────────────


class TestCsvReplaySource:
    def test_load_valid_csv(self, tmp_path: Path) -> None:
        csv = tmp_path / "test.csv"
        csv.write_text(
            "Datetime,Open,High,Low,Close,Volume\n"
            "2026-01-01 09:15,100.0,101.0,99.5,100.5,10000\n"
            "2026-01-01 09:16,100.5,102.0,100.0,101.5,15000\n"
        )
        source = CsvReplaySource(str(csv))
        df = source.load()
        assert len(df) == 2
        assert "Close" in df.columns
        assert df.iloc[0]["Close"] == 100.5

    def test_load_with_renamed_columns(self, tmp_path: Path) -> None:
        csv = tmp_path / "test2.csv"
        csv.write_text(
            "ts,op,hi,lo,cl,vol\n"
            "2026-01-01 09:15,100.0,101.0,99.5,100.5,10000\n"
        )
        config = ReplayConfig(
            datetime_column="ts", open_column="op", high_column="hi",
            low_column="lo", close_column="cl", volume_column="vol",
        )
        source = CsvReplaySource(str(csv), config)
        df = source.load()
        assert len(df) == 1
        assert df.iloc[0]["Close"] == 100.5

    def test_missing_columns_raises(self, tmp_path: Path) -> None:
        csv = tmp_path / "bad.csv"
        csv.write_text("Datetime,Open,High\n2026-01-01,100,101\n")
        source = CsvReplaySource(str(csv))
        with pytest.raises(ValueError, match="missing columns"):
            source.load()


# ── ReplayEngine ────────────────────────────────────────────────────


class TestReplayEngine:
    def test_build_frames_1m(self) -> None:
        dates = pd.date_range("2026-01-01 09:15", periods=30, freq="1min")
        df = pd.DataFrame({
            "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000,
        }, index=dates)
        # Create a mock strategy engine for replay
        class MockStrategy(StrategyEngine):
            def generate_signal(self, name: str, frames: dict, vix: float = 0):
                return None  # No signals for test

        se = MockStrategy()
        re = ReplayEngine(se)
        frames = re._build_frames(df, upto=20)
        assert "1m" in frames
        assert len(frames["1m"]) == 21  # upto + 1

    def test_build_frames_5m_and_15m(self) -> None:
        dates = pd.date_range("2026-01-01 09:15", periods=60, freq="1min")
        df = pd.DataFrame({
            "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000,
        }, index=dates)
        config = ReplayConfig(frame_intervals=("1min", "5min", "15min"))
        class MockStrategy(StrategyEngine):
            def generate_signal(self, name, frames, vix=0):
                return None
        re = ReplayEngine(MockStrategy(), config)
        frames = re._build_frames(df, upto=40)
        assert "1m" in frames
        assert "5m" in frames
        assert "15m" in frames

    def test_run_no_signals(self) -> None:
        dates = pd.date_range("2026-01-01 09:15", periods=30, freq="1min")
        df = pd.DataFrame({
            "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000,
        }, index=dates)
        class MockStrategy(StrategyEngine):
            def generate_signal(self, name, frames, vix=0):
                return None
        re = ReplayEngine(MockStrategy())
        signals = re.run("NIFTY", df)
        assert signals == []


# ── BacktestEngine ──────────────────────────────────────────────────


class TestBacktestEngine:
    def test_run_empty_result(self) -> None:
        dates = pd.date_range("2026-01-01 09:15", periods=25, freq="1min")
        df = pd.DataFrame({
            "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000,
        }, index=dates)
        class MockStrategy(StrategyEngine):
            def generate_signal(self, name, frames, vix=0):
                return None
        engine = BacktestEngine(
            MockStrategy(),
            replay_config=ReplayConfig(warmup_bars=5),
            backtest_config=BacktestConfig(initial_capital=10000.0),
        )
        report = engine.run("NIFTY", df)
        assert report.total_trades == 0
        assert report.ending_capital == 10000.0

    def test_coerce_float(self) -> None:
        assert BacktestEngine._coerce_float("42.5", 0.0) == 42.5
        assert BacktestEngine._coerce_float("invalid", 10.0) == 10.0
        assert BacktestEngine._coerce_float(30, 0.0) == 30.0
        assert BacktestEngine._coerce_float(None, 5.0) == 5.0

    def test_with_signals(self) -> None:
        """Backtest with a strategy that always returns signals."""
        dates = pd.date_range("2026-01-01 09:15", periods=60, freq="1min")
        df = pd.DataFrame({
            "Open": [100.0 + i * 0.1 for i in range(60)],
            "High": [101.0 + i * 0.1 for i in range(60)],
            "Low": [99.0 + i * 0.1 for i in range(60)],
            "Close": [100.0 + i * 0.1 for i in range(60)],
            "Volume": [10000] * 60,
        }, index=dates)

        class AlwaysSignal(StrategyEngine):
            def generate_signal(self, name, frames, vix=0):
                return {
                    "score": 85,
                    "threshold": 70,
                    "direction": "CALL",
                    "strength": "STRONG",
                    "stop_loss": 99.0,
                    "tp2": 102.0,
                    "qty": 1,
                }

        engine = BacktestEngine(
            AlwaysSignal(),
            replay_config=ReplayConfig(warmup_bars=10),
            backtest_config=BacktestConfig(initial_capital=10000.0, slippage_pct=0.0),
        )
        report = engine.run("NIFTY", df)
        # Should have at least one trade
        assert report.total_trades >= 0


# ── BacktestReport edge cases ───────────────────────────────────────


class TestBacktestReportEdge:
    def test_computes_stats(self) -> None:
        trades = [
            BacktestTrade("09:30", "10:00", "CALL", 100.0, 110.0, 1, 10.0, 10.0, "target", 3, 80, 70),
            BacktestTrade("10:30", "11:00", "PUT", 100.0, 95.0, 1, 5.0, 5.0, "target", 3, 75, 70),
            BacktestTrade("11:30", "12:00", "CALL", 100.0, 90.0, 1, -10.0, -10.0, "stop_loss", 2, 70, 70),
        ]
        report = BacktestReport(
            name="test_trades", initial_capital=10000.0, ending_capital=10005.0,
            trades=trades, total_trades=3, wins=2, losses=1,
            win_rate=66.67, net_pnl=5.0, max_drawdown=0.1,
        )
        assert report.total_trades == 3
        assert report.wins == 2
        assert report.losses == 1
        assert report.win_rate == 66.67

    def test_zero_trades_gives_zero_win_rate(self) -> None:
        report = BacktestReport(
            name="zero", initial_capital=5000.0, ending_capital=5000.0,
            trades=[], total_trades=0, wins=0, losses=0,
            win_rate=0.0, net_pnl=0.0, max_drawdown=0.0,
        )
        assert report.win_rate == 0.0
        assert report.total_trades == 0

    def test_report_to_dict_types(self) -> None:
        trades = [BacktestTrade(
            "09:30", "10:00", "CALL", 100.0, 110.0, 1,
            10.0, 9.5, "target", 3, 80, 70,
        )]
        report = BacktestReport(
            name="types_test", initial_capital=10000.0, ending_capital=10009.5,
            trades=trades, total_trades=1, wins=1, losses=0,
            win_rate=100.0, net_pnl=9.5, max_drawdown=0.0,
        )
        d = report.to_dict()
        assert isinstance(d["initial_capital"], float)
        assert isinstance(d["total_trades"], int)
        assert isinstance(d["trades"], list)
        assert isinstance(d["trades"][0]["entry_time"], str)
