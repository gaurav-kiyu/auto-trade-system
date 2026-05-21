"""
Portfolio Domain Models

This module contains the data models used in the portfolio domain,
including portfolio snapshots and position tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PositionSnapshot:
    """
    Represents a snapshot of a single position at a point in time.

    Attributes:
        symbol: Trading symbol
        quantity: Position quantity
        average_price: Average entry price
        current_price: Current market price
        market_value: Current market value of position
        unrealized_pnl: Unrealized profit/loss
        realized_pnl: Realized profit/loss
        timestamp: When this snapshot was taken
    """
    symbol: str
    quantity: int
    average_price: float
    current_price: float
    market_value: float = field(init=False)
    unrealized_pnl: float = field(init=False)
    realized_pnl: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Calculate derived fields and validate after initialization."""
        if self.average_price <= 0:
            raise ValueError(f"Average price must be positive, got {self.average_price}")

        if self.current_price <= 0:
            raise ValueError(f"Current price must be positive, got {self.current_price}")

        # Calculate market value and unrealized P&L
        self.market_value = self.quantity * self.current_price
        self.unrealized_pnl = (self.current_price - self.average_price) * self.quantity

        # Validate quantity makes sense
        if self.quantity == 0:
            # Flat position - prices should still be valid but P&L should be zero
            if self.unrealized_pnl != 0:
                # This might happen due to floating point, but we'll reset
                self.unrealized_pnl = 0.0


@dataclass
class PortfolioSnapshot:
    """
    Represents a snapshot of the entire portfolio at a point in time.

    Attributes:
        timestamp: When this snapshot was taken
        total_value: Total portfolio value (cash + positions)
        cash: Cash balance
        positions: Dictionary of symbol -> PositionSnapshot
        daily_pnl: Profit/loss for the current day
        total_pnl: Total profit/loss since inception
        metadata: Additional context-specific data
    """
    timestamp: datetime = field(default_factory=datetime.now)
    total_value: float = 0.0
    cash: float = 0.0
    positions: dict[str, PositionSnapshot] = field(default_factory=dict)
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Calculate derived fields and validate after initialization."""
        if self.cash < 0:
            raise ValueError(f"Cash balance cannot be negative, got {self.cash}")

        # Recalculate total value from cash and positions
        positions_value = sum(pos.market_value for pos in self.positions.values())
        self.total_value = self.cash + positions_value

        # Validate that total_pnl makes sense relative to daily_pnl
        # (This is a soft validation - total_pnl could be less if we had losses before today)


@dataclass
class PortfolioPerformance:
    """
    Represents performance metrics for a portfolio over a period.

    Attributes:
        period_start: Start date of the period
        period_end: End date of the period
        total_return: Total return percentage
        annualized_return: Annualized return percentage
        volatility: Volatility (standard deviation of returns)
        sharpe_ratio: Sharpe ratio
        max_drawdown: Maximum drawdown percentage
        win_rate: Percentage of profitable trades
        profit_factor: Gross profit / gross loss
        total_trades: Total number of trades
        winning_trades: Number of winning trades
        losing_trades: Number of losing trades
        avg_win: Average winning trade amount
        avg_loss: Average losing trade amount
        largest_win: Largest winning trade
        largest_loss: Largest losing trade
    """
    period_start: datetime
    period_end: datetime
    total_return: float = 0.0
    annualized_return: float = 0.0
    volatility: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0

    def __post_init__(self):
        """Validate performance metrics after initialization."""
        if self.period_start > self.period_end:
            raise ValueError("Period start must be before period end")

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

            # avg_loss and largest_loss are typically expressed as positive numbers representing magnitude
            # So we allow them to be positive


@dataclass
class ExposureRecord:
    """Per-asset-class exposure tracking."""
    asset_class: str          # "NIFTY", "BANKNIFTY", "FINNIFTY", "EQUITY"
    long_exposure: float = 0.0
    short_exposure: float = 0.0
    net_exposure: float = 0.0
    gross_exposure: float = 0.0
    margin_used: float = 0.0
    pnl: float = 0.0


@dataclass
class MarginRequirement:
    """Broker-margin requirement breakdown."""
    initial_margin: float = 0.0
    exposure_margin: float = 0.0
    span_margin: float = 0.0
    premium: float = 0.0
    total: float = 0.0
    available_cash: float = 0.0


@dataclass
class StrategyBudget:
    """Capital budget allocated to a single strategy."""
    strategy_id: str
    allocated_capital: float
    used_capital: float = 0.0
    max_positions: int = 5
    current_positions: int = 0
    max_risk_per_trade_pct: float = 2.0
    daily_loss_limit: float = 0.0
    is_active: bool = True

    @property
    def available_capital(self) -> float:
        return self.allocated_capital - self.used_capital

    @property
    def utilization_pct(self) -> float:
        if self.allocated_capital <= 0:
            return 0.0
        return (self.used_capital / self.allocated_capital) * 100.0


# Export all models
__all__ = [
    "PositionSnapshot",
    "PortfolioSnapshot",
    "PortfolioPerformance",
    "ExposureRecord",
    "MarginRequirement",
    "StrategyBudget",
]
