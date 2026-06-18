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


class BrokerTimeoutError(BrokerException):
    """Broker API call exceeded configured timeout."""


class BrokerConnectionError(BrokerException):
    """Network-level connection refused / DNS failure."""


class BrokerAuthError(BrokerException):
    """Authentication token expired, invalid, or rejected."""


class BrokerRejectedError(BrokerException):
    """Order explicitly rejected by the broker (insufficient margin, bad symbol, etc.)."""


class BrokerRateLimitError(BrokerException):
    """Broker API rate limit exceeded."""


# ── Risk ──────────────────────────────────────────────────────────────────────

class RiskException(TradingException):
    """Base for risk engine violations."""


class RiskLimitError(RiskException):
    """MAX_DAILY_LOSS, MAX_DRAWDOWN, or PORTFOLIO_MAX_SL_RISK_PCT breached."""


class MaxDrawdownError(RiskException):
    """Portfolio drawdown exceeded configured limit."""


class HardHaltError(RiskException):
    """Hard halt is active - all entries blocked."""


class PositionSizingError(RiskException):
    """Invalid or out-of-range position size calculated."""


class CorrelationGuardError(RiskException):
    """Cross-index correlation guard blocked simultaneous entries."""


# ── Validation ────────────────────────────────────────────────────────────────

class ValidationError(TradingException):
    """Input or state validation failure."""


# ── Reconciliation ────────────────────────────────────────────────────────────

class ReconciliationError(TradingException):
    """State mismatch, orphan orders, or reconciliation failure."""


# ── Persistence ───────────────────────────────────────────────────────────────

class PersistenceError(TradingException):
    """Base for DB / file I/O failures."""


class DatabaseError(PersistenceError):
    """SQLite connection or query error."""


class StateFileError(PersistenceError):
    """trader_state.json read or write failure."""


# ── Config ────────────────────────────────────────────────────────────────────

class ConfigError(TradingException):
    """Config loading, validation, or merge failure."""


# ── Signal ────────────────────────────────────────────────────────────────────

class SignalError(TradingException):
    """Signal generation or scoring pipeline failure."""


# ── Market Data ───────────────────────────────────────────────────────────────

class MarketDataError(TradingException):
    """Base for data feed failures."""


class StaleDataError(MarketDataError):
    """Data older than configured freshness threshold."""


class FeedDisconnectedError(MarketDataError):
    """WebSocket or API feed is disconnected."""


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class CircuitBreakerError(TradingException):
    """Circuit breaker is OPEN - operations blocked."""


# ── Execution ─────────────────────────────────────────────────────────────────

class ExecutionError(TradingException):
    """Base for order execution failures."""


class IdempotencyError(ExecutionError):
    """Duplicate order detected via idempotency check."""


class FillError(ExecutionError):
    """Fill verification failed - quantity or price mismatch."""


# ── Chaos ─────────────────────────────────────────────────────────────────────

class ChaosError(TradingException):
    """Chaos injection or verification failure."""


# ── Governance ────────────────────────────────────────────────────────────────

class GovernanceError(TradingException):
    """Constitution validation or AI safety gate violation."""


# ── Graceful degradation helpers ──────────────────────────────────────────────

def safe_fallback(value: Any, default: Any = None) -> Any:
    """Return value if truthy, else default - for optional-feature wrappers."""
    return value if value is not None else default
