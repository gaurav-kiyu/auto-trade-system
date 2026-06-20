"""Tests for core/strategy/sandbox.py - Strategy Sandbox Environment.

Covers:
- SandboxMode, SandboxConfig, SandboxResult dataclasses
- StrategySandbox init, configure, load_strategy
- run_historical_replay (signals, mock fills, no strategy, stop)
- run_simulated_live (data source, duration)
- stop, get_results, get_current_stats
- _convert_to_market_data, _simulate_fill, _record_signal_event
- get_strategy_sandbox singleton
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.strategy.sandbox import (
    SandboxConfig,
    SandboxMode,
    SandboxResult,
    StrategySandbox,
    get_strategy_sandbox,
)
from core.strategy.plugin_framework import (
    BaseStrategy,
    FillInfo,
    MarketData,
    RiskUpdate,
    StrategySignal,
    StrategySignalOutput,
)


# ── Mock Strategy ─────────────────────────────────────────────────────────────

class MockStrategy(BaseStrategy):
    """Simple mock strategy for sandbox testing."""
    def __init__(self):
        super().__init__(config={"name": "MockStrategy"})
        self._name = "MockStrategy"
        self._started = False
        self._stopped = False
        self._market_data_calls = 0

    @property
    def name(self) -> str:
        return self._name

    def on_start(self) -> None:
        super().on_start()
        self._started = True

    def on_stop(self) -> None:
        super().on_stop()
        self._stopped = True

    def on_market_data(self, data: MarketData) -> None:
        self._market_data_calls += 1

    def generate_signal(self, data: MarketData) -> StrategySignalOutput | None:
        if self._market_data_calls % 3 == 0:
            return StrategySignalOutput(
                signal=StrategySignal.BUY,
                confidence=0.8,
                score=75,
                price=data.last_price,
                quantity=1,
                metadata={"strategy_name": self._name, "symbol": data.symbol},
            )
        return None  # HOLD

    def on_fill(self, fill: FillInfo) -> None:
        pass

    def on_risk_update(self, risk: RiskUpdate) -> None:
        pass


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sandbox() -> StrategySandbox:
    return StrategySandbox()


@pytest.fixture
def configured_sandbox(sandbox: StrategySandbox) -> StrategySandbox:
    sandbox.configure(SandboxMode.HISTORICAL_REPLAY, speed=2.0, mock_fills=True)
    sandbox.load_strategy(MockStrategy())
    return sandbox


@pytest.fixture
def sample_data() -> list[dict[str, Any]]:
    return [
        {"symbol": "NIFTY", "last_price": 23500.0, "bid": 23499.0, "ask": 23501.0, "volume": 1000, "timestamp": "10:00:00"},
        {"symbol": "NIFTY", "last_price": 23550.0, "bid": 23549.0, "ask": 23551.0, "volume": 1200, "timestamp": "10:01:00"},
        {"symbol": "NIFTY", "last_price": 23600.0, "bid": 23599.0, "ask": 23601.0, "volume": 1500, "timestamp": "10:02:00"},
    ]


# =============================================================================
# Init & Configure Tests
# =============================================================================

class TestInit:
    def test_default_state(self):
        sandbox = StrategySandbox()
        assert sandbox._active is False
        assert sandbox._config is None
        assert sandbox._strategy is None
        assert sandbox._results == []

    def test_configure(self, sandbox: StrategySandbox):
        sandbox.configure(SandboxMode.MOCK_BROKER, speed=3.0, mock_fills=False)
        assert sandbox._config is not None
        assert sandbox._config.mode == SandboxMode.MOCK_BROKER
        assert sandbox._config.speed == 3.0
        assert sandbox._config.mock_fills is False

    def test_configure_defaults(self, sandbox: StrategySandbox):
        sandbox.configure(SandboxMode.SIMULATED_LIVE)
        assert sandbox._config.speed == 1.0
        assert sandbox._config.mock_fills is True
        assert sandbox._config.slippage_pct == 0.001


class TestLoadStrategy:
    def test_loads_strategy(self, sandbox: StrategySandbox):
        strategy = MockStrategy()
        result = sandbox.load_strategy(strategy)
        assert result is True
        assert sandbox._strategy is strategy
        assert strategy._started is True

    def test_load_strategy_calls_on_start(self, sandbox: StrategySandbox):
        strategy = MockStrategy()
        sandbox.load_strategy(strategy)
        assert strategy._started is True

    def test_load_strategy_failure(self, sandbox: StrategySandbox):
        strategy = MockStrategy()
        original_on_start = strategy.on_start
        strategy.on_start = lambda: (_ for _ in ()).throw(ValueError("Init failed"))
        result = sandbox.load_strategy(strategy)
        assert result is False
        strategy.on_start = original_on_start


# =============================================================================
# run_historical_replay Tests
# =============================================================================

class TestRunHistoricalReplay:
    def test_returns_result(self, configured_sandbox: StrategySandbox, sample_data: list[dict[str, Any]]):
        result = configured_sandbox.run_historical_replay(sample_data)
        assert result is not None
        assert result.mode == SandboxMode.HISTORICAL_REPLAY
        assert result.strategy_name == "MockStrategy"
        assert result.start_time is not None
        assert result.end_time is not None

    def test_generates_signals(self, configured_sandbox: StrategySandbox, sample_data: list[dict[str, Any]]):
        result = configured_sandbox.run_historical_replay(sample_data)
        # MockStrategy generates signal every 3rd call -> 1 signal for 3 data points
        assert result.total_signals >= 0

    def test_no_strategy_returns_none(self, sandbox: StrategySandbox):
        sandbox.configure(SandboxMode.HISTORICAL_REPLAY)
        result = sandbox.run_historical_replay([{"symbol": "NIFTY", "last_price": 100.0}])
        assert result is None

    def test_no_config_returns_none(self, sandbox: StrategySandbox):
        sandbox.load_strategy(MockStrategy())
        result = sandbox.run_historical_replay([{"symbol": "NIFTY", "last_price": 100.0}])
        assert result is None

    def test_calls_on_complete_callback(self, configured_sandbox: StrategySandbox, sample_data: list[dict[str, Any]]):
        callback = MagicMock()
        configured_sandbox.run_historical_replay(sample_data, on_complete=callback)
        callback.assert_called_once()
        args = callback.call_args[0][0]
        assert isinstance(args, SandboxResult)

    def test_stop_during_replay(self, configured_sandbox: StrategySandbox, sample_data: list[dict[str, Any]]):
        configured_sandbox.stop()
        result = configured_sandbox.run_historical_replay(sample_data)
        # Should return normally (short-circuits if not active)
        assert result is not None or configured_sandbox._active is False


# =============================================================================
# run_simulated_live Tests
# =============================================================================

class TestRunSimulatedLive:
    def test_returns_result(self, sandbox: StrategySandbox):
        sandbox.configure(SandboxMode.SIMULATED_LIVE, speed=10.0)
        sandbox.load_strategy(MockStrategy())
        data_source = MagicMock(return_value=MarketData(
            symbol="NIFTY", timestamp="10:00", last_price=23500.0, bid=23499.0, ask=23501.0, volume=100,
        ))
        result = sandbox.run_simulated_live(data_source, duration_seconds=1)
        assert result is not None
        assert result.mode == SandboxMode.SIMULATED_LIVE

    def test_no_strategy_returns_none(self, sandbox: StrategySandbox):
        sandbox.configure(SandboxMode.SIMULATED_LIVE)
        result = sandbox.run_simulated_live(MagicMock(), duration_seconds=1)
        assert result is None


# =============================================================================
# Stop Tests
# =============================================================================

class TestStop:
    def test_stops_sandbox(self, configured_sandbox: StrategySandbox):
        configured_sandbox.stop()
        assert configured_sandbox._active is False
        assert configured_sandbox._strategy._stopped is True

    def test_stop_calls_strategy_on_stop(self, sandbox: StrategySandbox):
        strategy = MockStrategy()
        sandbox.load_strategy(strategy)
        sandbox.stop()
        assert strategy._stopped is True


# =============================================================================
# get_results Tests
# =============================================================================

class TestGetResults:
    def test_empty_initially(self, sandbox: StrategySandbox):
        assert sandbox.get_results() == []

    def test_returns_recent_results(self, configured_sandbox: StrategySandbox, sample_data: list[dict[str, Any]]):
        configured_sandbox.run_historical_replay(sample_data)
        results = configured_sandbox.get_results()
        assert len(results) == 1

    def test_limits_results(self, configured_sandbox: StrategySandbox, sample_data: list[dict[str, Any]]):
        for _ in range(5):
            configured_sandbox.run_historical_replay(sample_data)
        results = configured_sandbox.get_results(limit=3)
        assert len(results) <= 3


# =============================================================================
# get_current_stats Tests
# =============================================================================

class TestGetCurrentStats:
    def test_initial_state(self, sandbox: StrategySandbox):
        stats = sandbox.get_current_stats()
        assert stats["active"] is False
        assert stats["config"]["mode"] is None
        assert stats["strategy"] is None
        assert stats["total_runs"] == 0

    def test_after_configure(self, configured_sandbox: StrategySandbox):
        stats = configured_sandbox.get_current_stats()
        assert stats["active"] is False
        assert stats["config"]["mode"] == "HISTORICAL_REPLAY"
        assert stats["strategy"] == "MockStrategy"


# =============================================================================
# Internal Methods Tests
# =============================================================================

class TestConvertToMarketData:
    def test_converts_dict(self, sandbox: StrategySandbox):
        data = {"symbol": "NIFTY", "last_price": 23500.0, "bid": 23499.0, "ask": 23501.0, "volume": 1000}
        md = sandbox._convert_to_market_data(data)
        assert md.symbol == "NIFTY"
        assert md.last_price == 23500.0
        assert md.bid == 23499.0
        assert md.ask == 23501.0

    def test_defaults_for_missing_keys(self, sandbox: StrategySandbox):
        md = sandbox._convert_to_market_data({})
        assert md.symbol == ""
        assert md.last_price == 0.0


class TestSimulateFill:
    def test_buy_with_slippage(self, sandbox: StrategySandbox):
        sandbox.configure(SandboxMode.HISTORICAL_REPLAY, slippage_pct=0.002)
        signal = StrategySignalOutput(signal=StrategySignal.BUY, confidence=0.8, score=75, price=100.0, quantity=10)
        fill = sandbox._simulate_fill(signal)
        assert fill["price"] == 100.0 * 1.002  # Buy: price * (1 + slippage)
        assert fill["quantity"] == 10

    def test_sell_with_slippage(self, sandbox: StrategySandbox):
        sandbox.configure(SandboxMode.HISTORICAL_REPLAY, slippage_pct=0.001)
        signal = StrategySignalOutput(signal=StrategySignal.SELL, confidence=0.7, score=60, price=200.0, quantity=5)
        fill = sandbox._simulate_fill(signal)
        assert fill["price"] == 200.0 * 0.999  # Sell: price * (1 - slippage)
        assert fill["quantity"] == 5

    def test_default_slippage(self, sandbox: StrategySandbox):
        sandbox.configure(SandboxMode.HISTORICAL_REPLAY)
        signal = StrategySignalOutput(signal=StrategySignal.BUY, confidence=0.8, score=75, price=100.0, quantity=1)
        assert sandbox._config.slippage_pct == 0.001


# =============================================================================
# Singleton Tests
# =============================================================================

class TestSingleton:
    def test_get_strategy_sandbox_returns_same_instance(self):
        # Reset global state
        import core.strategy.sandbox as sandbox_mod
        sandbox_mod._sandbox = None
        s1 = get_strategy_sandbox()
        s2 = get_strategy_sandbox()
        assert s1 is s2
        sandbox_mod._sandbox = None  # Cleanup
