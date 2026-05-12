"""
Strategy Domain Models

This module contains the data models used in the strategy domain,
including trading decisions and signal processing results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class StrategyDecision:
    """
    Represents a decision made by a trading strategy.

    Attributes:
        should_trade: Whether the strategy recommends taking a trade
        direction: Trade direction ("BUY" or "SELL")
        suggested_size: Suggested position size/quantity
        reason: Explanation for the decision
        strategy_name: Name of the strategy that made this decision
        metadata: Additional context-specific data
        timestamp: When the decision was made
    """
    should_trade: bool
    direction: str
    suggested_size: int
    reason: str
    strategy_name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Validate the decision after initialization."""
        if self.direction not in ["BUY", "SELL"]:
            raise ValueError(f"Direction must be 'BUY' or 'SELL', got {self.direction}")

        if self.suggested_size < 0:
            raise ValueError(f"Suggested size must be non-negative, got {self.suggested_size}")


@dataclass
class SignalStrength:
    """
    Represents the strength and quality of a trading signal.

    Attributes:
        value: Numerical signal strength (0.0 to 1.0)
        quality: Qualitative assessment of signal quality
        confidence: Confidence level in the signal (0.0 to 1.0)
    """
    value: float
    quality: str  # Could be "WEAK", "MODERATE", "STRONG"
    confidence: float = 0.0

    def __post_init__(self):
        """Validate signal strength after initialization."""
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"Signal value must be between 0.0 and 1.0, got {self.value}")

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Signal confidence must be between 0.0 and 1.0, got {self.confidence}")

        valid_qualities = ["WEAK", "MODERATE", "STRONG"]
        if self.quality not in valid_qualities:
            raise ValueError(f"Quality must be one of {valid_qualities}, got {self.quality}")


@dataclass
class StrategyConfig:
    """
    Configuration for a trading strategy.

    Attributes:
        name: Strategy name
        enabled: Whether the strategy is active
        parameters: Strategy-specific parameters
        risk_limits: Risk parameters for this strategy
    """
    name: str
    enabled: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)
    risk_limits: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate strategy configuration after initialization."""
        if not self.name:
            raise ValueError("Strategy name cannot be empty")
