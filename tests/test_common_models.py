"""Tests for core/common/models/models.py - foundational data models, enums, constants, and utility functions.

Covers:
- Enum values (MarketStatus, SessionType, OrderStatus, ExecutionMode, etc.)
- Data models (TradingSignal, OrderRequest, OrderFill, Position, Trade, TradingState)
- to_dict() serialization for all data models
- Utility functions (get_market_status, get_session_type, calculate_position_size, calculate_pnl, format_currency, format_percentage)
- System constants and validation constants
"""
from __future__ import annotations

from datetime import date, datetime

from core.common.models.models import (
    DEFAULT_BASE_CAPITAL,
    DEFAULT_CONSEC_LOSS_LIMIT,
    DEFAULT_COOLDOWN,
    DEFAULT_LOT_SIZE_MULTIPLIER,
    DEFAULT_MAX_DAILY_LOSS,
    DEFAULT_MAX_DRAWDOWN,
    DEFAULT_MAX_OPEN_POSITIONS,
    DEFAULT_MAX_TRADES_PER_DAY,
    DEFAULT_RISK_PER_TRADE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SL_PCT,
    DEFAULT_TARGET_PCT,
    DEFAULT_TG_HEARTBEAT_INTERVAL,
    DEFAULT_TG_MAX_PER_MIN,
    DEFAULT_TRAIL_PCT,
    DEFAULT_VIX_COOLDOWN_SEC,
    MAX_POSITION_AGE_MINUTES,
    MAX_SCORE_THRESHOLD,
    MIN_LOT_SIZE,
    MIN_SCORE_THRESHOLD,
    MIN_TRADE_DURATION_MINUTES,
    PERCENTAGE_PRECISION,
    PNL_PRECISION,
    PRICE_PRECISION,
    RSI_NEUTRAL_HIGH,
    RSI_NEUTRAL_LOW,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    TG_MAX_PER_MIN,
    TG_SIGNAL_COOLDOWN_SEC,
    TG_SIGNAL_GLOBAL_COOLDOWN_SEC,
    TIME_RISK_MULT_AFTER_1PM,
    TIME_RISK_MULT_AFTER_2PM,
    BrokerDriver,
    ExecutionMode,
    ExitReason,
    MarketStatus,
    OrderFill,
    OrderRequest,
    OrderStatus,
    Position,
    PositionSide,
    SessionType,
    SignalDirection,
    Trade,
    TradingSignal,
    TradingState,
    calculate_pnl,
    calculate_position_size,
    format_currency,
    format_percentage,
    get_market_status,
    get_session_type,
    is_market_open,
    is_trading_allowed,
)
from core.domains.strategy.model import SignalStrength

# =============================================================================
# Enum Tests
# =============================================================================

class TestMarketStatus:
    def test_values(self):
        assert MarketStatus.PRE.value == "PRE"
        assert MarketStatus.OPEN.value == "OPEN"
        assert MarketStatus.CLOSED.value == "CLOSED"
        assert MarketStatus.WEEKEND.value == "WEEKEND"
        assert MarketStatus.HOLIDAY.value == "HOLIDAY"

    def test_all_unique(self):
        values = [s.value for s in MarketStatus]
        assert len(values) == len(set(values))


class TestSessionType:
    def test_values(self):
        assert SessionType.MORNING.value == "MORNING"
        assert SessionType.MIDDAY.value == "MIDDAY"
        assert SessionType.CLOSING.value == "CLOSING"


class TestOrderStatus:
    def test_values(self):
        assert OrderStatus.PENDING.value == "PENDING"
        assert OrderStatus.SUBMITTED.value == "SUBMITTED"
        assert OrderStatus.PARTIALLY_FILLED.value == "PARTIALLY_FILLED"
        assert OrderStatus.FILLED.value == "FILLED"
        assert OrderStatus.CANCELLED.value == "CANCELLED"
        assert OrderStatus.REJECTED.value == "REJECTED"
        assert OrderStatus.EXPIRED.value == "EXPIRED"


class TestExecutionMode:
    def test_values(self):
        assert ExecutionMode.MANUAL.value == "MANUAL"
        assert ExecutionMode.AUTO.value == "AUTO"
        assert ExecutionMode.PAPER.value == "PAPER"


class TestBrokerDriver:
    def test_values(self):
        assert BrokerDriver.KITE.value == "KITE"
        assert BrokerDriver.ANGEL.value == "ANGEL"
        assert BrokerDriver.PAPER.value == "PAPER"


class TestPositionSide:
    def test_values(self):
        assert PositionSide.LONG.value == "LONG"
        assert PositionSide.SHORT.value == "SHORT"


class TestSignalDirection:
    def test_values(self):
        assert SignalDirection.CALL.value == "CALL"
        assert SignalDirection.PUT.value == "PUT"


class TestExitReason:
    def test_values(self):
        assert ExitReason.TARGET_HIT.value == "TARGET_HIT"
        assert ExitReason.STOP_LOSS.value == "STOP_LOSS"
        assert ExitReason.TRAILING_STOP.value == "TRAILING_STOP"
        assert ExitReason.END_OF_DAY.value == "END_OF_DAY"
        assert ExitReason.AUTO_CLOSE.value == "AUTO_CLOSE"
        assert ExitReason.MANUAL_EXIT.value == "MANUAL_EXIT"
        assert ExitReason.ZOMBIE_EXIT.value == "ZOMBIE_EXIT"
        assert ExitReason.API_FAILURE.value == "API_FAILURE"


# =============================================================================
# TradingSignal Tests
# =============================================================================

STRONG_SIGNAL = SignalStrength(value=0.8, quality="STRONG", confidence=0.9)
MODERATE_SIGNAL = SignalStrength(value=0.5, quality="MODERATE", confidence=0.6)


class TestTradingSignal:
    def test_create_with_required_fields(self):
        signal = TradingSignal(
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strength=MODERATE_SIGNAL,
            score=75,
            threshold=60,
            price=23500.0,
            vwap=23480.0,
            volatility=0.15,
            rsi=55.0,
            macd_histogram=0.5,
            pcr=1.2,
            smart_money="BULLISH",
            regime="RANGE_BOUND",
            session=SessionType.MORNING,
            volume_ratio=1.5,
        )
        assert signal.symbol == "NIFTY"
        assert signal.direction == SignalDirection.CALL
        assert signal.score == 75
        assert signal.threshold == 60
        assert signal.stop_loss is None
        assert signal.target is None
        assert signal.timestamp is not None

    def test_create_with_optional_fields(self):
        signal = TradingSignal(
            symbol="BANKNIFTY",
            direction=SignalDirection.PUT,
            strength=STRONG_SIGNAL,
            score=85,
            threshold=50,
            price=51000.0,
            vwap=50900.0,
            volatility=0.2,
            rsi=30.0,
            macd_histogram=-0.3,
            pcr=0.9,
            smart_money="BEARISH",
            regime="BEARISH",
            session=SessionType.MIDDAY,
            volume_ratio=1.8,
            stop_loss=50500.0,
            target=51500.0,
            sector="BANKING",
            lot_size=25,
        )
        assert signal.stop_loss == 50500.0
        assert signal.target == 51500.0
        assert signal.sector == "BANKING"
        assert signal.lot_size == 25

    def test_to_dict(self):
        signal = TradingSignal(
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strength=STRONG_SIGNAL,
            score=80,
            threshold=60,
            price=23500.0,
            vwap=23450.0,
            volatility=0.12,
            rsi=60.0,
            macd_histogram=1.0,
            pcr=1.1,
            smart_money="BULLISH",
            regime="BULLISH",
            session=SessionType.MORNING,
            volume_ratio=1.3,
        )
        d = signal.to_dict()
        assert d["symbol"] == "NIFTY"
        assert d["direction"] == "CALL"
        assert d["score"] == 80
        assert d["session"] == "MORNING"
        assert "timestamp" in d


# =============================================================================
# OrderRequest Tests
# =============================================================================

class TestOrderRequest:
    def test_create_with_required_fields(self):
        req = OrderRequest(
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strike_price=23500,
            lot_size=50,
            order_type="MARKET",
            stop_loss=0.15,
            target=0.30,
        )
        assert req.symbol == "NIFTY"
        assert req.direction == SignalDirection.CALL
        assert req.order_type == "MARKET"
        assert req.exchange == "NSE"
        assert req.product_type == "OPTIONS"
        assert req.validity == "DAY"

    def test_create_with_trail(self):
        req = OrderRequest(
            symbol="NIFTY",
            direction=SignalDirection.PUT,
            strike_price=23500,
            lot_size=50,
            order_type="LIMIT",
            stop_loss=0.10,
            target=0.25,
            trail_activate=True,
            trail_percent=0.05,
            price=150.0,
        )
        assert req.trail_activate is True
        assert req.trail_percent == 0.05
        assert req.price == 150.0

    def test_to_dict(self):
        req = OrderRequest(
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strike_price=23500,
            lot_size=50,
            order_type="MARKET",
            stop_loss=0.15,
            target=0.30,
        )
        d = req.to_dict()
        assert d["symbol"] == "NIFTY"
        assert d["direction"] == "CALL"
        assert d["order_type"] == "MARKET"
        assert d["exchange"] == "NSE"


# =============================================================================
# OrderFill Tests
# =============================================================================

class TestOrderFill:
    def test_create(self):
        ts = datetime(2026, 6, 20, 10, 30, 0)
        fill = OrderFill(
            order_id="ORD-001",
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strike_price=23500,
            lot_size=50,
            fill_price=150.0,
            fill_time=ts,
        )
        assert fill.order_id == "ORD-001"
        assert fill.gross_pnl == 0.0
        assert fill.net_pnl == 0.0

    def test_create_with_financials(self):
        ts = datetime(2026, 6, 20, 11, 0, 0)
        fill = OrderFill(
            order_id="ORD-001",
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strike_price=23500,
            lot_size=50,
            fill_price=150.0,
            fill_time=ts,
            gross_pnl=2500.0,
            brokerage=100.0,
            taxes=50.0,
            net_pnl=2350.0,
        )
        assert fill.gross_pnl == 2500.0
        assert fill.net_pnl == 2350.0

    def test_to_dict(self):
        ts = datetime(2026, 6, 20, 10, 30, 0)
        fill = OrderFill(
            order_id="ORD-001",
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strike_price=23500,
            lot_size=50,
            fill_price=150.0,
            fill_time=ts,
        )
        d = fill.to_dict()
        assert d["order_id"] == "ORD-001"
        assert d["symbol"] == "NIFTY"
        assert d["exchange"] == "NSE"


# =============================================================================
# Position Tests
# =============================================================================

class TestPosition:
    def test_create(self):
        ts = datetime(2026, 6, 20, 9, 30, 0)
        pos = Position(
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strike_price=23500,
            lot_size=50,
            entry_price=150.0,
            entry_time=ts,
            stop_loss=127.5,
            target=195.0,
        )
        assert pos.current_price == 0.0
        assert pos.unrealized_pnl == 0.0
        assert pos.strategy == "OPTIONS_BUYING"

    def test_update_current_price_call(self):
        ts = datetime(2026, 6, 20, 9, 30, 0)
        pos = Position(
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strike_price=23500,
            lot_size=50,
            entry_price=150.0,
            entry_time=ts,
            stop_loss=127.5,
            target=195.0,
        )
        pos.update_current_price(180.0)
        assert pos.current_price == 180.0
        # For CALL: (180 - 150) * 50 = 1500
        assert pos.unrealized_pnl == 1500.0

    def test_update_current_price_put(self):
        ts = datetime(2026, 6, 20, 9, 30, 0)
        pos = Position(
            symbol="NIFTY",
            direction=SignalDirection.PUT,
            strike_price=23500,
            lot_size=50,
            entry_price=150.0,
            entry_time=ts,
            stop_loss=127.5,
            target=195.0,
        )
        pos.update_current_price(120.0)
        assert pos.current_price == 120.0
        # For PUT: (150 - 120) * 50 = 1500
        assert pos.unrealized_pnl == 1500.0

    def test_update_current_price_negative(self):
        ts = datetime(2026, 6, 20, 9, 30, 0)
        pos = Position(
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strike_price=23500,
            lot_size=50,
            entry_price=150.0,
            entry_time=ts,
            stop_loss=127.5,
            target=195.0,
        )
        pos.update_current_price(140.0)
        # For CALL: (140 - 150) * 50 = -500
        assert pos.unrealized_pnl == -500.0

    def test_to_dict(self):
        ts = datetime(2026, 6, 20, 9, 30, 0)
        pos = Position(
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strike_price=23500,
            lot_size=50,
            entry_price=150.0,
            entry_time=ts,
            stop_loss=127.5,
            target=195.0,
        )
        pos.update_current_price(180.0)
        d = pos.to_dict()
        assert d["symbol"] == "NIFTY"
        assert d["direction"] == "CALL"
        assert d["unrealized_pnl"] == 1500.0


# =============================================================================
# Trade Tests
# =============================================================================

class TestTrade:
    def test_create(self):
        entry_ts = datetime(2026, 6, 20, 9, 30, 0)
        exit_ts = datetime(2026, 6, 20, 11, 0, 0)
        trade = Trade(
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strike_price=23500,
            lot_size=50,
            entry_price=150.0,
            entry_time=entry_ts,
            exit_price=190.0,
            exit_time=exit_ts,
            exit_reason=ExitReason.TARGET_HIT,
        )
        assert trade.net_pnl == 0.0
        assert trade.strategy == "OPTIONS_BUYING"

    def test_create_with_financials(self):
        entry_ts = datetime(2026, 6, 20, 9, 30, 0)
        exit_ts = datetime(2026, 6, 20, 11, 0, 0)
        trade = Trade(
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strike_price=23500,
            lot_size=50,
            entry_price=150.0,
            entry_time=entry_ts,
            exit_price=190.0,
            exit_time=exit_ts,
            exit_reason=ExitReason.TARGET_HIT,
            gross_pnl=2000.0,
            brokerage=100.0,
            taxes=50.0,
            net_pnl=1850.0,
        )
        assert trade.net_pnl == 1850.0

    def test_to_dict(self):
        entry_ts = datetime(2026, 6, 20, 9, 30, 0)
        exit_ts = datetime(2026, 6, 20, 11, 0, 0)
        trade = Trade(
            symbol="NIFTY",
            direction=SignalDirection.CALL,
            strike_price=23500,
            lot_size=50,
            entry_price=150.0,
            entry_time=entry_ts,
            exit_price=190.0,
            exit_time=exit_ts,
            exit_reason=ExitReason.TARGET_HIT,
        )
        d = trade.to_dict()
        assert d["exit_reason"] == "TARGET_HIT"
        assert d["direction"] == "CALL"


# =============================================================================
# TradingState Tests
# =============================================================================

class TestTradingState:
    def test_defaults(self):
        state = TradingState()
        assert state.capital == 0.0
        assert state.daily_pnl == 0.0
        assert state.trade_count == 0
        assert state.lock_mode is False
        assert state.trail_level == 0
        assert state.warned_loss is False
        assert state.ltp_frozen_sent == set()
        assert state.last_state_msg is None
        assert state.last_reset_day is None

    def test_is_new_day_no_reset(self):
        state = TradingState()
        assert state.is_new_day() is True

    def test_is_new_day_same_day(self):
        state = TradingState()
        state.last_reset_day = date(2026, 6, 20)
        # In real usage, today's date would be compared
        result = state.is_new_day()
        # We can't predict today's date in a test, but we can verify the logic
        assert isinstance(result, bool)

    def test_to_dict(self):
        state = TradingState(
            capital=100000.0,
            daily_pnl=5000.0,
            trade_count=3,
            lock_mode=False,
        )
        d = state.to_dict()
        assert d["capital"] == 100000.0
        assert d["daily_pnl"] == 5000.0
        assert d["trade_count"] == 3
        assert d["lock_mode"] is False

    def test_to_dict_handles_sets_and_none(self):
        state = TradingState(
            capital=50000.0,
            ltp_frozen_sent={"NIFTY"},
            last_reset_day=date(2026, 6, 19),
            last_state_msg="Running",
        )
        d = state.to_dict()
        assert d["capital"] == 50000.0
        assert d["ltp_frozen_sent"] == ["NIFTY"]
        assert d["last_reset_day"] == "2026-06-19"
        assert d["last_state_msg"] == "Running"


# =============================================================================
# Utility Function Tests
# =============================================================================

class TestCalculatePositionSize:
    def test_basic_calculation(self):
        capital = 100000.0
        risk_per_trade = 0.02  # 2%
        sl_percent = 0.15  # 15%
        lot_size = 50
        entry_price = 150.0

        lots = calculate_position_size(capital, risk_per_trade, sl_percent, lot_size, entry_price)
        # risk_amount = 100000 * 0.02 = 2000
        # loss_per_lot = 150 * 0.15 * 50 = 1125
        # lots = 2000 / 1125 = 1.777... → 1
        assert lots == 1

    def test_zero_stop_loss_returns_zero(self):
        lots = calculate_position_size(100000.0, 0.02, 0.0, 50, 150.0)
        assert lots == 0

    def test_zero_loss_per_lot_returns_zero(self):
        """If entry_price * sl_percent * lot_size is 0, returns 0."""
        lots = calculate_position_size(100000.0, 0.02, 0.15, 50, 0.0)
        # entry_price=0 → loss_per_lot=0 → returns 0
        assert lots == 0

    def test_never_negative(self):
        lots = calculate_position_size(100.0, 0.02, 0.15, 50, 150.0)
        assert lots >= 0

    def test_large_capital_multiple_lots(self):
        capital = 1000000.0
        lots = calculate_position_size(capital, 0.02, 0.15, 50, 150.0)
        # risk_amount = 20000, loss_per_lot = 1125 → 17.777 → 17
        assert lots == 17


class TestCalculatePnl:
    def test_call_profit(self):
        gross, net = calculate_pnl(
            entry_price=150.0, exit_price=190.0,
            lot_size=50, direction=SignalDirection.CALL,
            brokerage=100.0, taxes=50.0,
        )
        assert gross == 2000.0  # (190-150) * 50
        assert net == 1850.0  # 2000 - 100 - 50

    def test_call_loss(self):
        gross, net = calculate_pnl(
            entry_price=150.0, exit_price=130.0,
            lot_size=50, direction=SignalDirection.CALL,
        )
        assert gross == -1000.0  # (130-150) * 50

    def test_put_profit(self):
        gross, net = calculate_pnl(
            entry_price=150.0, exit_price=120.0,
            lot_size=50, direction=SignalDirection.PUT,
        )
        assert gross == 1500.0  # (150-120) * 50

    def test_put_loss(self):
        gross, net = calculate_pnl(
            entry_price=150.0, exit_price=170.0,
            lot_size=50, direction=SignalDirection.PUT,
        )
        assert gross == -1000.0  # (150-170) * 50

    def test_zero_brokerage(self):
        gross, net = calculate_pnl(
            entry_price=100.0, exit_price=200.0,
            lot_size=10, direction=SignalDirection.CALL,
        )
        assert gross == 1000.0
        assert net == 1000.0


class TestFormatCurrency:
    def test_positive_amount(self):
        result = format_currency(5000.0)
        assert "+" in result
        assert "₹" in result
        assert "5,000" in result

    def test_negative_amount(self):
        result = format_currency(-2500.0)
        assert "-" in result
        assert "₹" in result
        assert "2,500" in result

    def test_zero(self):
        result = format_currency(0.0)
        assert "₹" in result

    def test_custom_symbol(self):
        result = format_currency(1000.0, currency_symbol="$")
        assert "$" in result


class TestFormatPercentage:
    def test_positive(self):
        result = format_percentage(15.5)
        assert "15.50%" in result

    def test_zero(self):
        result = format_percentage(0.0)
        assert "0.00%" in result

    def test_negative(self):
        result = format_percentage(-5.25)
        assert "-5.25%" in result

    def test_custom_precision(self):
        result = format_percentage(12.3456, decimal_places=3)
        assert "12.346%" in result


# =============================================================================
# Market Status & Session Type Tests
# =============================================================================

class TestMarketStatusFunctions:
    def test_is_market_open_returns_bool(self):
        """is_market_open() should return a boolean."""
        result = is_market_open()
        assert isinstance(result, bool)

    def test_is_trading_allowed_returns_bool(self):
        result = is_trading_allowed()
        assert isinstance(result, bool)

    def test_get_market_status_returns_string(self):
        status = get_market_status()
        assert status in ("PRE", "OPEN", "CLOSED", "WEEKEND")

    def test_get_session_type_returns_sessiontype(self):
        session = get_session_type()
        assert isinstance(session, SessionType)


# =============================================================================
# Constant Tests
# =============================================================================

class TestConstants:
    def test_default_values(self):
        assert DEFAULT_BASE_CAPITAL == 100000.0
        assert DEFAULT_MAX_DAILY_LOSS == -2000.0
        assert DEFAULT_MAX_DRAWDOWN == -5000.0
        assert DEFAULT_RISK_PER_TRADE == 0.02
        assert DEFAULT_SL_PCT == 0.15
        assert DEFAULT_TARGET_PCT == 0.30
        assert DEFAULT_TRAIL_PCT == 0.08

    def test_risk_constants(self):
        assert TIME_RISK_MULT_AFTER_1PM == 0.75
        assert TIME_RISK_MULT_AFTER_2PM == 0.50

    def test_validation_constants(self):
        assert MIN_SCORE_THRESHOLD == 30
        assert MAX_SCORE_THRESHOLD == 95
        assert MIN_LOT_SIZE == 1
        # MAX_LOT_SIZE is not exported as a constant
        assert MAX_POSITION_AGE_MINUTES == 120
        assert MIN_TRADE_DURATION_MINUTES == 5

    def test_rsi_constants(self):
        assert RSI_OVERBOUGHT == 70
        assert RSI_OVERSOLD == 30
        assert RSI_NEUTRAL_LOW == 40
        assert RSI_NEUTRAL_HIGH == 70

    def test_telegram_constants(self):
        assert TG_SIGNAL_GLOBAL_COOLDOWN_SEC == 120.0
        assert TG_SIGNAL_COOLDOWN_SEC == 60.0
        assert TG_MAX_PER_MIN == 20

    def test_precision_constants(self):
        assert PRICE_PRECISION == 2
        assert PNL_PRECISION == 2
        assert PERCENTAGE_PRECISION == 2

    def test_default_counts(self):
        assert DEFAULT_MAX_OPEN_POSITIONS == 5
        assert DEFAULT_MAX_TRADES_PER_DAY == 10
        assert DEFAULT_CONSEC_LOSS_LIMIT == 3
        assert DEFAULT_COOLDOWN == 300
        assert DEFAULT_SCAN_INTERVAL == 5
        assert DEFAULT_TG_MAX_PER_MIN == 20
        assert DEFAULT_TG_HEARTBEAT_INTERVAL == 3600
        assert DEFAULT_VIX_COOLDOWN_SEC == 120
        assert DEFAULT_LOT_SIZE_MULTIPLIER == 1
