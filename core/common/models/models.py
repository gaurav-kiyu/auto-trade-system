"""
Shared data models and constants for the trading system.
Defines standard data structures and enumerations used throughout the system.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Import shared models from common kernels to avoid duplication
from core.datetime_ist import now_ist

# ...existing code...

class MarketStatus(Enum):
    """Market status enumeration."""
    PRE = "PRE"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"


# ...existing code...
class SessionType(Enum):
    """Trading session type."""
    MORNING = "MORNING"
    MIDDAY = "MIDDAY"
    CLOSING = "CLOSING"

class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ExecutionMode(Enum):
    """Execution mode enumeration."""
    MANUAL = "MANUAL"  # Signals only, no auto execution
    AUTO = "AUTO"      # Automatic execution when gates pass
    PAPER = "PAPER"    # Paper/simulated trading


class BrokerDriver(Enum):
    """Supported broker drivers."""
    KITE = "KITE"
    ANGEL = "ANGEL"
    PAPER = "PAPER"


class PositionSide(Enum):
    """Position side."""

    LONG = "LONG"
    SHORT = "SHORT"


class ExitReason(Enum):
    """Position exit reason."""
    TARGET_HIT = "TARGET_HIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    END_OF_DAY = "END_OF_DAY"
    AUTO_CLOSE = "AUTO_CLOSE"
    MANUAL_EXIT = "MANUAL_EXIT"
    ZOMBIE_EXIT = "ZOMBIE_EXIT"
    API_FAILURE = "API_FAILURE"


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class TradingSignal:
    """Trading signal data model."""
    symbol: str
    direction: SignalDirection
    strength: SignalStrength
    score: int
    threshold: int
    price: float
    vwap: float
    volatility: float
    rsi: float
    macd_histogram: float
    pcr: float
    smart_money: str  # "BULLISH", "BEARISH", or "--"
    regime: MarketRegime
    session: SessionType
    volume_ratio: float
    timestamp: datetime.datetime = field(default_factory=now_ist)

    # Optional calculated values (must come after required fields)
    stop_loss: float | None = None
    target: float | None = None
    trail_stop: float | None = None

    # Optional metadata
    sector: str | None = None
    lot_size: int | None = None
    bid_ask_spread: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "direction": self.direction.name,
            "strength": self.strength.name,
            "score": self.score,
            "threshold": self.threshold,
            "price": self.price,
            "vwap": self.vwap,
            "volatility": self.volatility,
            "rsi": self.rsi,
            "macd_histogram": self.macd_histogram,
            "pcr": self.pcr,
            "smart_money": self.smart_money,
            "regime": self.regime.name,
            "session": self.session.value,
            "volume_ratio": self.volume_ratio,
            "timestamp": self.timestamp.isoformat(),
            "stop_loss": self.stop_loss,
            "target": self.target,
            "trail_stop": self.trail_stop,
            "sector": self.sector,
            "lot_size": self.lot_size,
            "bid_ask_spread": self.bid_ask_spread
        }


@dataclass
class OrderRequest:
    """Order request data model."""
    symbol: str
    direction: SignalDirection
    strike_price: float
    lot_size: int
    order_type: str  # "MARKET", "LIMIT"
    stop_loss: float
    target: float
    trail_activate: bool = False
    trail_percent: float | None = None
    price: float | None = None  # For limit orders
    timestamp: datetime.datetime = field(default_factory=now_ist)

    # Broker-specific fields
    exchange: str = "NSE"
    product_type: str = "OPTIONS"
    validity: str = "DAY"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "direction": self.direction.name,
            "strike_price": self.strike_price,
            "lot_size": self.lot_size,
            "order_type": self.order_type,
            "price": self.price,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "trail_activate": self.trail_activate,
            "trail_percent": self.trail_percent,
            "timestamp": self.timestamp.isoformat(),
            "exchange": self.exchange,
            "product_type": self.product_type,
            "validity": self.validity
        }


@dataclass
class OrderFill:
    """Order fill data model."""
    order_id: str
    symbol: str
    direction: SignalDirection
    strike_price: float
    lot_size: int
    fill_price: float
    fill_time: datetime.datetime
    broker_order_id: str | None = None
    broker_timestamp: datetime.datetime | None = None

    # Financials
    gross_pnl: float = 0.0
    brokerage: float = 0.0
    taxes: float = 0.0
    net_pnl: float = 0.0

    # Metadata
    exchange: str = "NSE"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "direction": self.direction.name,
            "strike_price": self.strike_price,
            "lot_size": self.lot_size,
            "fill_price": self.fill_price,
            "fill_time": self.fill_time.isoformat(),
            "broker_order_id": self.broker_order_id,
            "broker_timestamp": self.broker_timestamp.isoformat() if self.broker_timestamp else None,
            "gross_pnl": self.gross_pnl,
            "brokerage": self.brokerage,
            "taxes": self.taxes,
            "net_pnl": self.net_pnl,
            "exchange": self.exchange
        }


@dataclass
class Position:
    """Trading position data model."""
    symbol: str
    direction: SignalDirection
    strike_price: float
    lot_size: int
    entry_price: float
    entry_time: datetime.datetime
    stop_loss: float
    target: float
    trail_stop: float | None = None
    trailing_activated: bool = False

    # Current state
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    # Metadata
    strategy: str = "OPTIONS_BUYING"
    tags: list[str] = field(default_factory=list)

    def update_current_price(self, price: float) -> None:
        """Update current price and calculate unrealized P&L."""
        self.current_price = price
        if self.direction == SignalDirection.CALL:
            self.unrealized_pnl = (price - self.entry_price) * self.lot_size
        else:  # PUT
            self.unrealized_pnl = (self.entry_price - price) * self.lot_size

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "direction": self.direction.name,
            "strike_price": self.strike_price,
            "lot_size": self.lot_size,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "stop_loss": self.stop_loss,
            "target": self.target,
            "trail_stop": self.trail_stop,
            "trailing_activated": self.trailing_activated,
            "current_price": self.current_price,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "strategy": self.strategy,
            "tags": self.tags
        }


@dataclass
class Trade:
    """Completed trade data model."""
    symbol: str
    direction: SignalDirection
    strike_price: float
    lot_size: int
    entry_price: float
    entry_time: datetime.datetime
    exit_price: float
    exit_time: datetime.datetime
    exit_reason: ExitReason

    # Financials
    gross_pnl: float = 0.0
    brokerage: float = 0.0
    taxes: float = 0.0
    net_pnl: float = 0.0

    # Metadata
    strategy: str = "OPTIONS_BUYING"
    tags: list[str] = field(default_factory=list)
    regime_at_entry: MarketRegime | None = None
    session_at_entry: SessionType | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "direction": self.direction.name,
            "strike_price": self.strike_price,
            "lot_size": self.lot_size,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "exit_price": self.exit_price,
            "exit_time": self.exit_time.isoformat(),
            "exit_reason": self.exit_reason.value,
            "gross_pnl": self.gross_pnl,
            "brokerage": self.brokerage,
            "taxes": self.taxes,
            "net_pnl": self.net_pnl,
            "strategy": self.strategy,
            "tags": self.tags,
            "regime_at_entry": self.regime_at_entry.name if self.regime_at_entry else None,
            "session_at_entry": self.session_at_entry.value if self.session_at_entry else None
        }


@dataclass
class TradingState:
    """Trading system state data model."""
    capital: float = 0.0
    daily_pnl: float = 0.0
    net_daily_pnl: float = 0.0
    peak_pnl: float = 0.0
    trade_count: int = 0
    lock_mode: bool = False
    trail_level: int = 0

    # Pending adjustments
    capital_adj_pending: float = 0.0

    # Flags
    warned_loss: bool = False
    warned_loss_soft: bool = False
    csv_error_alerted: bool = False
    cb_alert: bool = False
    target_hit: bool = False
    eod_report_sent: bool = False

    # Tracking
    eod_report_sent_date: datetime.date | None = None
    ltp_frozen_sent: set = field(default_factory=set)
    last_reset_day: datetime.date | None = None
    last_heartbeat: float = 0.0
    last_summary_ts: float = 0.0
    last_state_msg: str | None = None
    last_loop_heartbeat: float = field(default_factory=time.monotonic)
    last_market_status: str = ""
    last_lot_sizes: dict[str, int] = field(default_factory=dict)
    saved_config: dict[str, Any] = field(default_factory=dict)
    checkpoints_fired: set = field(default_factory=set)
    exception_counts: dict[str, int] = field(default_factory=dict)
    exception_alerted: set = field(default_factory=set)
    last_prices: dict[str, float] = field(default_factory=dict)

    def is_new_day(self) -> bool:
        """Check if today is a new day compared to last reset."""
        today = now_ist().date()
        return self.last_reset_day != today

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "capital": self.capital,
            "daily_pnl": self.daily_pnl,
            "net_daily_pnl": self.net_daily_pnl,
            "peak_pnl": self.peak_pnl,
            "trade_count": self.trade_count,
            "lock_mode": self.lock_mode,
            "trail_level": self.trail_level,
            "capital_adj_pending": self.capital_adj_pending,
            "warned_loss": self.warned_loss,
            "warned_loss_soft": self.warned_loss_soft,
            "csv_error_alerted": self.csv_error_alerted,
            "cb_alert": self.cb_alert,
            "target_hit": self.target_hit,
            "eod_report_sent": self.eod_report_sent,
            "eod_report_sent_date": self.eod_report_sent_date.isoformat() if self.eod_report_sent_date else None,
            "ltp_frozen_sent": list(self.ltp_frozen_sent),
            "last_reset_day": self.last_reset_day.isoformat() if self.last_reset_day else None,
            "last_heartbeat": self.last_heartbeat,
            "last_summary_ts": self.last_summary_ts,
            "last_state_msg": self.last_state_msg,
            "last_loop_heartbeat": self.last_loop_heartbeat,
            "last_market_status": self.last_market_status,
            "last_lot_sizes": self.last_lot_sizes,
            "saved_config": self.saved_config,
            "checkpoints_fired": list(self.checkpoints_fired),
            "exception_counts": self.exception_counts,
            "exception_alerted": list(self.exception_alerted),
            "last_prices": self.last_prices
        }


# =============================================================================
# SYSTEM CONSTANTS
# =============================================================================

# Default values (would normally be loaded from config)
DEFAULT_BASE_CAPITAL: float = 100000.0
DEFAULT_MAX_DAILY_LOSS: float = -2000.0
DEFAULT_MAX_DRAWDOWN: float = -5000.0
DEFAULT_RISK_PER_TRADE: float = 0.02  # 2% of capital per trade
DEFAULT_SL_PCT: float = 0.15  # 15% stop loss
DEFAULT_TARGET_PCT: float = 0.30  # 30% target
DEFAULT_TRAIL_PCT: float = 0.08  # 8% trail
DEFAULT_MAX_OPEN_POSITIONS: int = 5
DEFAULT_MAX_TRADES_PER_DAY: int = 10
DEFAULT_SCAN_INTERVAL: int = 5  # minutes
DEFAULT_COOLDOWN: int = 300  # seconds
DEFAULT_TG_MAX_PER_MIN: int = 20  # Telegram messages per minute
DEFAULT_CONSEC_LOSS_LIMIT: int = 3
DEFAULT_VIX_COOLDOWN_SEC: int = 120
DEFAULT_TG_HEARTBEAT_INTERVAL: int = 3600  # 1 hour

# Time-based constants
MARKET_OPEN_HOUR: int = 9
MARKET_OPEN_MINUTE: int = 15
MARKET_CLOSE_HOUR: int = 15
MARKET_CLOSE_MINUTE: int = 20
CONTINUOUS_TRADE_START_HOUR: int = 9
CONTINUOUS_TRADE_START_MINUTE: int = 20
MARKET_CLOSED_HOUR: int = 15
MARKET_CLOSED_MINUTE: int = 30
BLOCK_NEW_ENTRIES_FROM_HOUR: int = 15
BLOCK_NEW_ENTRIES_FROM_MINUTE: int = 0
POST_OPEN_NO_TRADE_MINUTES: int = 10
EARLY_SESSION_END_HOUR: int = 10
EARLY_SESSION_END_MINUTE: int = 15

# Risk management constants
TIME_RISK_MULT_AFTER_1PM: float = 0.75
TIME_RISK_MULT_AFTER_2PM: float = 0.50
EARLY_SESSION_RISK_MULT: float = 1.0

# File and directory constants
LOG_DIR: str = "logs"
STATE_FILE: str = "trader_state.json"
TRADE_LOG_FILE: str = "trade_log.csv"
CONFIG_FILE: str = "config.json"
DEFAULTS_FILE: str = "config.defaults.json"

# Validation constants
MIN_SCORE_THRESHOLD: int = 30
MAX_SCORE_THRESHOLD: int = 95
MIN_LOT_SIZE: int = 1
MAX_POSITION_AGE_MINUTES: int = 120
MIN_TRADE_DURATION_MINUTES: int = 5

# Notification constants
TG_SIGNAL_GLOBAL_COOLDOWN_SEC: float = 120.0
TG_SIGNAL_COOLDOWN_SEC: float = 60.0
TG_MAX_PER_MIN: int = 20

# Mathematical constants
RSI_OVERBOUGHT: int = 70
RSI_OVERSOLD: int = 30
RSI_NEUTRAL_LOW: int = 40
RSI_NEUTRAL_HIGH: int = 70

# Market data constants
DEFAULT_LOT_SIZE_MULTIPLIER: int = 1
PRICE_PRECISION: int = 2
PNL_PRECISION: int = 2
PERCENTAGE_PRECISION: int = 2

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_market_status():
    """Get current market status."""
    from trading_system.core.datetime_ist import market_status as _market_status
    status_str = _market_status()
    # Convert string to enum
    from core.common.models.models import MarketStatus
    return MarketStatus(status_str)


def get_session_type():
    """Get current session type."""
    from trading_system.core.datetime_ist import get_regime as _get_regime
    regime_str = _get_regime()
    # Map regime to session type (simplified mapping)
    from core.common.models.models import SessionType
    regime_map = {
        "MORNING": SessionType.MORNING,
        "MIDDAY": SessionType.MIDDAY,
        "CLOSING": SessionType.CLOSING
    }
    return regime_map.get(regime_str, SessionType.MIDDAY)


def is_market_open() -> bool:
    """Check if market is currently open."""
    return get_market_status() == MarketStatus.OPEN


def is_trading_allowed() -> bool:
    """Check if trading is currently allowed based on market status."""
    status = get_market_status()
    return status in [MarketStatus.PRE, MarketStatus.OPEN]


def calculate_position_size(
    capital: float,
    risk_per_trade: float,
    stop_loss_percent: float,
    lot_size: int,
    entry_price: float
) -> int:
    """
    Calculate position size based on risk parameters.

    Args:
        capital: Available capital
        risk_per_trade: Fraction of capital to risk per trade (e.g., 0.02 for 2%)
        stop_loss_percent: Stop loss as fraction of entry price (e.g., 0.15 for 15%)
        lot_size: Lot size for the instrument
        entry_price: Entry price per share

    Returns:
        Number of lots to trade
    """
    if stop_loss_percent <= 0:
        return 0

    risk_amount = capital * risk_per_trade
    loss_per_lot = entry_price * stop_loss_percent * lot_size

    if loss_per_lot <= 0:
        return 0

    lots = int(risk_amount / loss_per_lot)
    return max(lots, 0)


def calculate_pnl(
    entry_price: float,
    exit_price: float,
    lot_size: int,
    direction: SignalDirection,
    brokerage: float = 0.0,
    taxes: float = 0.0
) -> tuple[float, float]:
    """
    Calculate gross and net P&L for a trade.

    Returns:
        Tuple of (gross_pnl, net_pnl)
    """
    if direction == SignalDirection.CALL:
        gross_pnl = (exit_price - entry_price) * lot_size
    else:  # PUT
        gross_pnl = (entry_price - exit_price) * lot_size

    net_pnl = gross_pnl - brokerage - taxes
    return gross_pnl, net_pnl


def format_currency(amount: float, currency_symbol: str = "₹") -> str:
    """Format amount as currency string."""
    if amount >= 0:
        return f"+{currency_symbol}{round(amount,0):,.0f}"
    else:
        return f"-{currency_symbol}{abs(round(amount,0)):,.0f}"


def format_percentage(value: float, decimal_places: int = 2) -> str:
    """Format value as percentage string."""
    return f"{value:.{decimal_places}f}%"
