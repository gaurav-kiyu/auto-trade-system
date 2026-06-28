"""
Risk Management Domain Models - Clean Architecture Implementation

This module contains the domain models and value objects for the risk management service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.datetime_ist import now_ist


class RiskError(Exception):
    """Custom exception for risk management errors."""


@dataclass
class RiskLimits:
    """Risk limit configuration."""
    max_position_size: int = 100
    max_daily_loss: float = 1000.0  # INR
    max_drawdown: float = 0.20      # 20%
    max_consecutive_losses: int = 5
    max_portfolio_exposure: float = 0.80  # 80%
    max_volatility: float = 0.50    # 50%
    max_liquidity_size: int = 500
    max_correlation: float = 0.70
    max_open_positions: int = 10
    target_volatility: float = 0.20  # 20%
    use_kelly_sizing: bool = True
    kelly_fraction: float = 0.5      # Half-Kelly
    min_position_size: int = 1
    account_equity: float = 100000.0
    max_portfolio_risk_score: float = 0.8  # 80% max portfolio risk


@dataclass
class RiskDecision:
    """Result of risk evaluation."""
    allowed: bool
    reason: str = ""
    suggested_size: int = 0
    risk_metrics: dict[str, Any] | None = None


@dataclass
class Position:
    """Trading position."""
    symbol: str
    quantity: int  # Positive for long, negative for short
    average_price: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    timestamp: datetime = None
    direction: str = field(init=False)

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = now_ist()
        # Set direction based on quantity
        self.direction = "LONG" if self.quantity > 0 else "SHORT" if self.quantity < 0 else "NEUTRAL"


@dataclass
class MarketConditions:
    """Current market conditions."""
    volatility: float = 0.0
    liquidity: str = "NORMAL"  # HIGH, NORMAL, LOW
    trend: str = "NEUTRAL"     # BULLISH, BEARISH, NEUTRAL
    volume_profile: str = "NORMAL"  # HIGH, NORMAL, LOW


@dataclass
class PortfolioRiskMetrics:
    """Portfolio risk metrics."""
    total_exposure: float
    net_value: float
    concentration_risk: float
    volatility: float
    drawdown: float
    value_at_risk_95: float
    timestamp: datetime = field(default_factory=datetime.now)


# Value objects
@dataclass(frozen=True)
class PriceLevel:
    """Immutable price level."""
    price: float
    timestamp: datetime


@dataclass(frozen=True)
class VolumeProfile:
    """Immutable volume profile."""
    volume_node: float
    price_level: PriceLevel
    timestamp: datetime


@dataclass(frozen=True)
class HistoricalStats:
    """Immutable historical statistics for Kelly calculation."""
    win_rate: float
    avg_win: float
    avg_loss: float
    sample_size: int


__all__ = [
    "HistoricalStats",
    "MarketConditions",
    "PortfolioRiskMetrics",
    "Position",
    "PriceLevel",
    "RiskDecision",
    "RiskError",
    "RiskLimits",
    "VolumeProfile",
]

