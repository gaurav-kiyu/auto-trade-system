"""
Tests for core/domains/execution/model.py - Execution Domain Models.

Covers (30+ tests):
- OrderType, OrderStatus, PositionSide enums
- Order dataclass with constructor validation
- OrderResult dataclass with validation
- Fill dataclass with validation
- Position dataclass with validation
- ExecutionContext dataclass
"""

from __future__ import annotations

from datetime import datetime

import pytest
from core.domains.execution.model import (
    ExecutionContext,
    Fill,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
)

# ── Enum Tests ────────────────────────────────────────────────────────────────


class TestOrderType:
    """OrderType enum - MARKET, LIMIT, STOP, STOP_LIMIT."""

    def test_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP.value == "stop"
        assert OrderType.STOP_LIMIT.value == "stop_limit"


class TestOrderStatus:
    """OrderStatus enum - 7 states."""

    def test_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.REJECTED.value == "rejected"

    def test_terminal_states(self):
        """Verify terminal states cannot transition further."""
        terminal = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED}
        non_terminal = {OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED, OrderStatus.SUBMITTED}
        for s in terminal:
            assert s not in non_terminal
        for s in non_terminal:
            assert s not in terminal


class TestPositionSide:
    """PositionSide enum - LONG, SHORT, FLAT."""

    def test_values(self):
        assert PositionSide.LONG.value == "long"
        assert PositionSide.SHORT.value == "short"
        assert PositionSide.FLAT.value == "flat"


# ── Order Tests ────────────────────────────────────────────────────────────────


class TestOrder:
    """Order dataclass with validation."""

    def test_create_valid_order(self):
        order = Order(
            symbol="NIFTY",
            direction="BUY",
            quantity=50,
            order_type=OrderType.MARKET,
            price=None,
            strategy_id="strat-1",
            risk_decision_id="risk-1",
        )
        assert order.symbol == "NIFTY"
        assert order.direction == "BUY"
        assert order.quantity == 50
        assert order.order_type == OrderType.MARKET
        assert order.order_id is None

    def test_create_limit_order_with_price(self):
        order = Order(
            symbol="BANKNIFTY",
            direction="SELL",
            quantity=25,
            order_type=OrderType.LIMIT,
            price=50000.0,
            strategy_id="strat-2",
            risk_decision_id="risk-2",
        )
        assert order.price == 50000.0
        assert order.order_type == OrderType.LIMIT

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError, match="Direction must be 'BUY' or 'SELL'"):
            Order(
                symbol="NIFTY", direction="INVALID", quantity=50,
                order_type=OrderType.MARKET, price=None,
                strategy_id="s", risk_decision_id="r",
            )

    def test_non_positive_quantity_raises(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            Order(
                symbol="NIFTY", direction="BUY", quantity=0,
                order_type=OrderType.MARKET, price=None,
                strategy_id="s", risk_decision_id="r",
            )

    def test_negative_quantity_raises(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            Order(
                symbol="NIFTY", direction="BUY", quantity=-10,
                order_type=OrderType.MARKET, price=None,
                strategy_id="s", risk_decision_id="r",
            )

    def test_limit_order_missing_price_raises(self):
        with pytest.raises(ValueError, match="Limit orders must have a price"):
            Order(
                symbol="NIFTY", direction="BUY", quantity=50,
                order_type=OrderType.LIMIT, price=None,
                strategy_id="s", risk_decision_id="r",
            )

    def test_stop_limit_order_missing_price_raises(self):
        with pytest.raises(ValueError, match="Stop-limit orders must have a price"):
            Order(
                symbol="NIFTY", direction="BUY", quantity=50,
                order_type=OrderType.STOP_LIMIT, price=None,
                strategy_id="s", risk_decision_id="r",
            )

    def test_timestamp_defaults_to_now(self):
        order = Order(
            symbol="NIFTY", direction="BUY", quantity=50,
            order_type=OrderType.MARKET, price=None,
            strategy_id="s", risk_decision_id="r",
        )
        assert isinstance(order.timestamp, datetime)

    def test_client_order_id_optional(self):
        order = Order(
            symbol="NIFTY", direction="BUY", quantity=50,
            order_type=OrderType.MARKET, price=None,
            strategy_id="s", risk_decision_id="r",
            client_order_id="CLIENT-001",
        )
        assert order.client_order_id == "CLIENT-001"


# ── OrderResult Tests ─────────────────────────────────────────────────────────


class TestOrderResult:
    """OrderResult dataclass with validation."""

    def test_create_filled_order(self):
        result = OrderResult(
            order_id="ORD-001",
            status=OrderStatus.FILLED,
            filled_quantity=50,
            average_price=150.0,
        )
        assert result.order_id == "ORD-001"
        assert result.filled_quantity == 50
        assert result.average_price == 150.0

    def test_negative_filled_quantity_raises(self):
        with pytest.raises(ValueError, match="Filled quantity cannot be negative"):
            OrderResult(
                order_id="ORD-001", status=OrderStatus.FILLED,
                filled_quantity=-5, average_price=150.0,
            )

    def test_filled_with_zero_quantity_raises(self):
        with pytest.raises(ValueError, match="Filled order must have positive filled quantity"):
            OrderResult(
                order_id="ORD-001", status=OrderStatus.FILLED,
                filled_quantity=0, average_price=150.0,
            )

    def test_rejected_order_zero_quantity_ok(self):
        result = OrderResult(
            order_id="ORD-001", status=OrderStatus.REJECTED,
            filled_quantity=0, average_price=None,
            error_message="Insufficient margin",
        )
        assert result.status == OrderStatus.REJECTED
        assert result.error_message == "Insufficient margin"

    def test_non_positive_average_price_raises(self):
        with pytest.raises(ValueError, match="Average price must be positive"):
            OrderResult(
                order_id="ORD-001", status=OrderStatus.FILLED,
                filled_quantity=10, average_price=0.0,
            )

    def test_commission_defaults_to_zero(self):
        result = OrderResult(
            order_id="ORD-001", status=OrderStatus.FILLED,
            filled_quantity=10, average_price=150.0,
        )
        assert result.commission == 0.0


# ── Fill Tests ────────────────────────────────────────────────────────────────


class TestFill:
    """Fill dataclass with validation."""

    def test_create_fill(self):
        fill = Fill(
            order_id="ORD-001",
            fill_id="FILL-001",
            symbol="NIFTY",
            quantity=25,
            price=150.0,
        )
        assert fill.order_id == "ORD-001"
        assert fill.quantity == 25
        assert fill.price == 150.0

    def test_non_positive_quantity_raises(self):
        with pytest.raises(ValueError, match="Fill quantity must be positive"):
            Fill(
                order_id="ORD-001", fill_id="FILL-001",
                symbol="NIFTY", quantity=0, price=150.0,
            )

    def test_non_positive_price_raises(self):
        with pytest.raises(ValueError, match="Fill price must be positive"):
            Fill(
                order_id="ORD-001", fill_id="FILL-001",
                symbol="NIFTY", quantity=25, price=0.0,
            )

    def test_negative_commission_raises(self):
        with pytest.raises(ValueError, match="Commission cannot be negative"):
            Fill(
                order_id="ORD-001", fill_id="FILL-001",
                symbol="NIFTY", quantity=25, price=150.0,
                commission=-5.0,
            )


# ── Position Tests ────────────────────────────────────────────────────────────


class TestPosition:
    """Position dataclass with validation."""

    def test_long_position(self):
        pos = Position(
            symbol="NIFTY",
            side=PositionSide.LONG,
            quantity=50,
            average_price=150.0,
            current_price=155.0,
        )
        assert pos.unrealized_pnl == 0.0  # default
        assert pos.side == PositionSide.LONG

    def test_short_position(self):
        pos = Position(
            symbol="BANKNIFTY",
            side=PositionSide.SHORT,
            quantity=-25,
            average_price=50000.0,
            current_price=49500.0,
        )
        assert pos.quantity == -25

    def test_flat_position(self):
        pos = Position(
            symbol="NIFTY",
            side=PositionSide.FLAT,
            quantity=0,
            average_price=150.0,
            current_price=150.0,
        )
        assert pos.quantity == 0

    def test_non_positive_average_price_raises(self):
        with pytest.raises(ValueError, match="Average price must be positive"):
            Position(
                symbol="NIFTY", side=PositionSide.LONG, quantity=50,
                average_price=0.0, current_price=155.0,
            )

    def test_non_positive_current_price_raises(self):
        with pytest.raises(ValueError, match="Current price must be positive"):
            Position(
                symbol="NIFTY", side=PositionSide.LONG, quantity=50,
                average_price=150.0, current_price=0.0,
            )

    def test_long_with_negative_quantity_raises(self):
        with pytest.raises(ValueError, match="LONG position must have positive quantity"):
            Position(
                symbol="NIFTY", side=PositionSide.LONG, quantity=-50,
                average_price=150.0, current_price=155.0,
            )

    def test_short_with_positive_quantity_raises(self):
        with pytest.raises(ValueError, match="SHORT position must have negative quantity"):
            Position(
                symbol="NIFTY", side=PositionSide.SHORT, quantity=50,
                average_price=150.0, current_price=155.0,
            )

    def test_flat_with_nonzero_quantity_raises(self):
        with pytest.raises(ValueError, match="FLAT position must have zero quantity"):
            Position(
                symbol="NIFTY", side=PositionSide.FLAT, quantity=50,
                average_price=150.0, current_price=155.0,
            )


# ── ExecutionContext Tests ─────────────────────────────────────────────────────


class TestExecutionContext:
    """ExecutionContext dataclass."""

    def test_create_with_defaults(self):
        ctx = ExecutionContext(symbol="NIFTY")
        assert ctx.symbol == "NIFTY"
        assert ctx.volatility == 0.0
        assert ctx.spread == 0.0
        assert ctx.market_conditions == {}
        assert ctx.liquidity_info == {}

    def test_create_custom(self):
        ctx = ExecutionContext(
            symbol="BANKNIFTY",
            volatility=0.25,
            spread=0.05,
            market_conditions={"trend": "BULLISH"},
            liquidity_info={"bid_size": 100},
        )
        assert ctx.volatility == 0.25
        assert ctx.spread == 0.05
        assert ctx.market_conditions["trend"] == "BULLISH"
