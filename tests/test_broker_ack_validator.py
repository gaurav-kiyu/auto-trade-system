"""
Tests for core/execution/broker_ack_validator.py - BrokerAckValidator.

Covers:
  - BrokerType enum values
  - AckValidationResult dataclass
  - detect_broker_type (Kite, Angel, Paper, Unknown, None)
  - validate_order_id (None, non-string, empty, valid)
  - validate_status (None, non-string, known, unknown, terminal detection)
  - validate_fill_price (None, valid, negative, zero, non-numeric)
  - validate_quantity (None, valid, negative, non-int)
  - validate_acknowledgment (missing fields, valid, warnings for short ID)
  - validate_order_result (None, OrderResult with Enum status)
  - Convenience function validate_broker_ack
"""

from __future__ import annotations



from core.execution.broker_ack_validator import (
    AckValidationResult,
    BrokerAckValidator,
    BrokerType,
    VALID_BROKER_STATUSES,
    validate_broker_ack,
)
from core.ports.execution.execution_port import OrderResult, OrderStatus


class TestBrokerType:
    def test_values(self):
        assert BrokerType.KITE == "KITE"
        assert BrokerType.ANGEL == "ANGEL"
        assert BrokerType.PAPER == "PAPER"
        assert BrokerType.UNKNOWN == "UNKNOWN"


class TestAckValidationResult:
    def test_default_warnings_list(self):
        result = AckValidationResult(is_valid=True, broker=BrokerType.PAPER)
        assert result.warnings == []

    def test_custom_warnings(self):
        result = AckValidationResult(
            is_valid=True, broker=BrokerType.KITE, warnings=["Short ID"]
        )
        assert result.warnings == ["Short ID"]


class TestDetectBrokerType:
    def test_kite_broker(self):
        class KiteAdapter:
            pass
        result = BrokerAckValidator.detect_broker_type(KiteAdapter())
        assert result == BrokerType.KITE

    def test_angel_broker(self):
        class AngelAdapter:
            pass
        result = BrokerAckValidator.detect_broker_type(AngelAdapter())
        assert result == BrokerType.ANGEL

    def test_smart_broker(self):
        class SmartApiAdapter:
            pass
        result = BrokerAckValidator.detect_broker_type(SmartApiAdapter())
        assert result == BrokerType.ANGEL

    def test_paper_broker(self):
        class PaperBrokerAdapter:
            pass
        result = BrokerAckValidator.detect_broker_type(PaperBrokerAdapter())
        assert result == BrokerType.PAPER

    def test_unknown_broker(self):
        class CustomAdapter:
            pass
        result = BrokerAckValidator.detect_broker_type(CustomAdapter())
        assert result == BrokerType.UNKNOWN

    def test_none_adapter(self):
        result = BrokerAckValidator.detect_broker_type(None)
        assert result == BrokerType.UNKNOWN


class TestValidateOrderId:
    def test_none(self):
        valid, error = BrokerAckValidator.validate_order_id(None)
        assert valid is False
        assert "None" in error

    def test_non_string(self):
        valid, error = BrokerAckValidator.validate_order_id(12345)
        assert valid is False
        assert "not str" in error

    def test_empty_string(self):
        valid, error = BrokerAckValidator.validate_order_id("")
        assert valid is False
        assert "empty" in error

    def test_whitespace_only(self):
        valid, error = BrokerAckValidator.validate_order_id("   ")
        assert valid is False
        assert "empty" in error

    def test_valid(self):
        valid, error = BrokerAckValidator.validate_order_id("ORD-001")
        assert valid is True
        assert error is None


class TestValidateStatus:
    def test_none(self):
        valid, error, is_terminal = BrokerAckValidator.validate_status(None)
        assert valid is False
        assert "None" in error
        assert is_terminal is False

    def test_non_string(self):
        valid, error, is_terminal = BrokerAckValidator.validate_status(True)
        assert valid is False

    def test_known_status(self):
        for status in ["COMPLETE", "FILLED", "REJECTED", "CANCELLED", "OPEN", "PENDING", "SUBMITTED"]:
            valid, error, is_terminal = BrokerAckValidator.validate_status(status)
            assert valid is True
            assert error is None

    def test_terminal_detection(self):
        for status in ["COMPLETE", "FILLED", "REJECTED", "CANCELLED"]:
            _, _, is_terminal = BrokerAckValidator.validate_status(status)
            assert is_terminal is True

    def test_non_terminal(self):
        for status in ["OPEN", "PENDING", "SUBMITTED"]:
            _, _, is_terminal = BrokerAckValidator.validate_status(status)
            assert is_terminal is False

    def test_unknown_status(self):
        valid, error, is_terminal = BrokerAckValidator.validate_status("BOGUS")
        assert valid is True  # Unknown status is accepted with warning
        assert "Unknown" in error


class TestValidateFillPrice:
    def test_none(self):
        valid, error = BrokerAckValidator.validate_fill_price(None)
        assert valid is True

    def test_positive(self):
        valid, error = BrokerAckValidator.validate_fill_price(23500.0)
        assert valid is True

    def test_negative(self):
        valid, error = BrokerAckValidator.validate_fill_price(-100.0)
        assert valid is False
        assert "negative" in error

    def test_zero(self):
        valid, error = BrokerAckValidator.validate_fill_price(0)
        assert valid is True  # Zero is allowed

    def test_non_numeric(self):
        valid, error = BrokerAckValidator.validate_fill_price("abc")
        assert valid is False
        assert "not numeric" in error


class TestValidateQuantity:
    def test_none(self):
        valid, error = BrokerAckValidator.validate_quantity(None)
        assert valid is True

    def test_positive(self):
        valid, error = BrokerAckValidator.validate_quantity(50)
        assert valid is True

    def test_zero(self):
        valid, error = BrokerAckValidator.validate_quantity(0)
        assert valid is True

    def test_negative(self):
        valid, error = BrokerAckValidator.validate_quantity(-5)
        assert valid is False
        assert "negative" in error

    def test_non_int_string(self):
        valid, error = BrokerAckValidator.validate_quantity("fifty")
        assert valid is False
        assert "not int" in error

    def test_float_string(self):
        # "50.5" cannot be parsed as int via int("50.5") — raises ValueError
        valid, error = BrokerAckValidator.validate_quantity("50.5")
        assert valid is False
        assert "not int" in error


class TestValidateAcknowledgment:
    def test_missing_fields(self):
        validator = BrokerAckValidator(BrokerType.PAPER)
        result = validator.validate_acknowledgment({})
        assert result.is_valid is False
        assert "Missing required fields" in result.error_message

    def test_invalid_order_id(self):
        validator = BrokerAckValidator(BrokerType.PAPER)
        result = validator.validate_acknowledgment({"order_id": 123, "status": "FILLED"})
        assert result.is_valid is False
        assert "not str" in result.error_message

    def test_invalid_status(self):
        validator = BrokerAckValidator(BrokerType.PAPER)
        result = validator.validate_acknowledgment({"order_id": "ORD-001", "status": None})
        assert result.is_valid is False

    def test_valid_acknowledgment(self):
        validator = BrokerAckValidator(BrokerType.PAPER)
        result = validator.validate_acknowledgment({
            "order_id": "ORD-001",
            "status": "FILLED",
            "fill_price": 23500.0,
            "quantity": 50,
        })
        assert result.is_valid is True
        assert result.order_id == "ORD-001"
        assert result.status == "FILLED"
        assert result.warnings == []

    def test_short_order_id_warning(self):
        validator = BrokerAckValidator(BrokerType.PAPER)
        result = validator.validate_acknowledgment({
            "order_id": "AB",
            "status": "FILLED",
        })
        assert result.is_valid is True
        assert len(result.warnings) >= 1
        assert "short" in result.warnings[0].lower()

    def test_negative_fill_price(self):
        validator = BrokerAckValidator(BrokerType.PAPER)
        result = validator.validate_acknowledgment({
            "order_id": "ORD-001",
            "status": "FILLED",
            "fill_price": -100.0,
        })
        assert result.is_valid is False
        assert "negative" in result.error_message

    def test_negative_quantity(self):
        validator = BrokerAckValidator(BrokerType.PAPER)
        result = validator.validate_acknowledgment({
            "order_id": "ORD-001",
            "status": "FILLED",
            "quantity": -5,
        })
        assert result.is_valid is False
        assert "negative" in result.error_message

    def test_overrides_broker_type(self):
        validator = BrokerAckValidator(BrokerType.PAPER)
        result = validator.validate_acknowledgment(
            {"order_id": "ORD-001", "status": "FILLED"},
            broker_type=BrokerType.KITE,
        )
        assert result.broker == BrokerType.KITE


class TestValidateOrderResult:
    def test_none_result(self):
        validator = BrokerAckValidator(BrokerType.PAPER)
        result = validator.validate_order_result(None)
        assert result.is_valid is False
        assert "None" in result.error_message

    def test_valid_order_result(self):
        validator = BrokerAckValidator(BrokerType.PAPER)
        order_result = OrderResult(
            order_id="ORD-001",
            status=OrderStatus.FILLED,
            filled_quantity=50,
            average_price=23500.0,
        )
        result = validator.validate_order_result(order_result)
        assert result.is_valid is True
        assert result.order_id == "ORD-001"

    def test_order_result_invalid_status(self):
        validator = BrokerAckValidator(BrokerType.PAPER)
        order_result = OrderResult(order_id="ORD-001", status=OrderStatus.PENDING)
        # PENDING is a valid status
        result = validator.validate_order_result(order_result)
        assert result.is_valid is True


class TestConvenienceFunction:
    def test_validate_broker_ack(self):
        result = validate_broker_ack(
            {"order_id": "ORD-001", "status": "FILLED"},
            BrokerType.PAPER,
        )
        assert result.is_valid is True
        assert result.broker == BrokerType.PAPER

    def test_validate_broker_ack_invalid(self):
        result = validate_broker_ack({}, BrokerType.UNKNOWN)
        assert result.is_valid is False


class TestValidBrokerStatuses:
    def test_all_expected_statuses_present(self):
        expected = {"COMPLETE", "FILLED", "REJECTED", "CANCELLED", "OPEN", "PENDING", "TRIGGER PENDING", "PARTIALLY FILLED", "UNKNOWN", "SUBMITTED"}
        assert VALID_BROKER_STATUSES == expected
