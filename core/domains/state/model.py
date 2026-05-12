"""
State Domain Models

This module contains the data models used in the state domain,
including trading state and session state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TradingState:
    """
    Represents the current state of the trading system.

    Attributes:
        timestamp: When this state was captured
        last_order: The most recent order
        last_fills: The most recent fills (list)
        last_strategy_decision: The most recent strategy decision
        last_risk_decision: The most recent risk decision
        portfolio_snapshot: Current portfolio snapshot
        metadata: Additional context-specific data
    """
    timestamp: datetime = field(default_factory=datetime.now)
    last_order: Any | None = None  # Will be Order type when imported
    last_fills: list[Any] = field(default_factory=list)  # Will be Fill type when imported
    last_strategy_decision: Any | None = None  # Will be StrategyDecision type when imported
    last_risk_decision: Any | None = None  # Will be RiskDecision type when imported
    portfolio_snapshot: Any | None = None  # Will be PortfolioSnapshot type when imported
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate trading state after initialization."""
        # We'll do light validation here - more thorough validation would require
        # importing the actual types, which we avoid to prevent circular imports
        pass


@dataclass
class SessionState:
    """
    Represents the state of a trading session.

    Attributes:
        session_id: Unique session identifier
        start_time: When the session started
        end_time: When the session ended (None if ongoing)
        is_active: Whether the session is currently active
        total_trades: Total number of trades in the session
        total_pnl: Total profit/loss for the session
        metadata: Additional context-specific data
    """
    session_id: str
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    is_active: bool = True
    total_trades: int = 0
    total_pnl: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate session state after initialization."""
        if self.end_time is not None and self.start_time > self.end_time:
            raise ValueError("Session start time must be before end time")

        if self.total_trades < 0:
            raise ValueError(f"Total trades cannot be negative, got {self.total_trades}")
