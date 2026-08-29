"""Comprehensive bridge PnL tests — verifies direction-aware PnL calculations.

This module tests the edge cases for unrealized PnL conversion
from trader positions to domain models, including short positions,
zero PnL, and large position sizes.
"""

from __future__ import annotations

import pytest
from core.positions.bridge import (
    commodity_trade_to_domain,
    currency_trade_to_domain,
    equity_trade_to_domain,
    futures_trade_to_domain,
)


class MockPos:
    """Minimal mock with just the attributes the bridge needs."""

    def __init__(self, symbol: str, direction: str, qty: int, entry_price: float,
                 current_price: float | None = None, margin_used: float = 0.0,
                 expiry: str = "2026-09-26") -> None:
        self.symbol = symbol
        self.direction = direction
        self.qty = qty
        self.entry_price = entry_price
        if current_price is not None:
            self.current_price = current_price
        self.margin_used = margin_used
        self.expiry = expiry


class TestBridgePnL:
    """Verify PnL calculations are direction-aware."""

    def test_long_profit(self) -> None:
        """BUY position, price up → positive PnL."""
        p = MockPos("GOLD", "BUY", 10, 100.0, 110.0)
        cp = commodity_trade_to_domain({"X": p})[0]
        # (110 - 100) * 10 = 100
        assert cp.unrealized_pnl == 100.0, f"Expected 100.0, got {cp.unrealized_pnl}"

    def test_long_loss(self) -> None:
        """BUY position, price down → negative PnL."""
        p = MockPos("GOLD", "BUY", 10, 100.0, 90.0)
        cp = commodity_trade_to_domain({"X": p})[0]
        # (90 - 100) * 10 = -100
        assert cp.unrealized_pnl == -100.0, f"Expected -100.0, got {cp.unrealized_pnl}"

    def test_long_zero_pnl(self) -> None:
        """BUY position, price unchanged → PnL = 0."""
        p = MockPos("GOLD", "BUY", 10, 100.0, 100.0)
        cp = commodity_trade_to_domain({"X": p})[0]
        assert cp.unrealized_pnl == 0.0

    def test_short_profit_scenario(self) -> None:
        """SELL position, price down → positive PnL (direction-aware bridge)."""
        p = MockPos("SILVER", "SELL", 5, 200.0, 180.0)
        cp = commodity_trade_to_domain({"X": p})[0]
        # Bridge: (180 - 200) * 5 * -1 = 100 (short profit when price drops)
        assert cp.unrealized_pnl == 100.0
        assert cp.quantity == -5

    def test_short_loss_scenario(self) -> None:
        """SELL position, price up → negative PnL (direction-aware bridge)."""
        p = MockPos("SILVER", "SELL", 5, 200.0, 220.0)
        cp = commodity_trade_to_domain({"X": p})[0]
        # Bridge: (220 - 200) * 5 * -1 = -100 (loss when price goes up for short)
        assert cp.unrealized_pnl == -100.0
        assert cp.quantity == -5


        p = MockPos("NIFTY", "BUY", 50, 24500.0, 24600.0)
        fp = futures_trade_to_domain({"X": p})[0]
        # (24600 - 24500) * 50 = 5000
        assert fp.unrealized_pnl == 5000.0

    def test_futures_long_loss(self) -> None:
        p = MockPos("NIFTY", "BUY", 50, 24500.0, 24400.0)
        fp = futures_trade_to_domain({"X": p})[0]
        # (24400 - 24500) * 50 = -5000
        assert fp.unrealized_pnl == -5000.0

    def test_currency_long_profit(self) -> None:
        p = MockPos("USDINR", "BUY", 1000, 83.50, 83.75)
        cp = currency_trade_to_domain({"X": p})[0]
        # (83.75 - 83.50) * 1000 = 250
        assert cp.unrealized_pnl == 250.0

    def test_large_position_pnl(self) -> None:
        p = MockPos("GOLD", "BUY", 1000, 100.0, 110.0)
        cp = commodity_trade_to_domain({"X": p})[0]
        # (110 - 100) * 1000 = 10000
        assert cp.unrealized_pnl == 10000.0

    def test_single_lot(self) -> None:
        p = MockPos("GOLD", "BUY", 1, 100.0, 101.0)
        cp = commodity_trade_to_domain({"X": p})[0]
        # (101 - 100) * 1 = 1
        assert cp.unrealized_pnl == 1.0

    def test_fractional_price_diff(self) -> None:
        p = MockPos("GOLD", "BUY", 10, 100.0, 100.05)
        cp = commodity_trade_to_domain({"X": p})[0]
        # (100.05 - 100.00) * 10 = 0.5
        assert cp.unrealized_pnl == pytest.approx(0.5, rel=1e-6)


class TestBridgeCurrentPrice:
    """Verify current_price handling edge cases."""

    def test_current_price_attr_missing(self) -> None:
        p = MockPos("GOLD", "BUY", 10, 100.0)  # no current_price
        cp = commodity_trade_to_domain({"X": p})[0]
        assert cp.current_price == 100.0  # falls back to entry_price
        assert cp.unrealized_pnl == 0.0  # current == entry

    def test_current_price_zero(self) -> None:
        p = MockPos("GOLD", "BUY", 10, 100.0, 0.0)
        cp = commodity_trade_to_domain({"X": p})[0]
        # Current price == 0, _current_price falls back to entry_price (100)
        assert cp.current_price == 100.0

    def test_current_price_none(self) -> None:
        p = MockPos("GOLD", "BUY", 10, 100.0, None)  # type: ignore[arg-type]
        cp = commodity_trade_to_domain({"X": p})[0]
        assert cp.current_price == 100.0

    def test_equity_buy_profit(self) -> None:
        """Equity BUY position, price up → positive PnL."""
        pos = {"RELIANCE": {"direction": "BUY", "qty": 10, "entry_price": 2500.0,
                            "current_price": 2600.0, "asset_class": "EQUITY"}}
        ep = equity_trade_to_domain(pos)[0]
        # (2600 - 2500) * 10 = 1000
        assert ep.unrealized_pnl == 1000.0
        assert ep.stock.symbol == "RELIANCE"
        assert ep.quantity == 10

    def test_equity_buy_loss(self) -> None:
        """Equity BUY position, price down → negative PnL."""
        pos = {"TCS": {"direction": "BUY", "qty": 5, "entry_price": 3500.0,
                        "current_price": 3400.0, "asset_class": "EQUITY"}}
        ep = equity_trade_to_domain(pos)[0]
        # (3400 - 3500) * 5 = -500
        assert ep.unrealized_pnl == -500.0

    def test_equity_sell_profit(self) -> None:
        """Equity SELL position, price down → positive PnL (direction-aware)."""
        pos = {"HDFC": {"direction": "SELL", "qty": 20, "entry_price": 1600.0,
                         "current_price": 1550.0, "asset_class": "EQUITY"}}
        ep = equity_trade_to_domain(pos)[0]
        # (1600 - 1550) * 20 = 1000 (reverse for shorts)
        assert ep.unrealized_pnl == 1000.0
        assert ep.quantity == -20

    def test_equity_sell_loss(self) -> None:
        """Equity SELL position, price up → negative PnL (direction-aware)."""
        pos = {"SBIN": {"direction": "SELL", "qty": 15, "entry_price": 800.0,
                         "current_price": 820.0, "asset_class": "EQUITY"}}
        ep = equity_trade_to_domain(pos)[0]
        # (800 - 820) * 15 = -300
        assert ep.unrealized_pnl == -300.0

    def test_equity_no_current_price(self) -> None:
        """Equity position without current_price falls back to entry_price."""
        pos = {"WIPRO": {"direction": "BUY", "qty": 10, "entry_price": 450.0,
                          "asset_class": "EQUITY"}}
        ep = equity_trade_to_domain(pos)[0]
        assert ep.current_price == 450.0
        assert ep.unrealized_pnl == 0.0

    def test_equity_empty_dict(self) -> None:
        """Empty equity positions dict returns empty list."""
        assert equity_trade_to_domain({}) == []

    def test_equity_zero_entry_price_skipped(self) -> None:
        """Equity position with zero entry_price is skipped."""
        pos = {"BAD": {"direction": "BUY", "qty": 10, "entry_price": 0,
                        "asset_class": "EQUITY"}}
        assert equity_trade_to_domain(pos) == []

    def test_multiple_prices(self) -> None:
        """Multiple positions with different current prices."""
        p1 = MockPos("GOLD", "BUY", 10, 100.0, 110.0)
        p2 = MockPos("SILVER", "BUY", 20, 50.0, 45.0)
        result = commodity_trade_to_domain({"GOLD": p1, "SILVER": p2})
        assert len(result) == 2
        pnl_sum = sum(p.unrealized_pnl for p in result)
        # GOLD: (110-100)*10 = 100, SILVER: (45-50)*20 = -100, sum = 0
        assert pnl_sum == 0.0
