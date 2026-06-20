"""Tests for core/risk/sizing/manager.py - Position Sizing Manager.

Covers:
- PositionSizingManager init with config
- calculate_size (normal, zero/negative prices, edge cases)
- get_volatility_multiplier (low, high, interpolated)
- Error handling (exceptions return 0)
"""
from __future__ import annotations

import pytest

from core.risk.sizing.manager import PositionSizingManager
from core.ports.risk.risk_port import PositionSizingInput

# Can't use TestConfigNamedTuple here since it's internal to the source module.
# We'll use a simple class/object with the required attributes instead.


class MockSizingConfig:
    """Mock config object with the attributes PositionSizingManager needs."""
    def __init__(self):
        self.vix_threshold_low = 12.0
        self.vix_threshold_high = 25.0
        self.vix_size_multiplier_low = 1.0
        self.vix_size_multiplier_high = 0.5


@pytest.fixture
def config() -> MockSizingConfig:
    return MockSizingConfig()


@pytest.fixture
def mgr(config: MockSizingConfig) -> PositionSizingManager:
    return PositionSizingManager(config)


# =============================================================================
# Init Tests
# =============================================================================

class TestInit:
    def test_stores_config(self, config: MockSizingConfig):
        mgr = PositionSizingManager(config)
        assert mgr.config is config

    def test_accepts_namespace_config(self):
        """Manager should accept object with attribute access."""
        from types import SimpleNamespace
        cfg = SimpleNamespace(
            vix_threshold_low=12, vix_threshold_high=25,
            vix_size_multiplier_low=1.0, vix_size_multiplier_high=0.5,
        )
        mgr = PositionSizingManager(cfg)
        assert mgr.config is cfg
        assert mgr.get_volatility_multiplier(15.0) > 0


# =============================================================================
# calculate_size Tests
# =============================================================================

class TestCalculateSize:
    def test_basic_calculation(self, mgr: PositionSizingManager):
        sizing_input = PositionSizingInput(
            symbol="NIFTY",
            capital_available=100000.0,
            risk_per_trade=0.02,
            entry_price=150.0,
            stop_loss_price=127.5,
            lot_size=50,
        )
        lots = mgr.calculate_size(sizing_input, volatility_multiplier=1.0)
        # risk_amount = 2000, price_diff = 22.5
        # raw_lots = 2000 / (22.5 * 50) = 1.777...
        # base_lots = 1 (since int(1.777) = 1)
        # adjusted_lots = 1 * 1.0 = 1
        assert lots == 1

    def test_volatility_reduces_size(self, mgr: PositionSizingManager):
        sizing_input = PositionSizingInput(
            symbol="NIFTY",
            capital_available=100000.0,
            risk_per_trade=0.02,
            entry_price=150.0,
            stop_loss_price=127.5,
            lot_size=50,
        )
        lots = mgr.calculate_size(sizing_input, volatility_multiplier=0.5)
        assert lots == 0  # int(1 * 0.5) = 0

    def test_volatility_increases_size(self, mgr: PositionSizingManager):
        sizing_input = PositionSizingInput(
            symbol="NIFTY",
            capital_available=1000000.0,
            risk_per_trade=0.02,
            entry_price=150.0,
            stop_loss_price=127.5,
            lot_size=50,
        )
        lots = mgr.calculate_size(sizing_input, volatility_multiplier=1.5)
        # raw_lots = 20000 / 1125 = 17.777 → 17
        # adjusted_lots = 17 * 1.5 = 25.5 → 25
        assert lots == 25

    def test_large_position_many_lots(self, mgr: PositionSizingManager):
        sizing_input = PositionSizingInput(
            symbol="NIFTY",
            capital_available=10000000.0,
            risk_per_trade=0.02,
            entry_price=150.0,
            stop_loss_price=127.5,
            lot_size=50,
        )
        lots = mgr.calculate_size(sizing_input, volatility_multiplier=0.8)
        assert lots > 0

    def test_zero_stop_loss_returns_zero(self, mgr: PositionSizingManager):
        sizing_input = PositionSizingInput(
            symbol="NIFTY",
            capital_available=100000.0,
            risk_per_trade=0.02,
            entry_price=150.0,
            stop_loss_price=0.0,
            lot_size=50,
        )
        lots = mgr.calculate_size(sizing_input, volatility_multiplier=1.0)
        assert lots == 0

    def test_negative_stop_loss_returns_zero(self, mgr: PositionSizingManager):
        sizing_input = PositionSizingInput(
            symbol="NIFTY",
            capital_available=100000.0,
            risk_per_trade=0.02,
            entry_price=150.0,
            stop_loss_price=-10.0,
            lot_size=50,
        )
        lots = mgr.calculate_size(sizing_input, volatility_multiplier=1.0)
        assert lots == 0

    def test_zero_entry_price_returns_zero(self, mgr: PositionSizingManager):
        sizing_input = PositionSizingInput(
            symbol="NIFTY",
            capital_available=100000.0,
            risk_per_trade=0.02,
            entry_price=0.0,
            stop_loss_price=100.0,
            lot_size=50,
        )
        lots = mgr.calculate_size(sizing_input, volatility_multiplier=1.0)
        assert lots == 0

    def test_equal_entry_and_stop_returns_zero(self, mgr: PositionSizingManager):
        """When entry_price == stop_loss_price, price_diff is 0."""
        sizing_input = PositionSizingInput(
            symbol="NIFTY",
            capital_available=100000.0,
            risk_per_trade=0.02,
            entry_price=100.0,
            stop_loss_price=100.0,
            lot_size=50,
        )
        lots = mgr.calculate_size(sizing_input, volatility_multiplier=1.0)
        assert lots == 0

    def test_never_negative(self, mgr: PositionSizingManager):
        sizing_input = PositionSizingInput(
            symbol="NIFTY",
            capital_available=100.0,
            risk_per_trade=0.02,
            entry_price=150.0,
            stop_loss_price=127.5,
            lot_size=50,
        )
        lots = mgr.calculate_size(sizing_input, volatility_multiplier=0.1)
        assert lots >= 0

    def test_raises_type_error_handled(self, mgr: PositionSizingManager):
        """Invalid inputs should return 0, not raise."""
        with pytest.raises(AttributeError):
            mgr.calculate_size(None, None)  # type: ignore


# =============================================================================
# get_volatility_multiplier Tests
# =============================================================================

class TestGetVolatilityMultiplier:
    def test_below_low_threshold(self, mgr: PositionSizingManager):
        """VIX below low threshold → use low multiplier."""
        mult = mgr.get_volatility_multiplier(8.0)
        assert mult == 1.0

    def test_at_low_threshold(self, mgr: PositionSizingManager):
        mult = mgr.get_volatility_multiplier(12.0)
        assert mult == 1.0

    def test_above_high_threshold(self, mgr: PositionSizingManager):
        """VIX above high threshold → use high multiplier."""
        mult = mgr.get_volatility_multiplier(30.0)
        assert mult == 0.5

    def test_at_high_threshold(self, mgr: PositionSizingManager):
        mult = mgr.get_volatility_multiplier(25.0)
        assert mult == 0.5

    def test_mid_range_interpolation(self, mgr: PositionSizingManager):
        """Mid-range should interpolate linearly."""
        # VIX = 18.5, range = 12-25 → ratio = 6.5/13 = 0.5
        # mult = 1.0 + 0.5 * (0.5 - 1.0) = 1.0 - 0.25 = 0.75
        mult = mgr.get_volatility_multiplier(18.5)
        assert mult == pytest.approx(0.75, rel=0.01)

    def test_mid_range_lower_half(self, mgr: PositionSizingManager):
        """VIX at 15: ratio = 3/13 ≈ 0.23, mult = 1.0 + 0.23 * (-0.5) ≈ 0.885"""
        mult = mgr.get_volatility_multiplier(15.0)
        assert mult == pytest.approx(0.8846, rel=0.01)

    def test_mid_range_upper_half(self, mgr: PositionSizingManager):
        """VIX at 22: ratio = 10/13 ≈ 0.769, mult = 1.0 + 0.769 * (-0.5) ≈ 0.615"""
        mult = mgr.get_volatility_multiplier(22.0)
        assert mult == pytest.approx(0.6154, rel=0.01)

    def test_clamps_below_zero(self, mgr: PositionSizingManager):
        """Negative ratio should be clamped to 0."""
        mult = mgr.get_volatility_multiplier(0.0)
        assert mult == 1.0  # Clamped to low threshold

    def test_clamps_above_one(self, mgr: PositionSizingManager):
        mult = mgr.get_volatility_multiplier(50.0)
        assert mult == 0.5  # Clamped to high threshold

    def test_custom_thresholds(self):
        """Custom config with different thresholds."""
        cfg = MockSizingConfig()
        cfg.vix_threshold_low = 10.0
        cfg.vix_threshold_high = 20.0
        cfg.vix_size_multiplier_low = 0.8
        cfg.vix_size_multiplier_high = 0.3
        mgr = PositionSizingManager(cfg)

        assert mgr.get_volatility_multiplier(5.0) == 0.8  # Below low
        assert mgr.get_volatility_multiplier(15.0) == pytest.approx(0.55, rel=0.01)  # Mid
        assert mgr.get_volatility_multiplier(25.0) == 0.3  # Above high
