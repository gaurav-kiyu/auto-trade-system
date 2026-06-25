"""Tests for core.equity_protection - equity curve protection."""

from __future__ import annotations

import pytest

from core.equity_protection import EquityProtection, ProtectionState


class TestProtectionState:
    """Tests for ProtectionState dataclass."""

    def test_defaults(self) -> None:
        state = ProtectionState(multiplier=1.0, status="NORMAL", current_drawdown=0.0)
        assert state.multiplier == 1.0
        assert state.status == "NORMAL"


class TestEquityProtection:
    """Tests for EquityProtection - scaling risk during drawdowns."""

    def setup_method(self) -> None:
        self.protector = EquityProtection({})

    def test_no_drawdown_returns_full_multiplier(self) -> None:
        state = self.protector.calculate_multiplier(100_000, 100_000)
        assert state.multiplier == 1.0
        assert state.status == "NORMAL"
        assert state.current_drawdown == 0.0

    def test_small_drawdown_below_2pct(self) -> None:
        state = self.protector.calculate_multiplier(99_000, 100_000)
        assert state.multiplier == 1.0  # 1% drawdown, below 2% threshold
        assert state.status == "NORMAL"

    def test_medium_drawdown_2_to_5_pct(self) -> None:
        state = self.protector.calculate_multiplier(96_000, 100_000)
        assert state.multiplier == 0.7  # 4% drawdown
        assert state.status == "REDUCED"

    def test_large_drawdown_5_to_10_pct(self) -> None:
        state = self.protector.calculate_multiplier(92_000, 100_000)
        assert state.multiplier == 0.4  # 8% drawdown
        assert state.status == "CAUTIOUS"

    def test_extreme_drawdown_over_10_pct(self) -> None:
        state = self.protector.calculate_multiplier(85_000, 100_000)
        assert state.multiplier == 0.1  # 15% drawdown
        assert state.status == "PROTECTIVE"

    def test_zero_peak_capital(self) -> None:
        state = self.protector.calculate_multiplier(100_000, 0)
        assert state.multiplier == 1.0
        assert state.current_drawdown == 0.0

    def test_negative_drawdown_when_above_peak(self) -> None:
        state = self.protector.calculate_multiplier(105_000, 100_000)
        assert state.multiplier == 1.0  # above peak = no drawdown
        assert state.current_drawdown < 0  # negative drawdown = above peak

    def test_apply_protection_scales_quantity(self) -> None:
        result = self.protector.apply_protection(base_qty=10, multiplier=0.7, lot_size=1)
        assert result == 7  # 70% of 10

    def test_apply_protection_rounds_to_lot_size(self) -> None:
        result = self.protector.apply_protection(base_qty=10, multiplier=0.35, lot_size=5)
        assert result == 5  # 3.5 rounds to 0 lots → minimum 5

    def test_apply_protection_minimum_one_lot(self) -> None:
        result = self.protector.apply_protection(base_qty=2, multiplier=0.1, lot_size=1)
        assert result == 1  # minimum 1 lot

    def test_apply_protection_zero_multiplier(self) -> None:
        result = self.protector.apply_protection(base_qty=10, multiplier=0.0, lot_size=1)
        assert result == 0  # 0 multiplier = nothing

    def test_boundary_at_exactly_2pct(self) -> None:
        """Exactly 2% drawdown should be in the < 5% band (multiplier 0.7)."""
        state = self.protector.calculate_multiplier(98_000, 100_000)
        assert state.multiplier == 0.7
        assert state.status == "REDUCED"

    def test_boundary_at_exactly_5pct(self) -> None:
        """Exactly 5% drawdown should be in the < 10% band (multiplier 0.4)."""
        state = self.protector.calculate_multiplier(95_000, 100_000)
        assert state.multiplier == 0.4
        assert state.status == "CAUTIOUS"
