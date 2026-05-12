"""
Execution Port Interface

This interface defines the contract that all execution services must implement.
It provides a unified way to place, manage, and verify orders with support for
idempotency, duplicate prevention, and comprehensive audit trails.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class OrderType(Enum):
    """Order types supported by the execution service."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "SL"
    STOP_LOSS_MARKET = "SL-M"


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
    MANUAL = "MANUAL"
    AUTOMATIC = "AUTOMATIC"
    PAPER = "PAPER"


@dataclass
class OrderRequest:
    """Order request data model."""
    symbol: str
    direction: str  # BUY or SELL
    strike_price: float
    lot_size: int
    order_type: OrderType
    price: float | None = None  # For LIMIT orders
    stop_loss: float | None = None
    target: float | None = None
    trail_activate: bool = False
    trail_percent: float | None = None
    strategy_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    idempotency_key: str | None = None  # Unique key to prevent duplicate execution


@dataclass
class OrderResult:
    """Order execution result."""
    order_id: str
    status: OrderStatus
    filled_quantity: int = 0
    average_price: float = 0.0
    commission: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    reject_reason: str | None = None
    broker_order_id: str | None = None
    broker_timestamp: datetime | None = None


@dataclass
class ExecutionContext:
    """Context information for execution."""
    signal_id: str = ""
    signal_timestamp: datetime = field(default_factory=datetime.now)
    strategy_name: str = ""
    execution_mode: ExecutionMode = ExecutionMode.AUTOMATIC
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionAuditTrail:
    """Audit trail for execution tracking."""
    execution_id: str
    order_request: OrderRequest
    order_result: OrderResult | None = None
    execution_context: ExecutionContext = field(default_factory=ExecutionContext)
    timestamp: datetime = field(default_factory=datetime.now)
    latency_ms: int = 0
    retry_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionPort(ABC):
    """
    Abstract base class for execution services.

    All execution implementations must inherit from this class
    and implement the required methods.
    """

    @abstractmethod
    def execute_order(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext = None
    ) -> OrderResult:
        """
        Execute an order with idempotency and duplicate prevention.

        Args:
            order_request: The order to execute
            execution_context: Context information for the execution

        Returns:
            OrderResult indicating success or failure
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an existing order.

        Args:
            order_id: The order ID to cancel

        Returns:
            True if cancellation successful, False otherwise
        """
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderStatus:
        """
        Get the current status of an order.

        Args:
            order_id: The order ID to check

        Returns:
            Current order status
        """
        pass

    @abstractmethod
    def verify_order_fill(
        self,
        order_id: str,
        timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """
        Verify that an order has been filled and get fill details.

        Args:
            order_id: The order ID to verify
            timeout_seconds: Maximum time to wait for fill confirmation

        Returns:
            Dictionary containing fill verification results
        """
        pass

    @abstractmethod
    def is_duplicate_order(self, idempotency_key: str) -> bool:
        """
        Check if an order with the given idempotency key has already been processed.

        Args:
            idempotency_key: Unique key to check for duplication

        Returns:
            True if order is duplicate, False otherwise
        """
        pass

    @abstractmethod
    def record_execution_audit(
        self,
        audit_trail: ExecutionAuditTrail
    ) -> bool:
        """
        Record an execution audit trail for compliance and debugging.

        Args:
            audit_trail: The execution audit trail to record

        Returns:
            True if recording successful, False otherwise
        """
        pass

    @abstractmethod
    def get_execution_audit_trail(
        self,
        execution_id: str
    ) -> ExecutionAuditTrail | None:
        """
        Retrieve an execution audit trail by ID.

        Args:
            execution_id: The execution ID to retrieve

        Returns:
            ExecutionAuditTrail if found, None otherwise
        """
        pass

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the execution service.

        Returns:
            Dictionary containing health check results
        """
        pass
