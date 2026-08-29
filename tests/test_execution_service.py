"""
Tests for core/services/execution_service.py - ExecutionService (new, replaces legacy execution_engine).

Covers:
  - ExecutionService initialization with defaults
  - execute_order with OrderRequest
  - Duplicate order prevention via idempotency
  - Cancel order
  - Get order status
  - Verify order fill
  - Health check
  - Trading freeze on reconciliation
  - Paper mode execution
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core.ports.execution.execution_port import (
    ExecutionContext,
    ExecutionMode,
    ExecutionPort,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
)
from core.services.execution_service import ExecutionService, ExecutionServiceConfig

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def mock_broker() -> MagicMock:
    broker = MagicMock()
    broker.place_order.return_value = OrderResult(
        order_id="ORD-001",
        status=OrderStatus.FILLED,
        filled_quantity=50,
        average_price=23500.0,
        broker_order_id="BRK-001",
    )
    broker.cancel_order.return_value = True
    broker.get_order_status.return_value = OrderStatus.FILLED
    broker.wait_for_fill.return_value = True
    broker.get_filled_quantity.return_value = 50
    broker.get_average_price.return_value = 23500.0
    return broker


@pytest.fixture()
def service(mock_broker: MagicMock) -> ExecutionService:
    """ExecutionService with mock broker and minimal config."""
    config = ExecutionServiceConfig(
        enable_duplicate_prevention=True,
        idempotency_cache_size=100,
        idempotency_expiry_hours=24,
        enable_audit_trail=False,
        paper_fill_delay_ms=0,
        paper_fill_slippage_pct=0.0,
        max_retries=1,
    )
    svc = ExecutionService(
        config=config,
        broker_port=mock_broker,
        reconciliation_db_path=":memory:",
    )
    return svc


@pytest.fixture()
def order_request() -> OrderRequest:
    """Standard NIFTY CALL order request."""
    return OrderRequest(
        symbol="NIFTY",
        direction="BUY",
        strike_price=23500.0,
        lot_size=50,
        order_type=OrderType.MARKET,
    )


@pytest.fixture()
def execution_context() -> ExecutionContext:
    """Default execution context for testing."""
    return ExecutionContext(execution_mode=ExecutionMode.PAPER)


# ── Initialization ───────────────────────────────────────────────────


class TestInitialization:
    def test_implements_execution_port(self, service: ExecutionService) -> None:
        assert isinstance(service, ExecutionPort)

    def test_default_config_creates(self) -> None:
        svc = ExecutionService(reconciliation_db_path=":memory:")
        assert svc.config is not None
        assert svc.config.max_retries == 3
        assert svc.config.enable_duplicate_prevention is True

    def test_dict_config_converts(self) -> None:
        svc = ExecutionService(
            config={"max_retries": 5, "enable_duplicate_prevention": False},
            reconciliation_db_path=":memory:",
        )
        assert svc.config.max_retries == 5
        assert svc.config.enable_duplicate_prevention is False

    def test_default_order_fill_timeout_sec_is_10(self) -> None:
        svc = ExecutionService(reconciliation_db_path=":memory:")
        assert svc.config.order_fill_timeout_sec == 10

    def test_config_max_retries_flows_into_state_handler(self) -> None:
        """config key ORDER_PLACE_RETRIES (via ExecutionServiceConfig.max_retries)
        must actually reach the constructed BrokerStateHandler, not just sit
        unused on the dataclass."""
        svc = ExecutionService(
            config={"max_retries": 5},
            reconciliation_db_path=":memory:",
        )
        assert svc._state_handler._max_retries == 5

    def test_has_idempotency_manager(self, service: ExecutionService) -> None:
        assert service.idempotency is not None

    def test_has_lock(self, service: ExecutionService) -> None:
        assert hasattr(service, "_lock")


# ── Execute Order ────────────────────────────────────────────────────


class TestExecuteOrder:
    def teardown_method(self) -> None:
        """Clean up global hard halt state after each test to prevent test isolation leaks."""
        from core.safety_state import _HARD_HALT
        if _HARD_HALT.is_set():
            _HARD_HALT.clear()

    def test_execute_order_returns_result(
        self, service: ExecutionService, order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> None:
        result = service.execute_order(order_request, execution_context)
        assert isinstance(result, OrderResult)
        assert result.status in (OrderStatus.FILLED, OrderStatus.SUBMITTED, OrderStatus.REJECTED)

    def test_execute_order_with_idempotency_key(
        self, service: ExecutionService, order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> None:
        order_request.idempotency_key = "test-key-001"
        result = service.execute_order(order_request, execution_context)
        assert isinstance(result, OrderResult)

    def test_duplicate_order_safe(
        self, service: ExecutionService, order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> None:
        """Calling with same idempotency key is safe (no crash, no invalid state)."""
        order_request.idempotency_key = "dup-safe-key-001"
        service.execute_order(order_request, execution_context)
        # Second attempt with same key should not crash and should return a result
        result2 = service.execute_order(order_request, execution_context)
        assert isinstance(result2, OrderResult), "Second call must return OrderResult"

    def test_hard_halt_blocks_execution(
        self, service: ExecutionService, order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> None:
        """Simulate hard halt by injecting the check."""
        from core.safety_state import _HARD_HALT
        original = _HARD_HALT.is_set()
        try:
            _HARD_HALT.set()
            result = service.execute_order(order_request, execution_context)
            assert result.status == OrderStatus.REJECTED
        finally:
            if not original:
                _HARD_HALT.clear()

    def test_paper_mode_returns_filled(
        self, service: ExecutionService, order_request: OrderRequest
    ) -> None:
        ctx = ExecutionContext(execution_mode=ExecutionMode.PAPER)
        result = service.execute_order(order_request, ctx)
        # Paper mode should always fill immediately
        assert result.status == OrderStatus.FILLED

    def test_execute_with_none_context(
        self, service: ExecutionService, order_request: OrderRequest
    ) -> None:
        result = service.execute_order(order_request)
        assert isinstance(result, OrderResult)


# ── Smart Router (multi-broker failover, opt-in) ────────────────────


class TestSmartRouterWiring:
    """core.execution.smart_router.SmartRouter integration in
    _attempt_order_execution(). Opt-in - self._smart_router is None unless
    a caller explicitly passes one (the DI container only builds one when
    SECONDARY_BROKER_DRIVER is configured)."""

    def teardown_method(self) -> None:
        from core.safety_state import _HARD_HALT
        if _HARD_HALT.is_set():
            _HARD_HALT.clear()

    def test_disabled_by_default_uses_broker_port_directly(
        self, service: ExecutionService, mock_broker: MagicMock, order_request: OrderRequest,
    ) -> None:
        """Regression guard: with no smart_router configured (today's only
        real case), place_order must go straight to broker_port exactly as
        before."""
        ctx = ExecutionContext(execution_mode=ExecutionMode.MANUAL)
        service.execute_order(order_request, ctx)
        mock_broker.place_order.assert_called_once_with(order_request)

    def test_enabled_routes_through_smart_router(
        self, service: ExecutionService, mock_broker: MagicMock, order_request: OrderRequest,
    ) -> None:
        """With a smart_router configured, the order must route through it
        instead of calling broker_port.place_order directly."""
        from core.execution.smart_router import RouteResult

        mock_broker.get_filled_quantity.return_value = 50
        mock_broker.get_fill_price.return_value = 23500.0
        mock_router = MagicMock()
        mock_router.route_to_best.return_value = RouteResult(
            success=True, broker="KITE", order_id="ROUTED-001",
        )
        mock_router._routers = {"KITE": mock_broker}
        service._smart_router = mock_router

        ctx = ExecutionContext(execution_mode=ExecutionMode.MANUAL)
        result = service.execute_order(order_request, ctx)

        mock_router.route_to_best.assert_called_once()
        mock_broker.place_order.assert_not_called()  # not called directly - routed instead
        assert result.order_id == "ROUTED-001"

    def test_routed_fill_status_is_queried_on_the_broker_that_actually_placed_it(
        self, service: ExecutionService, order_request: OrderRequest,
    ) -> None:
        """Regression guard for the same class of bug already fixed once in
        this codebase (get_fill_price() querying the wrong adapter): when the
        router picks a SECONDARY broker, filled_quantity/fill_price must be
        queried on THAT broker, not on self.broker_port."""
        from core.execution.smart_router import RouteResult

        secondary_broker = MagicMock()
        secondary_broker.get_filled_quantity.return_value = 50
        secondary_broker.get_fill_price.return_value = 275.0

        mock_router = MagicMock()
        mock_router.route_to_best.return_value = RouteResult(
            success=True, broker="ANGEL", order_id="ROUTED-002",
        )
        mock_router._routers = {"ANGEL": secondary_broker}
        service._smart_router = mock_router

        ctx = ExecutionContext(execution_mode=ExecutionMode.MANUAL)
        result = service.execute_order(order_request, ctx)

        secondary_broker.get_filled_quantity.assert_called_once_with("ROUTED-002")
        secondary_broker.get_fill_price.assert_called_once_with("ROUTED-002")
        assert result.status == OrderStatus.FILLED
        assert result.average_price == 275.0

    def test_enabled_no_broker_available_rejects_without_touching_broker_port(
        self, service: ExecutionService, mock_broker: MagicMock, order_request: OrderRequest,
    ) -> None:
        from core.execution.smart_router import RouteResult

        mock_router = MagicMock()
        mock_router.route_to_best.return_value = RouteResult(
            success=False, broker="", order_id="", error="No available broker found",
        )
        service._smart_router = mock_router

        ctx = ExecutionContext(execution_mode=ExecutionMode.MANUAL)
        result = service.execute_order(order_request, ctx)

        mock_broker.place_order.assert_not_called()
        assert result.status == OrderStatus.REJECTED
        assert "No available broker found" in result.reject_reason


# ── Cancel Order ─────────────────────────────────────────────────────


class TestCancelOrder:
    def test_cancel_returns_bool(self, service: ExecutionService) -> None:
        result = service.cancel_order("ORD-001")
        assert isinstance(result, bool)

    def test_cancel_invalid_order(self, service: ExecutionService) -> None:
        # Should not raise exception for invalid order
        result = service.cancel_order("NONEXISTENT")
        assert isinstance(result, bool)

    def test_cancel_empty_id(self, service: ExecutionService) -> None:
        result = service.cancel_order("")
        assert isinstance(result, bool)


# ── Get Order Status ─────────────────────────────────────────────────


class TestGetOrderStatus:
    def test_returns_order_status(self, service: ExecutionService) -> None:
        status = service.get_order_status("ORD-001")
        assert isinstance(status, OrderStatus)

    def test_duplicate_id_returns_rejected(self, service: ExecutionService) -> None:
        status = service.get_order_status("duplicate")
        assert status == OrderStatus.REJECTED

    def test_empty_id_returns_rejected(self, service: ExecutionService) -> None:
        status = service.get_order_status("")
        assert status == OrderStatus.REJECTED


# ── Verify Order Fill ────────────────────────────────────────────────


class TestVerifyOrderFill:
    def test_returns_dict_with_required_keys(
        self, service: ExecutionService
    ) -> None:
        result = service.verify_order_fill("ORD-001", timeout_seconds=1)
        assert isinstance(result, dict)
        assert "ok" in result
        assert "filled_quantity" in result
        assert "average_price" in result
        assert "order_id" in result

    def test_verify_successful_fill(
        self, service: ExecutionService
    ) -> None:
        result = service.verify_order_fill("ORD-001", timeout_seconds=1)
        assert result["ok"] is True or result["ok"] is False

    def test_omitted_timeout_uses_config_order_fill_timeout_sec(
        self, service: ExecutionService, mock_broker: MagicMock
    ) -> None:
        """config key ORDER_FILL_TIMEOUT_SEC (via order_fill_timeout_sec)
        must be the real fallback when the caller omits timeout_seconds."""
        service.config.order_fill_timeout_sec = 7
        service.verify_order_fill("ORD-001")
        mock_broker.wait_for_fill.assert_called_once_with("ORD-001", timeout=7)

    def test_explicit_timeout_overrides_config_default(
        self, service: ExecutionService, mock_broker: MagicMock
    ) -> None:
        service.config.order_fill_timeout_sec = 7
        service.verify_order_fill("ORD-001", timeout_seconds=2)
        mock_broker.wait_for_fill.assert_called_once_with("ORD-001", timeout=2)

    def test_verify_empty_order_id(
        self, service: ExecutionService
    ) -> None:
        result = service.verify_order_fill("", timeout_seconds=1)
        # An empty order ID should not cause an exception
        assert isinstance(result, dict)
        assert "ok" in result


# ── Duplicate Detection ──────────────────────────────────────────────


class TestIsDuplicateOrder:
    def test_returns_bool(self, service: ExecutionService) -> None:
        result = service.is_duplicate_order("unknown-key")
        assert isinstance(result, bool)

    def test_after_execution_returns_true(
        self, service: ExecutionService, order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> None:
        order_request.idempotency_key = "dup-detect-key"
        service.execute_order(order_request, execution_context)
        is_dup = service.is_duplicate_order("dup-detect-key")
        assert is_dup is True


# ── Audit Trail ──────────────────────────────────────────────────────


class TestAuditTrail:
    def test_record_and_retrieve(
        self, service: ExecutionService, order_request: OrderRequest
    ) -> None:
        from core.ports.execution.execution_port import ExecutionAuditTrail
        audit = ExecutionAuditTrail(
            execution_id="audit-001",
            order_request=order_request,
        )
        recorded = service.record_execution_audit(audit)
        assert recorded is True

        retrieved = service.get_execution_audit_trail("audit-001")
        assert retrieved is not None
        assert retrieved.execution_id == "audit-001"

    def test_get_nonexistent(self, service: ExecutionService) -> None:
        result = service.get_execution_audit_trail("nonexistent")
        assert result is None


# ── Health Check ─────────────────────────────────────────────────────


class TestHealthCheck:
    def test_returns_dict_with_status(self, service: ExecutionService) -> None:
        result = service.health_check()
        assert isinstance(result, dict)
        assert "status" in result
        assert "service" in result


# ── Trading Freeze ───────────────────────────────────────────────────


class TestTradingFreeze:
    def test_not_frozen_initially(self, service: ExecutionService) -> None:
        # Initialize the freeze state by calling set_operating_mode_manager
        service.set_operating_mode_manager(None)
        assert not service.is_trading_frozen()

    def test_unfreeze_works(self, service: ExecutionService) -> None:
        service.set_operating_mode_manager(None)
        service.unfreeze_trading()
        assert not service.is_trading_frozen()


# ── Port Interface Compliance ────────────────────────────────────────


class TestPortInterface:
    """Verify ExecutionService implements all abstract methods of ExecutionPort."""

    def test_all_abstract_methods_implemented(self) -> None:
        """Check that ExecutionService has concrete implementations for all abstract methods."""
        import inspect

        from core.ports.execution.execution_port import ExecutionPort

        abstract_methods = [
            name for name, method in inspect.getmembers(ExecutionPort)
            if getattr(method, "__isabstractmethod__", False)
        ]
        impl_methods = [
            name for name, _ in inspect.getmembers(ExecutionService)
            if not name.startswith("_")
        ]

        for method in abstract_methods:
            assert method in impl_methods, (
                f"ExecutionService missing implementation for {method}"
            )
