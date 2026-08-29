"""
Tests for core/strategy/plugin_framework.py - Plugin Strategy Framework.

Covers:
  - StrategySignal, StrategyState enums
  - MarketData, StrategySignalOutput, FillInfo, RiskUpdate dataclasses
  - BaseStrategy ABC (abstract methods, lifecycle: start/stop/pause/resume)
  - BaseStrategy get_config_hash, validate_config, stats, repr
  - StrategyRegistry (register, unregister, get, get_all, get_active, duplicate)
  - StrategyRegistry generate_signals, on_fill, on_risk_update
  - StrategyRegistry start_all/stop_all/pause_all/resume_all
  - StrategyRegistry get_all_stats
  - StrategyLoader (load from module, failure)
  - get_strategy_registry singleton
"""

from __future__ import annotations

import pytest
from core.strategy.plugin_framework import (
    BaseStrategy,
    FillInfo,
    MarketData,
    RiskUpdate,
    StrategyLoader,
    StrategyRegistry,
    StrategySignal,
    StrategySignalOutput,
    StrategyState,
    get_strategy_registry,
)

# ═══════════════════════════════════════════════════════════════════════
#  Enums
# ═══════════════════════════════════════════════════════════════════════


class TestStrategySignal:
    def test_values(self):
        assert StrategySignal.BUY.value == "BUY"
        assert StrategySignal.SELL.value == "SELL"
        assert StrategySignal.HOLD.value == "HOLD"
        assert StrategySignal.CLOSE.value == "CLOSE"


class TestStrategyState:
    def test_values(self):
        assert StrategyState.INITIALIZED.value == "INITIALIZED"
        assert StrategyState.ACTIVE.value == "ACTIVE"
        assert StrategyState.PAUSED.value == "PAUSED"
        assert StrategyState.STOPPED.value == "STOPPED"


# ═══════════════════════════════════════════════════════════════════════
#  Dataclasses
# ═══════════════════════════════════════════════════════════════════════


class TestMarketData:
    def test_defaults(self):
        md = MarketData(symbol="NIFTY", timestamp="09:15:00", last_price=23500.0, bid=23499.0, ask=23501.0, volume=1000)
        assert md.open_interest == 0
        assert md.delta == 0.0

    def test_additional(self):
        md = MarketData(symbol="NIFTY", timestamp="09:15:00", last_price=23500.0, bid=23499.0, ask=23501.0, volume=1000, iv=15.5)
        assert md.iv == 15.5


class TestStrategySignalOutput:
    def test_defaults(self):
        sso = StrategySignalOutput(signal=StrategySignal.BUY, confidence=0.8, score=85)
        assert sso.quantity == 1
        assert sso.strike is None


class TestFillInfo:
    def test_defaults(self):
        fi = FillInfo(order_id="ORD-001", symbol="NIFTY", direction="BUY", quantity=50, price=23500.0, timestamp="09:15:00")
        assert fi.metadata == {}


class TestRiskUpdate:
    def test_fields(self):
        ru = RiskUpdate(portfolio_pnl=1000.0, daily_pnl=500.0, max_drawdown=0.1, positions_count=2, margin_used=50000.0, available_capital=100000.0)
        assert ru.portfolio_pnl == 1000.0


# ═══════════════════════════════════════════════════════════════════════
#  BaseStrategy (concrete implementation for testing)
# ═══════════════════════════════════════════════════════════════════════


class _TestStrategy(BaseStrategy):
    """Concrete strategy for testing BaseStrategy."""

    @property
    def name(self) -> str:
        return "TestStrategy"

    def on_market_data(self, data: MarketData) -> None:
        self._last_data = data

    def generate_signal(self, data: MarketData) -> StrategySignalOutput | None:
        return StrategySignalOutput(signal=StrategySignal.BUY, confidence=0.9, score=90, reason="Test")

    def on_fill(self, fill: FillInfo) -> None:
        self._last_fill = fill

    def on_risk_update(self, risk: RiskUpdate) -> None:
        self._last_risk = risk


class TestBaseStrategy:
    def test_init(self):
        s = _TestStrategy({"key": "val"})
        assert s.config == {"key": "val"}
        assert s.state == StrategyState.INITIALIZED

    def test_lifecycle(self):
        s = _TestStrategy({})
        assert s.state == StrategyState.INITIALIZED

        s.on_start()
        assert s.state == StrategyState.ACTIVE

        s.on_pause()
        assert s.state == StrategyState.PAUSED

        s.on_resume()
        assert s.state == StrategyState.ACTIVE

        s.on_stop()
        assert s.state == StrategyState.STOPPED

    def test_stats(self):
        s = _TestStrategy({})
        stats = s.stats
        assert stats["signals_generated"] == 0
        assert stats["trades_executed"] == 0
        assert stats["version"] == "1.0.0"

    def test_get_config_hash(self):
        s = _TestStrategy({"param": 1, "other": "val"})
        h1 = s.get_config_hash()
        s2 = _TestStrategy({"param": 1, "other": "val"})
        h2 = s2.get_config_hash()
        assert h1 == h2
        assert len(h1) == 16

    def test_validate_config_returns_true(self):
        s = _TestStrategy({})
        assert s.validate_config() is True

    def test_repr(self):
        s = _TestStrategy({})
        r = repr(s)
        assert "TestStrategy" in r
        assert "INITIALIZED" in r

    def test_version(self):
        s = _TestStrategy({})
        assert s.version == "1.0.0"


# ═══════════════════════════════════════════════════════════════════════
#  StrategyRegistry
# ═══════════════════════════════════════════════════════════════════════


class TestStrategyRegistry:
    def test_register(self):
        registry = StrategyRegistry()
        s = _TestStrategy({})
        assert registry.register(s) is True
        assert registry.get("TestStrategy") is s

    def test_register_duplicate_fails(self):
        registry = StrategyRegistry()
        s1 = _TestStrategy({})
        s2 = _TestStrategy({})
        registry.register(s1)
        assert registry.register(s2) is False  # Same name

    def test_unregister(self):
        registry = StrategyRegistry()
        s = _TestStrategy({})
        registry.register(s)
        assert registry.unregister("TestStrategy") is True
        assert registry.get("TestStrategy") is None

    def test_unregister_nonexistent(self):
        registry = StrategyRegistry()
        assert registry.unregister("NONEXIST") is False

    def test_get_all(self):
        registry = StrategyRegistry()

        class StratA(_TestStrategy):
            @property
            def name(self): return "StratA"

        class StratB(_TestStrategy):
            @property
            def name(self): return "StratB"

        registry.register(StratA({}))
        registry.register(StratB({}))
        assert len(registry.get_all()) == 2

    def test_get_active(self):
        registry = StrategyRegistry()
        s = _TestStrategy({})
        registry.register(s)
        assert len(registry.get_active()) == 0  # INITIALIZED, not ACTIVE

        s.on_start()
        assert len(registry.get_active()) == 1

        s.on_pause()
        assert len(registry.get_active()) == 0

    def test_generate_signals(self):
        registry = StrategyRegistry()
        s = _TestStrategy({})
        registry.register(s)
        s.on_start()

        md = MarketData(symbol="NIFTY", timestamp="09:15:00", last_price=23500.0, bid=23499.0, ask=23501.0, volume=1000)
        signals = registry.generate_signals(md)
        assert len(signals) == 1
        assert signals[0].signal == StrategySignal.BUY
        # Stats should be updated
        assert s._stats["signals_generated"] == 1
        assert s._stats["signals_buy"] == 1

    def test_generate_signals_ignores_inactive(self):
        registry = StrategyRegistry()
        s = _TestStrategy({})
        registry.register(s)  # INITIALIZED, not ACTIVE

        md = MarketData(symbol="NIFTY", timestamp="09:15:00", last_price=23500.0, bid=23499.0, ask=23501.0, volume=1000)
        signals = registry.generate_signals(md)
        assert len(signals) == 0

    def test_generate_signals_hold_is_excluded(self):
        class HoldStrategy(_TestStrategy):
            @property
            def name(self): return "HoldStrat"
            def generate_signal(self, data):
                return StrategySignalOutput(signal=StrategySignal.HOLD, confidence=0.5, score=50)

        registry = StrategyRegistry()
        s = HoldStrategy({})
        registry.register(s)
        s.on_start()

        md = MarketData(symbol="NIFTY", timestamp="09:15:00", last_price=23500.0, bid=23499.0, ask=23501.0, volume=1000)
        signals = registry.generate_signals(md)
        assert len(signals) == 0

    def test_generate_signals_error_is_safe(self):
        class BrokenStrategy(_TestStrategy):
            @property
            def name(self): return "Broken"
            def generate_signal(self, data):
                raise RuntimeError("Boom")

        registry = StrategyRegistry()
        s = BrokenStrategy({})
        registry.register(s)
        s.on_start()

        md = MarketData(symbol="NIFTY", timestamp="09:15:00", last_price=23500.0, bid=23499.0, ask=23501.0, volume=1000)
        signals = registry.generate_signals(md)
        assert len(signals) == 0  # Error caught, returns []

    def test_start_all_stop_all(self):
        registry = StrategyRegistry()
        s = _TestStrategy({})
        registry.register(s)

        registry.start_all()
        assert s.state == StrategyState.ACTIVE

        registry.stop_all()
        assert s.state == StrategyState.STOPPED

    def test_pause_resume_all(self):
        registry = StrategyRegistry()
        s = _TestStrategy({})
        registry.register(s)
        s.on_start()

        registry.pause_all()
        assert s.state == StrategyState.PAUSED

        registry.resume_all()
        assert s.state == StrategyState.ACTIVE

    def test_get_all_stats(self):
        registry = StrategyRegistry()
        s = _TestStrategy({})
        registry.register(s)

        stats = registry.get_all_stats()
        assert "TestStrategy" in stats
        assert stats["TestStrategy"]["version"] == "1.0.0"


# ═══════════════════════════════════════════════════════════════════════
#  StrategyLoader
# ═══════════════════════════════════════════════════════════════════════


class TestStrategyLoader:
    def test_load_invalid_path(self):
        registry = StrategyRegistry()
        loader = StrategyLoader(registry)
        result = loader.load_from_module("/nonexistent/path.py", "TestStrategy", {})
        assert result is None


# ═══════════════════════════════════════════════════════════════════════
#  Singleton
# ═══════════════════════════════════════════════════════════════════════


class TestGetStrategyRegistry:
    @pytest.fixture(autouse=True)
    def _reset(self):
        """Reset singleton before and after."""
        import core.strategy.plugin_framework as pf
        old = pf._strategy_registry
        pf._strategy_registry = None
        yield
        pf._strategy_registry = old

    def test_singleton(self):
        r1 = get_strategy_registry()
        r2 = get_strategy_registry()
        assert r1 is r2
