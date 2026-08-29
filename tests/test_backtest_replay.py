from __future__ import annotations

# ── Inline backward-compat wrapper for deleted core.strategy_engine ──────────
from dataclasses import dataclass
from pathlib import Path

from core import (
    BacktestConfig,
    BacktestEngine,
    CsvReplaySource,
    ProviderChain,
    ReplayConfig,
    ReplayEngine,
)


@dataclass
class _StrategySnapshot:
    """Snapshot returned by StrategyEngine.snapshot()."""
    name: str = ""
    score: float = 0.0
    threshold: float = 60.0
    direction: str = ""
    regime: str = "NEUTRAL"
    strength: str = "NONE"


class StrategyEngine:
    """Inline wrapper for backward-compat in tests."""
    def __init__(self, generate_signal_fn=None):
        self._generate_signal_fn = generate_signal_fn or (lambda name, frames, vix=0.0: None)
    def generate_signal(self, name, frames, vix=0.0):
        return self._generate_signal_fn(name, frames, vix)
    def snapshot(self, name, sig=None):
        if sig is None:
            sig = {}
        return _StrategySnapshot(
            name=name,
            score=float(sig.get('score', 0)) if isinstance(sig, dict) else 0.0,
            threshold=float(sig.get('threshold', 60)) if isinstance(sig, dict) else 60.0,
            direction=str(sig.get('direction', '')),
            regime=str(sig.get('regime', 'NEUTRAL')),
            strength=str(sig.get('strength', 'NONE')),
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
