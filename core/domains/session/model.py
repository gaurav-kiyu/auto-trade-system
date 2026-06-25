"""
Session Domain Models

This module contains the data models used in the session domain,
including market session and trading session models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MarketSessionType(Enum):
    """Types of market sessions."""
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    POST_MARKET = "post_market"
    CLOSED = "closed"


@dataclass
class MarketSession:
    """
    Represents a market trading session.

    Attributes:
        session_id: Unique session identifier
        session_type: Type of market session (pre-market, regular, etc.)
        start_time: Session start time
        end_time: Session end time
        is_open: Whether the market is currently open
        symbol: Trading symbol (for symbol-specific sessions)
        metadata: Additional context-specific data
    """
    session_id: str
    session_type: MarketSessionType
    start_time: datetime
    end_time: datetime
    is_open: bool = False
    symbol: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate market session after initialization."""
        if self.start_time > self.end_time:
            raise ValueError("Session start time must be before end time")

        # Auto-calculate is_open based on current time if not explicitly set
        # Note: This is simplified - in reality, would check against current time
        # self.is_open = self.start_time <= datetime.now() <= self.end_time


@dataclass
class TradingSession:
    """
    Represents a trading session for a specific strategy or system.

    Attributes:
        session_id: Unique session identifier
        strategy_name: Name of the strategy being traded
        start_time: When the trading session started
        end_time: When the trading session ended (None if ongoing)
        is_active: Whether the trading session is currently active
        positions: Dictionary of current positions
        total_pnl: Total profit/loss for the session
        trades_count: Number of trades executed
        metadata: Additional context-specific data
    """
    session_id: str
    strategy_name: str
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    is_active: bool = True
    positions: dict[str, Any] = field(default_factory=dict)  # Will be Position type when imported
    total_pnl: float = 0.0
    trades_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate trading session after initialization."""
        if self.end_time is not None and self.start_time > self.end_time:
            raise ValueError("Session start time must be before end time")

        if self.trades_count < 0:
            raise ValueError(f"Trades count cannot be negative, got {self.trades_count}")


@dataclass
class SessionStats:
    """
    Represents statistics for a trading session.

    Attributes:
        session_id: Session identifier
        duration_minutes: Session duration in minutes
        total_trades: Total number of trades
        winning_trades: Number of winning trades
        losing_trades: Number of losing trades
        win_rate: Percentage of winning trades
        total_pnl: Total profit/loss
        avg_trade_pnl: Average profit/loss per trade
        max_drawdown: Maximum drawdown during session
        sharpe_ratio: Sharpe ratio for the session
        profit_factor: Gross profit / gross loss
    """
    session_id: str
    duration_minutes: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_trade_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0

    def __post_init__(self):
        """Validate session stats after initialization."""
        if self.duration_minutes < 0:
            raise ValueError(f"Duration cannot be negative, got {self.duration_minutes}")

        if self.total_trades < 0:
            raise ValueError(f"Total trades cannot be negative, got {self.total_trades}")

        if self.winning_trades < 0:
            raise ValueError(f"Winning trades cannot be negative, got {self.winning_trades}")

        if self.losing_trades < 0:
            raise ValueError(f"Losing trades cannot be negative, got {self.losing_trades}")

        if self.winning_trades + self.losing_trades != self.total_trades:
            raise ValueError(
                f"Winning trades ({self.winning_trades}) + losing trades ({self.losing_trades}) "
                f"must equal total trades ({self.total_trades})"
            )

        if self.total_trades > 0:
            if not 0.0 <= self.win_rate <= 1.0:
                raise ValueError(f"Win rate must be between 0.0 and 1.0, got {self.win_rate}")

            if self.profit_factor < 0:
                raise ValueError(f"Profit factor cannot be negative, got {self.profit_factor}")


__all__ = [
    "MarketSession",
    "MarketSessionType",
    "SessionStats",
    "TradingSession",
]

