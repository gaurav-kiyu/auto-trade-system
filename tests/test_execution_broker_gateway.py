"""Tests for core/execution/broker_gateway.py - Broker Gateway."""

from __future__ import annotations

import pytest
from core.adapters.base_adapter import BrokerAdapter, OrderRequest, OrderResponse, OrderStatus
from core.execution.broker_gateway import BrokerGateway, broker_gateway


def _make_order_request(**overrides) -> OrderRequest:
    """Helper to create OrderRequest with sensible defaults."""
    params = {
        "symbol": "NIFTY",
        "qty": 50,
        "price": 0.0,
        "order_type": "MARKET",
        "direction": "BUY",
        "product": "MIS",
        "variety": "REGULAR",
    }
    params.update(overrides)
    return OrderRequest(**params)


class FakeHealthyAdapter(BrokerAdapter):
    """Adapter that succeeds on all operations."""

    def authenticate(self, credentials: dict) -> bool:
        return credentials.get("key") == "valid"

    def place_order(self, request: OrderRequest) -> OrderResponse:
        return OrderResponse(
            order_id="FAKE_ORD_001",
            status=OrderStatus.FILLED,
            filled_qty=request.qty,
            avg_price=100.0,
        )

    def cancel_order(self, order_id: str) -> OrderResponse:
        return OrderResponse(order_id=order_id, status=OrderStatus.CANCELLED)

    def get_ltp(self, symbol: str) -> float:
        return 23500.0 if symbol == "NIFTY" else 0.0

    def get_positions(self) -> list[dict]:
        return [{"symbol": "NIFTY", "qty": 50, "pnl": 100.0}]

    def get_order_status(self, order_id: str) -> OrderResponse:
        return OrderResponse(order_id=order_id, status=OrderStatus.FILLED)

    def get_instrument_token(self, symbol: str) -> str:
        return f"TOKEN_{symbol}"

    def is_healthy(self) -> bool:
        return True


class FakeFailingAdapter(BrokerAdapter):
    """Adapter that fails on every operation."""

    def authenticate(self, credentials: dict) -> bool:
        return False

    def place_order(self, request: OrderRequest) -> OrderResponse:
        raise ConnectionError("Simulated connection failure")

    def cancel_order(self, order_id: str) -> OrderResponse:
        raise ConnectionError("Simulated failure")

    def get_ltp(self, symbol: str) -> float:
        raise TimeoutError("Simulated timeout")

    def get_positions(self) -> list[dict]:
        raise ValueError("Simulated error fetching positions")

    def get_order_status(self, order_id: str) -> OrderResponse:
        raise ConnectionError("Simulated failure")

    def get_instrument_token(self, symbol: str) -> str:
        raise ValueError("Simulated error")

    def is_healthy(self) -> bool:
        return False


class TestBrokerGateway:
    """BrokerGateway functional coverage."""

    @pytest.fixture
    def gateway(self):
        g = BrokerGateway()
        g.register_adapter("healthy", FakeHealthyAdapter)
        g.register_adapter("failing", FakeFailingAdapter)
        return g

    def test_register_adapter(self, gateway):
        assert "healthy" in gateway._adapter_registry
        assert "failing" in gateway._adapter_registry

    def test_connect_success(self, gateway):
        result = gateway.connect("healthy", {"key": "valid"})
        assert result is True
        assert gateway._current_broker_name == "healthy"
        assert gateway._active_adapter is not None

    def test_connect_failure_wrong_credentials(self, gateway):
        result = gateway.connect("healthy", {"key": "invalid"})
        assert result is False
        assert gateway._active_adapter is None

    def test_connect_unregistered_broker(self, gateway):
        result = gateway.connect("unknown", {})
        assert result is False

    def test_connect_failing_adapter(self, gateway):
        result = gateway.connect("failing", {"key": "valid"})
        assert result is False

    def test_place_order_no_connection(self, gateway):
        response = gateway.place_order(_make_order_request())
        assert response.status == OrderStatus.FAILED
        assert "No active broker" in response.error

    def test_place_order_success(self, gateway):
        gateway.connect("healthy", {"key": "valid"})
        response = gateway.place_order(
            _make_order_request(symbol="NIFTY", qty=50)
        )
        assert response.status == OrderStatus.FILLED
        assert response.order_id == "FAKE_ORD_001"

    def test_place_order_failing_adapter(self, gateway):
        # Bypass auth by directly setting adapter
        gateway._active_adapter = FakeFailingAdapter()
        gateway._current_broker_name = "failing"
        response = gateway.place_order(
            _make_order_request(symbol="NIFTY", qty=50)
        )
        assert response.status == OrderStatus.FAILED

    def test_get_ltp_no_connection(self, gateway):
        price = gateway.get_ltp("NIFTY")
        assert price == 0.0

    def test_get_ltp_success(self, gateway):
        gateway.connect("healthy", {"key": "valid"})
        price = gateway.get_ltp("NIFTY")
        assert price == 23500.0

    def test_get_ltp_unknown_symbol(self, gateway):
        gateway.connect("healthy", {"key": "valid"})
        price = gateway.get_ltp("UNKNOWN")
        assert price == 0.0

    def test_get_positions_no_connection(self, gateway):
        positions = gateway.get_positions()
        assert positions == []

    def test_get_positions_success(self, gateway):
        gateway.connect("healthy", {"key": "valid"})
        positions = gateway.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "NIFTY"

    def test_switch_broker_success(self, gateway):
        gateway.register_adapter("healthy2", FakeHealthyAdapter)
        gateway.connect("healthy", {"key": "valid"})
        assert gateway._current_broker_name == "healthy"
        result = gateway.switch_broker("healthy2", {"key": "valid"})
        assert result is True
        assert gateway._current_broker_name == "healthy2"

    def test_switch_broker_failure(self, gateway):
        gateway.connect("healthy", {"key": "valid"})
        result = gateway.switch_broker("unknown", {})
        assert result is False

    def test_place_order_multiple(self, gateway):
        gateway.connect("healthy", {"key": "valid"})
        for i in range(3):
            resp = gateway.place_order(
                _make_order_request(symbol="NIFTY", qty=10 * (i + 1))
            )
            assert resp.status == OrderStatus.FILLED

    def test_double_connect(self, gateway):
        gateway.register_adapter("healthy2", FakeHealthyAdapter)
        gateway.connect("healthy", {"key": "valid"})
        assert gateway._current_broker_name == "healthy"
        gateway.connect("healthy2", {"key": "valid"})
        assert gateway._current_broker_name == "healthy2"

    def test_place_order_with_connection_error(self, gateway):
        """Simulate an adapter that raises ConnectionError during order placement."""
        gateway.connect("healthy", {"key": "valid"})
        adapter = gateway._active_adapter

        def failing_place(request):
            raise ConnectionError("Network error")

        adapter.place_order = failing_place
        response = gateway.place_order(
            _make_order_request(symbol="NIFTY", qty=50)
        )
        assert response.status == OrderStatus.FAILED
        assert response.error is not None

    def test_connect_with_empty_credentials(self, gateway):
        result = gateway.connect("healthy", {})
        assert result is False

    def test_get_ltp_failing_adapter(self, gateway):
        """Test LTP fetch from adapter that raises exceptions."""
        bad_adapter = FakeFailingAdapter()
        gateway._active_adapter = bad_adapter
        price = gateway.get_ltp("NIFTY")
        assert price == 0.0  # Graceful fallback


class TestSingletonGateway:
    """Singleton broker_gateway instance coverage."""

    def test_singleton_is_instance(self):
        assert isinstance(broker_gateway, BrokerGateway)

    def test_singleton_mutable_state(self):
        """The module-level singleton should be the same across references."""
        g = broker_gateway
        g.register_adapter("test_singleton_adapter2", FakeHealthyAdapter)
        assert "test_singleton_adapter2" in broker_gateway._adapter_registry
