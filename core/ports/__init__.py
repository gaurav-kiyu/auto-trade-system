"""Ports Package - Hexagonal Architecture Port Interfaces.

All port interfaces that define contracts between the core domain and
external adapters. Each sub-package defines a specific port boundary.

Port Sub-Packages:
  - broker       : Broker adapter interface (Kite, Angel, etc.)
  - circuit_breaker : Circuit breaker pattern interface
  - config       : Configuration provider interface
  - execution    : Order execution interface
  - ml_model     : ML model prediction interface
  - notification : Notification dispatch interface
  - persistence  : Database/storage interface
  - rate_limiting: Rate limiting interface
  - risk         : Risk evaluation interface
  - strategy     : Strategy decision interface

Direct Port Modules:
  - correlation_id : Correlation ID management (abstract port)
  - logging      : Logging service abstraction
  - market_data  : Market data provider interface
  - metrics      : Metrics collection interface

Usage:
    from core.ports import BrokerPort, RiskPort, ConfigPort
    from core.ports import MarketDataPort, MetricsPort, LoggingPort
"""

from __future__ import annotations

# ── Sub-package architectures ────────────────────────────────────────────
from core.ports.broker import (
    BrokerAuthStatus,
    BrokerCapability,
    BrokerCredentials,
    BrokerHealthPort,
    BrokerOrderRequest,
    BrokerPort,
    Exchange,
    Fill,
    Holding,
    LegacyBrokerPort,
    LegacyFill,
    LegacyOrderResult,
    LegacyOrderStatus,
    LegacyPosition,
    LegacyQuote,
    Margin,
    Order,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    OrderVariety,
    Position,
    PositionDirection,
    ProductType,
    Quote,
    Trade,
)

# ── Capital Allocation (multi-asset) ─────────────────────────────────────
from core.ports.capital_allocation import (
    AllocationRequest,
    AllocationResult,
    AssetClass,
    CapitalAllocationPort,
)
from core.ports.circuit_breaker import CircuitBreakerPort
from core.ports.config import ConfigPort

# ── Direct module port interfaces ────────────────────────────────────────
from core.ports.correlation_id import CorrelationIdPort
from core.ports.execution import ExecutionPort
from core.ports.logging import LoggingPort
from core.ports.market_data import MarketDataAdapterFactory, MarketDataPort
from core.ports.metrics import MetricsPort
from core.ports.ml_model import MlModelPort, MLPrediction
from core.ports.notification import NotificationPort
from core.ports.persistence import PersistencePort
from core.ports.rate_limiting import RateLimitPort
from core.ports.risk import RiskPort

# ── Risk port types (shared with domain models) ──────────────────────────
from core.ports.risk.risk_port import (
    PortfolioRiskMetrics,
    PositionSizingInput,
    RiskEvaluation,
)
from core.ports.risk.risk_port import (
    RiskDecision as RiskPortDecision,
)
from core.ports.strategy import StrategyDecision, StrategyPort

__all__ = [
    # Broker
    "BrokerAuthStatus",
    "BrokerCapability",
    "BrokerCredentials",
    "BrokerHealthPort",
    "BrokerOrderRequest",
    "BrokerPort",
    "Exchange",
    "Fill",
    "Holding",
    "LegacyBrokerPort",
    "LegacyFill",
    "LegacyOrderResult",
    "LegacyOrderStatus",
    "LegacyPosition",
    "LegacyQuote",
    "Margin",
    "Order",
    "OrderRequest",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "OrderVariety",
    "Position",
    "PositionDirection",
    "ProductType",
    "Quote",
    "Trade",
    # Circuit Breaker
    "CircuitBreakerPort",
    # Config
    "ConfigPort",
    # Correlation ID
    "CorrelationIdPort",
    # Execution
    "ExecutionPort",
    # Logging
    "LoggingPort",
    # ML Model
    "MLPrediction",
    "MlModelPort",
    # Market Data
    "MarketDataAdapterFactory",
    "MarketDataPort",
    # Capital Allocation
    "AllocationRequest",
    "AllocationResult",
    "AssetClass",
    "CapitalAllocationPort",
    # Metrics
    "MetricsPort",
    # Notification
    "NotificationPort",
    # Persistence
    "PersistencePort",
    # Rate Limiting
    "RateLimitPort",
    # Risk
    "PositionSizingInput",
    "RiskPort",
    "RiskPortDecision",
    "RiskEvaluation",
    "PortfolioRiskMetrics",
    # Strategy
    "StrategyDecision",
    "StrategyPort",
]
