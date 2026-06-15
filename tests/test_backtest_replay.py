from __future__ import annotations

from pathlib import Path

from core import (
    BacktestConfig,
    BacktestEngine,
    CsvReplaySource,
    ProviderChain,
    ReplayConfig,
    ReplayEngine,
    StrategyEngine,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def _fixture_strategy(name: str, frames: dict, vix: float = 0.0):
    frame_1m = frames.get("1m")
    if frame_1m is None or len(frame_1m) < 20:
        return None
    close_now = float(frame_1m["Close"].iloc[-1])
    close_prev = float(frame_1m["Close"].iloc[-2])
    if close_now <= close_prev:
        return None
    return {
        "name": name,
        "score": 84,
        "threshold": 70,
        "direction": "CALL",
        "strength": "STRONG",
        "regime": "TRENDING",
        "price": close_now,
        "stop_loss": round(close_now - 0.7, 2),
        "tp2": round(close_now + 0.9, 2),
        "qty": 1,
    }


def test_provider_chain_falls_through_to_working_provider():
    chain = ProviderChain(
        {
            "nse": lambda: (_ for _ in ()).throw(ConnectionError("nse down")),
            "yfinance": lambda: {"source": "yfinance"},
        }
    )
    result = chain.fetch(["nse", "yfinance"])
    assert result.ok is True
    assert result.provider == "yfinance"
    assert result.data == {"source": "yfinance"}


def test_replay_engine_emits_signals_from_csv_fixture():
    strategy = StrategyEngine(generate_signal_fn=_fixture_strategy)
    source = CsvReplaySource(FIXTURES / "replay_minute_bars.csv", ReplayConfig(warmup_bars=10))
    base_df = source.load()
    replay = ReplayEngine(strategy, ReplayConfig(warmup_bars=10))
    signals = replay.run("NIFTY", base_df)
    assert signals
    assert signals[0].direction == "CALL"
    assert signals[0].score >= signals[0].threshold


def test_backtest_engine_produces_trade_report_from_csv_fixture():
    strategy = StrategyEngine(generate_signal_fn=_fixture_strategy)
    source = CsvReplaySource(FIXTURES / "replay_minute_bars.csv", ReplayConfig(warmup_bars=10))
    base_df = source.load()
    backtest = BacktestEngine(
        strategy,
        replay_config=ReplayConfig(warmup_bars=10),
        backtest_config=BacktestConfig(
            initial_capital=5000,
            trade_size=1,
            fallback_stop_pct=0.01,
            fallback_target_pct=0.015,
            max_bars_in_trade=8,
            commission_per_trade=0.0,
            slippage_pct=0.0,
        ),
    )
    report = backtest.run("NIFTY", base_df)
    assert report.total_trades >= 1
    assert report.ending_capital >= report.initial_capital
    assert report.net_pnl >= 0
