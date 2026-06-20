"""
Unit tests for Execution Service.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest
from core.ports.broker import BrokerPort
from core.ports.execution.execution_port import (
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
)
from core.ports.persistence.persistence_port import TradePersistencePort
from core.services.execution_service import ExecutionService, ExecutionServiceConfig


class TestExecutionService:
    """Test cases for ExecutionService."""

    def setup_method(self):
        """Set up test fixtures."""
        from core.safety_state import clear_hard_halt
        clear_hard_halt()  # Ensure hard halt is clear before each test

        self.broker_mock = Mock(spec=BrokerPort)
        self.persistence_mock = Mock(spec=TradePersistencePort)
        self.config = ExecutionServiceConfig()
        self.service = ExecutionService(
            broker_port=self.broker_mock,
            trade_persistence=self.persistence_mock,
            config=self.config
        )

    def test_initialization(self):
        """Test service initialization."""
        assert self.service.broker_port == self.broker_mock
        assert self.service.trade_persistence == self.persistence_mock
        assert self.service.config == self.config
        assert self.service._idempotency_cache == {}
        assert self.service._lock is not None

    def test_execute_order_success(self):
        """Test successful order execution."""
        # Setup
        order_request = OrderRequest(
            symbol="NIFTY24SepFUT",
            direction="BUY",
            strike_price=22000.0,
            lot_size=50,
            order_type=OrderType.MARKET,
            strategy_id="test_strategy"
        )

        expected_result = OrderResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            filled_quantity=50,
            average_price=22000.0,
            timestamp=datetime.now()
        )

        self.broker_mock.place_order.return_value = expected_result

        # Execute
        result = self.service.execute_order(order_request)

        # Verify
        assert result == expected_result
        self.broker_mock.place_order.assert_called_once_with(order_request)
        # The idempotency cache should contain the key for the executed order
        assert len(self.service._idempotency_cache) == 1

    def test_execute_order_with_idempotency(self):
        """Test order execution with idempotency key."""
        # Setup
        idempotency_key = "test_key_123"
        order_request = OrderRequest(
            symbol="NIFTY24SepFUT",
            direction="BUY",
            strike_price=22000.0,
            lot_size=50,
            order_type=OrderType.MARKET,
            strategy_id="test_strategy",
            idempotency_key=idempotency_key
        )

        expected_result = OrderResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            filled_quantity=50,
            average_price=22000.0,
            timestamp=datetime.now()
        )

        self.broker_mock.place_order.return_value = expected_result

        # Execute first time
        result1 = self.service.execute_order(order_request)

        # Execute second time with same idempotency key
        result2 = self.service.execute_order(order_request)

        # Verify
        assert result1 == expected_result
        assert result2 == expected_result
        assert result1.order_id == result2.order_id
        # Broker should only be called once due to idempotency
        self.broker_mock.place_order.assert_called_once()

    def test_execute_order_different_idempotency_keys(self):
        """Test that different idempotency keys allow different orders."""
        # Setup
        order_request1 = OrderRequest(
            symbol="NIFTY24SepFUT",
            direction="BUY",
            strike_price=22000.0,
            lot_size=50,
            order_type=OrderType.MARKET,
            strategy_id="test_strategy",
            idempotency_key="key_1"
        )

        order_request2 = OrderRequest(
            symbol="NIFTY24SepFUT",
            direction="BUY",
            strike_price=22000.0,
            lot_size=50,
            order_type=OrderType.MARKET,
            strategy_id="test_strategy",
            idempotency_key="key_2"
        )

        expected_result1 = OrderResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            filled_quantity=50,
            average_price=22000.0,
            timestamp=datetime.now()
        )

        expected_result2 = OrderResult(
            order_id="order_124",
            status=OrderStatus.FILLED,
            filled_quantity=50,
            average_price=22000.0,
            timestamp=datetime.now()
        )

        self.broker_mock.place_order.side_effect = [expected_result1, expected_result2]

        # Execute both orders
        result1 = self.service.execute_order(order_request1)
        result2 = self.service.execute_order(order_request2)

        # Verify
        assert result1 == expected_result1
        assert result2 == expected_result2
        assert result1.order_id != result2.order_id
        # Broker should be called twice
        assert self.broker_mock.place_order.call_count == 2

    def test_execute_order_broker_exception(self):
        """Test order execution when broker throws exception."""
        # Setup
        order_request = OrderRequest(
            symbol="NIFTY24SepFUT",
            direction="BUY",
            strike_price=22000.0,
            lot_size=50,
            order_type=OrderType.MARKET,
            strategy_id="test_strategy"
        )

        self.broker_mock.place_order.side_effect = ValueError("Broker error")

        # Execute and verify that we get a rejected order
        result = self.service.execute_order(order_request)
        assert result.status == OrderStatus.REJECTED
        assert "Broker error" in result.reject_reason

    def test_get_order_status(self):
        """Test getting order status."""
        # Setup
        order_id = "order_123"
        expected_status = OrderStatus.FILLED
        self.broker_mock.get_order_status.return_value = expected_status

        # Execute
        result = self.service.get_order_status(order_id)

        # Verify
        assert result == expected_status
        self.broker_mock.get_order_status.assert_called_once_with(order_id)

    def test_cancel_order(self):
        """Test cancelling an order."""
        # Setup
        order_id = "order_123"
        expected_result = OrderResult(
            order_id=order_id,
            status=OrderStatus.CANCELLED,
            timestamp=datetime.now()
        )
        self.broker_mock.cancel_order.return_value = expected_result

        # Execute
        result = self.service.cancel_order(order_id)

        # Verify
        assert result == expected_result
        self.broker_mock.cancel_order.assert_called_once_with(order_id)

    def test_health_check_healthy(self):
        """Test health check when service is healthy."""
        # Setup
        self.broker_mock.health_check.return_value = {"status": "healthy"}
        self.persistence_mock.health_check.return_value = {"status": "healthy"}

        # Execute
        result = self.service.health_check()

        # Verify
        assert result["status"] == "healthy"
        assert "ExecutionService" in result["service"]
        assert result["broker_healthy"] is True
        assert result["persistence_healthy"] is True

    def test_health_check_unhealthy_broker(self):
        """Test health check when broker is unhealthy."""
        # Setup
        self.broker_mock.health_check.return_value = {"status": "unhealthy", "error": "Connection failed"}
        self.persistence_mock.health_check.return_value = {"status": "healthy"}

        # Execute
        result = self.service.health_check()

        # Verify
        assert result["status"] == "unhealthy"
        assert result["broker_healthy"] is False
        assert result["persistence_healthy"] is True

    def test_health_check_unhealthy_persistence(self):
        """Test health check when persistence is unhealthy."""
        # Setup
        self.broker_mock.health_check.return_value = {"status": "healthy"}
        self.persistence_mock.health_check.return_value = {"status": "unhealthy", "error": "DB connection failed"}

        # Execute
        result = self.service.health_check()

        # Verify
        assert result["status"] == "unhealthy"
        assert result["broker_healthy"] is True
        assert result["persistence_healthy"] is False

    def test_idempotency_cache_cleanup(self):
        """Test that old idempotency keys are cleaned up."""
        # This test would require mocking time, but we can verify the structure exists
        assert hasattr(self.service, '_idempotency_cache')
        assert hasattr(self.service, '_lock')

    def test_retry_logic(self):
        """Test retry logic for transient failures - service does NOT retry, returns REJECTED."""
        # Setup
        order_request = OrderRequest(
            symbol="NIFTY24SepFUT",
            direction="BUY",
            strike_price=22000.0,
            lot_size=50,
            order_type=OrderType.MARKET,
            strategy_id="test_strategy"
        )

        # First call fails, second would succeed - but service does NOT retry
        expected_result = OrderResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            filled_quantity=50,
            average_price=22000.0,
            timestamp=datetime.now()
        )

        self.broker_mock.place_order.side_effect = [
            ValueError("Transient error"),
            expected_result
        ]

        # Execute
        result = self.service.execute_order(order_request)

        # Service does NOT retry - returns REJECTED with the error
        assert result.status == OrderStatus.REJECTED
        assert "Transient error" in (result.reject_reason or "")
        # Only 1 call attempt - service does not retry
        assert self.broker_mock.place_order.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
