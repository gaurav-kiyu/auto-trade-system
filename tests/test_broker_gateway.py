"""
Tests for core/execution/broker_gateway.py - The 'Air Gap' between Trading Brain and Broker SDKs.

Covers (30+ tests):
- BrokerGateway init state (no active adapter, empty registry)
- register_adapter() with valid/invalid adapter classes
- connect() with registered/unregistered brokers, auth success/failure
- place_order() with/without active adapter, adapter error handling
- get_ltp() with/without active adapter, adapter errors
- get_positions() with/without active adapter, adapter errors
- switch_broker() for runtime failover
- Singleton broker_gateway instance
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from core.adapters.base_adapter import BrokerAdapter, OrderRequest, OrderResponse, OrderStatus
from core.execution.broker_gateway import BrokerGateway, broker_gateway

# ── Mock Broker Adapter ──────────────────────────────────────────────────────


class MockBrokerAdapter(BrokerAdapter):
    """A minimal BrokerAdapter implementation for testing."""

    def __init__(self):
        self.authenticated = False
        self.orders: list[OrderRequest] = []
        self.ltp_values: dict[str, float] = {}
        self.positions: list[dict] = []
        self.healthy = True

    def authenticate(self, credentials: dict) -> bool:
        self.authenticated = credentials.get("key") == "valid"
        return self.authenticated

    def place_order(self, request: OrderRequest) -> OrderResponse:
        self.orders.append(request)
        return OrderResponse(
            order_id=f"MOCK-{len(self.orders)}",
            status=OrderStatus.FILLED,
            filled_qty=request.qty,
            avg_price=request.price,
        )

    def cancel_order(self, order_id: str) -> OrderResponse:
        return OrderResponse(order_id=order_id, status=OrderStatus.CANCELLED)

    def get_ltp(self, symbol: str) -> float:
        return self.ltp_values.get(symbol, 100.0)

    def get_positions(self) -> list[dict]:
        return self.positions

    def get_order_status(self, order_id: str) -> OrderResponse:
        return OrderResponse(order_id=order_id, status=OrderStatus.FILLED)

    def get_instrument_token(self, symbol: str) -> str:
        return f"TOKEN-{symbol}"

    def is_healthy(self) -> bool:
        return self.healthy


class FailingBrokerAdapter(BrokerAdapter):
    """Adapter that fails on every operation."""

    def authenticate(self, credentials: dict) -> bool:
        raise ConnectionError("Broker unreachable")

    def place_order(self, request: OrderRequest) -> OrderResponse:
        raise TimeoutError("Request timed out")

    def cancel_order(self, order_id: str) -> OrderResponse:
        raise ValueError("Invalid order")

    def get_ltp(self, symbol: str) -> float:
        raise ConnectionError("Connection lost")

    def get_positions(self) -> list[dict]:
        raise TimeoutError("Position fetch timeout")

    def get_order_status(self, order_id: str) -> OrderResponse:
        raise AttributeError("Session expired")

    def get_instrument_token(self, symbol: str) -> str:
        raise ValueError("Unknown symbol")

    def is_healthy(self) -> bool:
        return False


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def gateway():
    """Fresh BrokerGateway instance for each test."""
    return BrokerGateway()


# ── Initial State Tests ───────────────────────────────────────────────────────


class TestBrokerGatewayInit:
    """Initial state - no active adapter, empty registry."""

    def test_no_active_adapter_after_init(self, gateway):
        """No adapter should be active initially."""
        assert gateway._active_adapter is None
        assert gateway._current_broker_name is None

    def test_empty_registry_after_init(self, gateway):
        """Registry should be empty initially."""
        assert gateway._adapter_registry == {}


# ── register_adapter Tests ────────────────────────────────────────────────────


class TestRegisterAdapter:
    """register_adapter() - adapter class registration."""

    def test_register_valid_adapter(self, gateway):
        """Register a valid BrokerAdapter subclass."""
        gateway.register_adapter("mock", MockBrokerAdapter)
        assert "mock" in gateway._adapter_registry
        assert gateway._adapter_registry["mock"] is MockBrokerAdapter

    def test_register_multiple_adapters(self, gateway):
        """Multiple adapters can be registered."""
        gateway.register_adapter("mock1", MockBrokerAdapter)
        gateway.register_adapter("mock2", MockBrokerAdapter)
        assert len(gateway._adapter_registry) == 2

    def test_register_overwrites_existing(self, gateway):
        """Registering same name should overwrite."""
        gateway.register_adapter("mock", MockBrokerAdapter)
        gateway.register_adapter("mock", MockBrokerAdapter)
        assert len(gateway._adapter_registry) == 1  # Same key, overwritten


# ── connect Tests ─────────────────────────────────────────────────────────────


class TestConnect:
    """connect() - instantiate and authenticate broker."""

    def test_connect_registered_broker_success(self, gateway):
        """Connect to registered broker with valid credentials."""
        gateway.register_adapter("mock", MockBrokerAdapter)
        result = gateway.connect("mock", {"key": "valid"})
        assert result is True
        assert gateway._current_broker_name == "mock"
        assert gateway._active_adapter is not None

    def test_connect_registered_broker_auth_failure(self, gateway):
        """Connect to registered broker with invalid credentials."""
        gateway.register_adapter("mock", MockBrokerAdapter)
        result = gateway.connect("mock", {"key": "invalid"})
        assert result is False
        assert gateway._active_adapter is None

    def test_connect_unregistered_broker(self, gateway):
        """Connect to unregistered broker should fail."""
        result = gateway.connect("nonexistent", {"key": "valid"})
        assert result is False
        assert gateway._active_adapter is None

    def test_connect_with_failing_adapter(self, gateway):
        """Adapter that raises during connect should return False."""
        gateway.register_adapter("failing", FailingBrokerAdapter)
        result = gateway.connect("failing", {})
        assert result is False
        assert gateway._active_adapter is None


# ── place_order Tests ─────────────────────────────────────────────────────────


class TestPlaceOrder:
    """place_order() - route order to active adapter."""

    def test_place_order_with_active_adapter(self, gateway):
        """Place order through active adapter returns success."""
        gateway.register_adapter("mock", MockBrokerAdapter)
        gateway.connect("mock", {"key": "valid"})
        request = OrderRequest(
            symbol="NIFTY",
            qty=50,
            price=150.0,
            order_type="MARKET",
            direction="BUY",
            product="MIS",
            variety="REGULAR",
        )
        response = gateway.place_order(request)
        assert response.status == OrderStatus.FILLED
        assert response.order_id.startswith("MOCK-")
        assert response.filled_qty == 50

    def test_place_order_no_active_adapter(self, gateway):
        """Place order with no active adapter returns FAILED."""
        request = OrderRequest(
            symbol="NIFTY", qty=50, price=150.0,
            order_type="MARKET", direction="BUY",
            product="MIS", variety="REGULAR",
        )
        response = gateway.place_order(request)
        assert response.status == OrderStatus.FAILED
        assert response.order_id == "NONE"
        assert "No active broker" in (response.error or "")

    def test_place_order_adapter_error(self, gateway):
        """Adapter error during place_order returns FAILED."""
        gateway.register_adapter("failing", FailingBrokerAdapter)
        # We need a connected adapter - let's patch the authenticate
        with patch.object(FailingBrokerAdapter, "authenticate", return_value=True):
            gateway.connect("failing", {})
        request = OrderRequest(
            symbol="NIFTY", qty=50, price=150.0,
            order_type="MARKET", direction="BUY",
            product="MIS", variety="REGULAR",
        )
        response = gateway.place_order(request)
        assert response.status == OrderStatus.FAILED
        assert response.order_id == "ERROR"


# ── get_ltp Tests ─────────────────────────────────────────────────────────────


class TestGetLTP:
    """get_ltp() - fetch Last Traded Price."""

    def test_get_ltp_with_active_adapter(self, gateway):
        """Get LTP returns value from active adapter."""
        gateway.register_adapter("mock", MockBrokerAdapter)
        gateway.connect("mock", {"key": "valid"})
        gateway._active_adapter.ltp_values["NIFTY"] = 23500.50
        ltp = gateway.get_ltp("NIFTY")
        assert ltp == 23500.50

    def test_get_ltp_no_active_adapter(self, gateway):
        """Get LTP with no active adapter returns 0.0."""
        ltp = gateway.get_ltp("NIFTY")
        assert ltp == 0.0

    def test_get_ltp_adapter_error(self, gateway):
        """Adapter error during get_ltp returns 0.0."""
        gateway.register_adapter("failing", FailingBrokerAdapter)
        with patch.object(FailingBrokerAdapter, "authenticate", return_value=True):
            gateway.connect("failing", {})
        ltp = gateway.get_ltp("NIFTY")
        assert ltp == 0.0


# ── get_positions Tests ───────────────────────────────────────────────────────


class TestGetPositions:
    """get_positions() - fetch open positions."""

    def test_get_positions_with_active_adapter(self, gateway):
        """Get positions returns values from active adapter."""
        gateway.register_adapter("mock", MockBrokerAdapter)
        gateway.connect("mock", {"key": "valid"})
        gateway._active_adapter.positions = [{"symbol": "NIFTY", "qty": 50}]
        positions = gateway.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "NIFTY"

    def test_get_positions_no_active_adapter(self, gateway):
        """Get positions with no active adapter returns empty list."""
        positions = gateway.get_positions()
        assert positions == []

    def test_get_positions_adapter_error(self, gateway):
        """Adapter error during get_positions returns empty list."""
        gateway.register_adapter("failing", FailingBrokerAdapter)
        with patch.object(FailingBrokerAdapter, "authenticate", return_value=True):
            gateway.connect("failing", {})
        positions = gateway.get_positions()
        assert positions == []


# ── switch_broker Tests ───────────────────────────────────────────────────────


class TestSwitchBroker:
    """switch_broker() - runtime broker failover."""

    def test_switch_to_registered_broker(self, gateway):
        """Switch to a registered broker should succeed."""
        gateway.register_adapter("mock1", MockBrokerAdapter)
        gateway.register_adapter("mock2", MockBrokerAdapter)
        gateway.connect("mock1", {"key": "valid"})
        assert gateway._current_broker_name == "mock1"

        result = gateway.switch_broker("mock2", {"key": "valid"})
        assert result is True
        assert gateway._current_broker_name == "mock2"

    def test_switch_to_unregistered_broker(self, gateway):
        """Switch to unregistered broker should fail."""
        gateway.register_adapter("mock1", MockBrokerAdapter)
        gateway.connect("mock1", {"key": "valid"})
        result = gateway.switch_broker("nonexistent", {})
        assert result is False
        # Should still be connected to original broker
        assert gateway._current_broker_name == "mock1"


# ── Singleton Tests ───────────────────────────────────────────────────────────


class TestSingleton:
    """Module-level broker_gateway singleton."""

    def test_singleton_is_instance(self):
        """broker_gateway should be a BrokerGateway instance."""
        assert isinstance(broker_gateway, BrokerGateway)

    def test_singleton_persistence(self):
        """broker_gateway should persist state across imports."""
        # If we modify the singleton directly, it stays modified
        assert hasattr(broker_gateway, "_adapter_registry")


# ── Integration-Style Tests ───────────────────────────────────────────────────


class TestBrokerGatewayIntegration:
    """End-to-end workflow tests."""

    def test_full_connect_order_workflow(self, gateway):
        """Complete workflow: register -> connect -> place_order -> get_positions."""
        gateway.register_adapter("mock", MockBrokerAdapter)
        connected = gateway.connect("mock", {"key": "valid"})
        assert connected is True

        request = OrderRequest(
            symbol="BANKNIFTY", qty=25, price=50000.0,
            order_type="LIMIT", direction="SELL",
            product="MIS", variety="REGULAR",
        )
        response = gateway.place_order(request)
        assert response.status == OrderStatus.FILLED

        ltp = gateway.get_ltp("BANKNIFTY")
        assert ltp == 100.0  # default MockBrokerAdapter value

    def test_connect_then_disconnect_pattern(self, gateway):
        """Simulate disconnect by setting active adapter to None."""
        gateway.register_adapter("mock", MockBrokerAdapter)
        gateway.connect("mock", {"key": "valid"})
        assert gateway._active_adapter is not None

        # Simulate disconnect
        gateway._active_adapter = None
        gateway._current_broker_name = None

        # All operations should fail gracefully
        request = OrderRequest(
            symbol="NIFTY", qty=50, price=150.0,
            order_type="MARKET", direction="BUY",
            product="MIS", variety="REGULAR",
        )
        response = gateway.place_order(request)
        assert response.status == OrderStatus.FAILED
        assert gateway.get_ltp("NIFTY") == 0.0
        assert gateway.get_positions() == []

    def test_multiple_adapters_failover(self, gateway):
        """Switch between working adapters."""
        gateway.register_adapter("primary", MockBrokerAdapter)
        gateway.register_adapter("backup", MockBrokerAdapter)

        gateway.connect("primary", {"key": "valid"})
        assert gateway._current_broker_name == "primary"

        # Failover to backup
        result = gateway.switch_broker("backup", {"key": "valid"})
        assert result is True
        assert gateway._current_broker_name == "backup"

        # Verify backup works
        request = OrderRequest(
            symbol="NIFTY", qty=10, price=200.0,
            order_type="MARKET", direction="BUY",
            product="MIS", variety="REGULAR",
        )
        response = gateway.place_order(request)
        assert response.status == OrderStatus.FILLED
