"""
Risk Management Port Interface

This interface defines the contract that all risk management implementations must implement.
It provides a unified way to evaluate trading signals, validate position sizes, and manage
portfolio-level risk exposure.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class RiskDecision(Enum):
    """Risk evaluation decision."""
    ALLOWED = "allowed"
    DENIED = "denied"


@dataclass
class RiskEvaluation:
    """Result of a risk evaluation."""
    decision: RiskDecision
    reason: str
    recommended_position_size: int | None = None
    max_allowed_position_size: int | None = None
    risk_score: float = 0.0  # 0.0 to 1.0, where 1.0 is maximum risk
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class PositionSizingInput:
    """Input parameters for position sizing calculations."""
    symbol: str
    entry_price: float
    stop_loss_price: float
    capital_available: float
    risk_per_trade: float  # Percentage of capital to risk (e.g., 0.02 for 2%)
    lot_size: int
    volatility: float | None = None  # For volatility-adjusted sizing
    margin_required: float | None = None  # Margin required per lot
    existing_exposure: float = 0.0  # Current exposure to this symbol/related symbols


@dataclass
class PortfolioRiskMetrics:
    """Current portfolio risk metrics."""
    total_capital: float
    used_capital: float
    available_capital: float
    daily_pnl: float
    max_daily_loss: float
    current_drawdown: float
    max_drawdown: float
    open_positions_count: int
    max_open_positions: int
    consecutive_losses: int
    max_consecutive_losses: int
    sector_exposure: dict[str, float]  # Sector -> exposure amount
    symbol_exposure: dict[str, float]  # Symbol -> exposure amount


class RiskPort(ABC):
    """
    Abstract base class for risk management services.

    All risk management implementations must inherit from this class
    and implement the required methods.
    """

    @abstractmethod
    def evaluate_trade(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        portfolio_metrics: PortfolioRiskMetrics
    ) -> RiskEvaluation:
        """
        Evaluate whether a trade should be allowed based on risk parameters.

        Args:
            symbol: Trading symbol
            signal_data: Signal information (direction, strength, price, etc.)
            portfolio_metrics: Current portfolio risk metrics

        Returns:
            RiskEvaluation indicating whether the trade is allowed and any constraints
        """

    @abstractmethod
    def calculate_position_size(
        self,
        sizing_input: PositionSizingInput
    ) -> int:
        """
        Calculate the appropriate position size for a trade.

        Args:
            sizing_input: Input parameters for position sizing

        Returns:
            Number of lots/contracts to trade
        """

    @abstractmethod
    def validate_margin_requirements(
        self,
        symbol: str,
        quantity: int,
        capital_available: float
    ) -> bool:
        """
        Validate that sufficient margin is available for a position.

        Args:
            symbol: Trading symbol
            quantity: Position size in lots
            capital_available: Available capital

        Returns:
            True if margin requirements are satisfied, False otherwise
        """

    @abstractmethod
    def get_portfolio_risk_metrics(self) -> PortfolioRiskMetrics:
        """
        Get current portfolio risk metrics.

        Returns:
            PortfolioRiskMetrics object with current risk statistics
        """

    @abstractmethod
    def update_position(
        self,
        symbol: str,
        quantity: int,
        entry_price: float,
        timestamp: datetime
    ) -> None:
        """
        Update risk tracking with a new or modified position.

        Args:
            symbol: Trading symbol
            quantity: Position size (positive for long, negative for short)
            entry_price: Entry price per share/lot
            timestamp: Time of the position update
        """

    @abstractmethod
    def remove_position(self, symbol: str) -> None:
        """
        Remove a position from risk tracking.

        Args:
            symbol: Trading symbol to remove
        """

    @abstractmethod
    def reset_daily_metrics(self) -> None:
        """Reset daily risk metrics (called at start of new trading day)."""

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the risk management service.

        Returns:
            Dictionary containing health check results
        """

    # ── Trading Policy Gates (consolidated from ProductionMandateEnforcer) ──

    @abstractmethod
    def is_in_trading_window(self) -> bool:
        """Check if current time is within NSE trading windows (9:20-11:30, 13:00-14:45)."""

    @abstractmethod
    def should_skip_first_20_min(self) -> bool:
        """Skip first 20 minutes after market open (9:20-9:40)."""

    @abstractmethod
    def should_skip_last_45_min(self) -> bool:
        """Skip last 45 minutes before market close (14:35-15:20)."""

    @abstractmethod
    def get_min_score_for_regime(self, regime: str) -> int:
        """Get minimum signal score required for a given market regime."""

    @abstractmethod
    def should_block_false_signal(self, score: int, iv_rank: float) -> bool:
        """Check whether a high-score signal with elevated IV should be blocked as false."""

    @abstractmethod
    def get_max_trades_per_day(self, vix: float | None = None, consecutive_losses: int = 0) -> int:
        """Get maximum trades allowed per day, adjusted for VIX and loss streak."""

    @abstractmethod
    def get_live_vix(self) -> float:
        """Get current India VIX for real-time risk adjustment."""


__all__ = [
    "PortfolioRiskMetrics",
    "PositionSizingInput",
    "RiskDecision",
    "RiskEvaluation",
    "RiskPort",
]

