"""
Domain-Specific Exception Hierarchy (Phase 1).

Replaces bare ``except Exception`` with semantically typed catches so that
every failure is: logged, classified, escalated, recovered, and fails closed.

Usage
-----
    from core.exceptions import BrokerTimeoutError, ValidationError
    try:
        broker.place_order(...)
    except BrokerTimeoutError:
        _log.warning("Broker timeout - retrying")
        return _fallback_fill(...)


Exception Tree
--------------
TradingException                    # Base - all trading exceptions
├── BrokerException                 # Broker adapter failures
│   ├── BrokerTimeoutError          #   API call exceeded timeout
│   ├── BrokerConnectionError       #   Network / connection refused
│   ├── BrokerAuthError             #   Token expired / invalid
│   ├── BrokerRejectedError         #   Order rejected by broker
│   └── BrokerRateLimitError        #   Rate limited
├── RiskException                   # Risk engine violations
│   ├── RiskLimitError              #   MAX_DAILY_LOSS / MAX_DRAWDOWN breached
│   ├── MaxDrawdownError            #   Portfolio drawdown limit hit
│   ├── HardHaltError               #   Hard halt active
│   ├── PositionSizingError         #   Invalid position size
│   └── CorrelationGuardError       #   Cross-index correlation block
├── ValidationError                 # Input/state validation failures
├── ReconciliationError             # State mismatch / orphan orders
├── PersistenceError                # DB / file I/O failures
│   ├── DatabaseError               #   SQLite / connection errors
│   └── StateFileError              #   trader_state.json read/write
├── ConfigError                     # Config validation / loading
├── SignalError                     # Signal generation pipeline
├── MarketDataError                 # Data feed failures
│   ├── StaleDataError              #   Data older than freshness threshold
│   └── FeedDisconnectedError       #   WebSocket / API feed down
├── CircuitBreakerError             # Circuit breaker open
├── ExecutionError                  # Order execution failures
│   ├── IdempotencyError            #   Duplicate order detection
│   └── FillError                   #   Fill verification failed
├── ChaosError                      # Chaos injection failures
└── GovernanceError                 # Constitution / AI gate violations
"""

from __future__ import annotations

from typing import Any


# ── Base ──────────────────────────────────────────────────────────────────────

class TradingException(Exception):
    """Base exception for all trading system errors."""

    def __init__(self, message: str = "", *, details: dict[str, Any] | None = None):
        self.details = details or {}
        super().__init__(message)

    def classify(self) -> str:
        """Return a human-readable classification tag."""
        return type(self).__name__

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.classify(),
            "message": str(self),
            "details": self.details,
        }


# ── Broker ────────────────────────────────────────────────────────────────────

class BrokerException(TradingException):
    """Base for all broker adapter failures."""
    pass


class BrokerTimeoutError(BrokerException):
    """Broker API call exceeded configured timeout."""
    pass


class BrokerConnectionError(BrokerException):
    """Network-level connection refused / DNS failure."""
    pass


class BrokerAuthError(BrokerException):
    """Authentication token expired, invalid, or rejected."""
    pass


class BrokerRejectedError(BrokerException):
    """Order explicitly rejected by the broker (insufficient margin, bad symbol, etc.)."""
    pass


class BrokerRateLimitError(BrokerException):
    """Broker API rate limit exceeded."""
    pass


# ── Risk ──────────────────────────────────────────────────────────────────────

class RiskException(TradingException):
    """Base for risk engine violations."""
    pass


class RiskLimitError(RiskException):
    """MAX_DAILY_LOSS, MAX_DRAWDOWN, or PORTFOLIO_MAX_SL_RISK_PCT breached."""
    pass


class MaxDrawdownError(RiskException):
    """Portfolio drawdown exceeded configured limit."""
    pass


class HardHaltError(RiskException):
    """Hard halt is active - all entries blocked."""
    pass


class PositionSizingError(RiskException):
    """Invalid or out-of-range position size calculated."""
    pass


class CorrelationGuardError(RiskException):
    """Cross-index correlation guard blocked simultaneous entries."""
    pass


# ── Validation ────────────────────────────────────────────────────────────────

class ValidationError(TradingException):
    """Input or state validation failure."""
    pass


# ── Reconciliation ────────────────────────────────────────────────────────────

class ReconciliationError(TradingException):
    """State mismatch, orphan orders, or reconciliation failure."""
    pass


# ── Persistence ───────────────────────────────────────────────────────────────

class PersistenceError(TradingException):
    """Base for DB / file I/O failures."""
    pass


class DatabaseError(PersistenceError):
    """SQLite connection or query error."""
    pass


class StateFileError(PersistenceError):
    """trader_state.json read or write failure."""
    pass


# ── Config ────────────────────────────────────────────────────────────────────

class ConfigError(TradingException):
    """Config loading, validation, or merge failure."""
    pass


# ── Signal ────────────────────────────────────────────────────────────────────

class SignalError(TradingException):
    """Signal generation or scoring pipeline failure."""
    pass


# ── Market Data ───────────────────────────────────────────────────────────────

class MarketDataError(TradingException):
    """Base for data feed failures."""
    pass


class StaleDataError(MarketDataError):
    """Data older than configured freshness threshold."""
    pass


class FeedDisconnectedError(MarketDataError):
    """WebSocket or API feed is disconnected."""
    pass


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class CircuitBreakerError(TradingException):
    """Circuit breaker is OPEN - operations blocked."""
    pass


# ── Execution ─────────────────────────────────────────────────────────────────

class ExecutionError(TradingException):
    """Base for order execution failures."""
    pass


class IdempotencyError(ExecutionError):
    """Duplicate order detected via idempotency check."""
    pass


class FillError(ExecutionError):
    """Fill verification failed - quantity or price mismatch."""
    pass


# ── Chaos ─────────────────────────────────────────────────────────────────────

class ChaosError(TradingException):
    """Chaos injection or verification failure."""
    pass


# ── Governance ────────────────────────────────────────────────────────────────

class GovernanceError(TradingException):
    """Constitution validation or AI safety gate violation."""
    pass


# ── Graceful degradation helpers ──────────────────────────────────────────────

def safe_fallback(value: Any, default: Any = None) -> Any:
    """Return value if truthy, else default - for optional-feature wrappers."""
    return value if value is not None else default


__all__ = [
    "BrokerAuthError",
    "BrokerConnectionError",
    "BrokerException",
    "BrokerRateLimitError",
    "BrokerRejectedError",
    "BrokerTimeoutError",
    "ChaosError",
    "CircuitBreakerError",
    "ConfigError",
    "CorrelationGuardError",
    "DatabaseError",
    "ExecutionError",
    "FeedDisconnectedError",
    "FillError",
    "GovernanceError",
    "HardHaltError",
    "IdempotencyError",
    "MarketDataError",
    "MaxDrawdownError",
    "PersistenceError",
    "PositionSizingError",
    "ReconciliationError",
    "RiskException",
    "RiskLimitError",
    "SignalError",
    "StaleDataError",
    "StateFileError",
    "TradingException",
    "ValidationError",
    "safe_fallback",
]

