"""
Broker ACK Schema Validation (Phase 0).

Validates broker order acknowledgments to ensure:
- Order ID is present and valid
- Status is recognized
- No malformed data from broker
- Required fields are present
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class BrokerType(str, Enum):
    KITE = "KITE"
    ANGEL = "ANGEL"
    PAPER = "PAPER"
    UNKNOWN = "UNKNOWN"


VALID_BROKER_STATUSES = {
    "COMPLETE", "FILLED", "REJECTED", "CANCELLED",
    "OPEN", "PENDING", "TRIGGER PENDING", "PARTIALLY FILLED",
    "UNKNOWN", "SUBMITTED"
}

REQUIRED_ACK_FIELDS = {
    BrokerType.KITE: ["order_id", "status"],
    BrokerType.ANGEL: ["order_id", "status"],
    BrokerType.PAPER: ["order_id", "status"],
    BrokerType.UNKNOWN: ["order_id", "status"],
}


@dataclass
class AckValidationResult:
    is_valid: bool
    broker: BrokerType
    order_id: str | None = None
    status: str | None = None
    error_message: str | None = None
    warnings: list[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class BrokerAckValidator:
    """
    Validates broker acknowledgments against expected schema.

    Prevents:
    - Processing malformed order IDs
    - Accepting unknown statuses
    - Silent failures from broker
    - Missing required fields
    """

    def __init__(self, broker_type: BrokerType = BrokerType.UNKNOWN):
        self._broker_type = broker_type

    @staticmethod
    def detect_broker_type(broker_adapter: Any) -> BrokerType:
        """Detect broker type from adapter class name."""
        if broker_adapter is None:
            return BrokerType.UNKNOWN
        class_name = broker_adapter.__class__.__name__.upper()
        if "KITE" in class_name:
            return BrokerType.KITE
        if "ANGEL" in class_name or "SMART" in class_name:
            return BrokerType.ANGEL
        if "PAPER" in class_name:
            return BrokerType.PAPER
        return BrokerType.UNKNOWN

    @staticmethod
    def validate_order_id(order_id: Any) -> tuple[bool, str | None]:
        """Validate order ID is non-empty string. Returns (is_valid, error_message)."""
        if order_id is None:
            return False, "order_id is None"
        if not isinstance(order_id, str):
            return False, f"order_id is {type(order_id).__name__}, not str"
        if not order_id.strip():
            return False, "order_id is empty"
        return True, None

    @staticmethod
    def validate_status(status: Any) -> tuple[bool, str | None, bool]:
        """Validate status is recognized. Returns (is_valid, error_message, is_terminal)."""
        if status is None:
            return False, "status is None", False
        if not isinstance(status, str):
            return False, f"status is {type(status).__name__}", False
        status_upper = status.upper()
        is_terminal = status_upper in ("COMPLETE", "FILLED", "REJECTED", "CANCELLED", "UNKNOWN")
        if status_upper not in VALID_BROKER_STATUSES:
            log.warning(f"Broker ACK: unknown status '{status}' - treating as UNKNOWN")
            return True, f"Unknown status: {status}", is_terminal
        return True, None, is_terminal

    @staticmethod
    def validate_fill_price(price: Any) -> tuple[bool, str | None]:
        """Validate fill price is numeric and positive if present."""
        if price is None:
            return True, None
        try:
            price_float = float(price)
            if price_float < 0:
                return False, f"negative fill price: {price_float}"
            if price_float == 0 and price != 0:
                return False, "zero fill price for non-zero input"
            return True, None
        except (ValueError, TypeError):
            return False, f"fill_price not numeric: {price}"

    @staticmethod
    def validate_quantity(qty: Any) -> tuple[bool, str | None]:
        """Validate quantity is non-negative integer."""
        if qty is None:
            return True, None
        try:
            qty_int = int(qty)
            if qty_int < 0:
                return False, f"negative quantity: {qty_int}"
            return True, None
        except (ValueError, TypeError):
            return False, f"quantity not int: {qty}"

    def validate_acknowledgment(
        self,
        acknowledgment: dict[str, Any],
        broker_type: BrokerType | None = None,
    ) -> AckValidationResult:
        """
        Validate complete broker acknowledgment.

        Args:
            acknowledgment: Dict with keys like order_id, status, fill_price, quantity
            broker_type: Optional override for broker type detection

        Returns:
            AckValidationResult with validation details
        """
        broker = broker_type or self._broker_type
        required_fields = REQUIRED_ACK_FIELDS.get(broker, REQUIRED_ACK_FIELDS[BrokerType.UNKNOWN])
        warnings = []

        missing_fields = [f for f in required_fields if f not in acknowledgment or acknowledgment[f] is None]
        if missing_fields:
            return AckValidationResult(
                is_valid=False,
                broker=broker,
                error_message=f"Missing required fields: {missing_fields}",
            )

        valid, error = self.validate_order_id(acknowledgment.get("order_id"))
        if not valid:
            return AckValidationResult(is_valid=False, broker=broker, error_message=error)

        order_id = acknowledgment.get("order_id")
        if isinstance(order_id, str) and len(order_id) < 3:
            warnings.append(f"Order ID suspiciously short: '{order_id}'")

        valid, error, _is_terminal = self.validate_status(acknowledgment.get("status"))
        if not valid:
            return AckValidationResult(is_valid=False, broker=broker, order_id=order_id, error_message=error)

        status = acknowledgment.get("status")
        valid, error = self.validate_fill_price(acknowledgment.get("fill_price"))
        if not valid:
            return AckValidationResult(is_valid=False, broker=broker, order_id=order_id, status=status, error_message=error)

        valid, error = self.validate_quantity(acknowledgment.get("quantity"))
        if not valid:
            return AckValidationResult(is_valid=False, broker=broker, order_id=order_id, status=status, error_message=error)

        return AckValidationResult(
            is_valid=True,
            broker=broker,
            order_id=order_id,
            status=status,
            warnings=warnings,
        )

    def validate_order_result(self, order_result: Any, broker_type: BrokerType | None = None) -> AckValidationResult:
        """Validate OrderResult object from execution service."""
        if order_result is None:
            return AckValidationResult(
                is_valid=False,
                broker=broker_type or self._broker_type,
                error_message="OrderResult is None",
            )

        status_val = getattr(order_result, "status", None)
        # Normalize Enum status values to strings for validation
        if isinstance(status_val, Enum):
            status_val = status_val.value

        acknowledgment = {
            "order_id": getattr(order_result, "order_id", None),
            "status": status_val,
            "fill_price": getattr(order_result, "average_price", None),
            "quantity": getattr(order_result, "filled_quantity", None),
        }

        return self.validate_acknowledgment(acknowledgment, broker_type)


def validate_broker_ack(acknowledgment: dict[str, Any], broker_type: BrokerType = BrokerType.UNKNOWN) -> AckValidationResult:
    """Convenience function for validation."""
    validator = BrokerAckValidator(broker_type)
    return validator.validate_acknowledgment(acknowledgment, broker_type)
