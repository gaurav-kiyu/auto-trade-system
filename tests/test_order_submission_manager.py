"""Tests for core/execution/order_submission/manager.py - Order Submission Manager.

Covers:
- OrderSubmissionManager init with broker port
- submit() with successful OrderResult
- submit() with string ID response from broker
- submit() with broker exception (returns REJECTED)
- Edge cases: None result, empty string ID
- Contract validation: broker_port interface
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core.common.kernels.models import OrderResult as KernelOrderResult
from core.execution.order_submission.manager import OrderSubmissionManager
from core.ports.broker import LegacyBrokerPort, OrderRequest

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_request() -> OrderRequest:
    return OrderRequest(
        symbol="NIFTY",
        quantity=50,
        price=None,
        order_type="MARKET",
        direction="BUY",
    )


@pytest.fixture
def success_result() -> KernelOrderResult:
    return KernelOrderResult(
        order_id="ORD-001",
        status="SUBMITTED",
        timestamp="2026-06-20T10:00:00",
    )


@pytest.fixture
def mock_broker_port() -> MagicMock:
    return MagicMock(spec=LegacyBrokerPort)


@pytest.fixture
def mgr(mock_broker_port: MagicMock) -> OrderSubmissionManager:
    return OrderSubmissionManager(broker_port=mock_broker_port)


# ═══════════════════════════════════════════════════════════════════════════════
#  Initialization
# ═══════════════════════════════════════════════════════════════════════════════


class TestInit:
    def test_stores_broker_port(self, mock_broker_port: MagicMock):
        mgr = OrderSubmissionManager(broker_port=mock_broker_port)
        assert mgr.broker_port is mock_broker_port

    def test_raises_without_port(self):
        with pytest.raises(TypeError):
            OrderSubmissionManager()  # type: ignore[call-arg]


# ═══════════════════════════════════════════════════════════════════════════════
#  submit() - Success Paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestSubmitSuccess:
    def test_returns_order_result(self, mgr: OrderSubmissionManager,
                                  sample_request: OrderRequest, success_result: KernelOrderResult,
                                  mock_broker_port: MagicMock):
        mock_broker_port.place_order.return_value = success_result
        result = mgr.submit(sample_request)
        assert result == success_result
        assert result.order_id == "ORD-001"

    def test_passes_request_to_broker(self, mgr: OrderSubmissionManager,
                                      sample_request: OrderRequest, success_result: KernelOrderResult,
                                      mock_broker_port: MagicMock):
        mock_broker_port.place_order.return_value = success_result
        mgr.submit(sample_request)
        mock_broker_port.place_order.assert_called_once_with(sample_request)

    def test_string_response_wraps_in_result(self, mgr: OrderSubmissionManager,
                                             sample_request: OrderRequest,
                                             mock_broker_port: MagicMock):
        """When broker returns a string ID, wrap it in OrderResult."""
        mock_broker_port.place_order.return_value = "STR-ORD-001"
        result = mgr.submit(sample_request)
        assert isinstance(result, KernelOrderResult)
        assert result.order_id == "STR-ORD-001"
        assert result.status == "SUBMITTED"

    def test_string_response_timestamp_none(self, mgr: OrderSubmissionManager,
                                            sample_request: OrderRequest,
                                            mock_broker_port: MagicMock):
        """String responses should have None timestamp (caller sets it)."""
        mock_broker_port.place_order.return_value = "STR-ID"
        result = mgr.submit(sample_request)
        assert result.timestamp is None


# ═══════════════════════════════════════════════════════════════════════════════
#  submit() - Error Paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestSubmitError:
    def test_exception_returns_rejected(self, mgr: OrderSubmissionManager,
                                        sample_request: OrderRequest,
                                        mock_broker_port: MagicMock):
        """When broker raises, return REJECTED OrderResult with error message."""
        mock_broker_port.place_order.side_effect = ConnectionError("Broker unreachable")
        result = mgr.submit(sample_request)
        assert result.status == "REJECTED"
        assert result.order_id == "ERROR"
        assert "Broker unreachable" in (result.reject_reason or "")

    def test_value_error_handled(self, mgr: OrderSubmissionManager,
                                 sample_request: OrderRequest,
                                 mock_broker_port: MagicMock):
        mock_broker_port.place_order.side_effect = ValueError("Invalid order")
        result = mgr.submit(sample_request)
        assert result.status == "REJECTED"
        assert "Invalid order" in (result.reject_reason or "")

    def test_timeout_error_handled(self, mgr: OrderSubmissionManager,
                                   sample_request: OrderRequest,
                                   mock_broker_port: MagicMock):
        mock_broker_port.place_order.side_effect = TimeoutError("Request timed out")
        result = mgr.submit(sample_request)
        assert result.status == "REJECTED"
        assert "timed out" in (result.reject_reason or "").lower()

    def test_broker_returns_none(self, mgr: OrderSubmissionManager,
                                 sample_request: OrderRequest,
                                 mock_broker_port: MagicMock):
        """None response should flow through without error (caller handles it)."""
        mock_broker_port.place_order.return_value = None
        result = mgr.submit(sample_request)
        assert result is None

    def test_empty_string_id(self, mgr: OrderSubmissionManager,
                             sample_request: OrderRequest,
                             mock_broker_port: MagicMock):
        """Empty string ID should be wrapped as a string response."""
        mock_broker_port.place_order.return_value = ""
        result = mgr.submit(sample_request)
        assert result.order_id == ""
        assert result.status == "SUBMITTED"


# ═══════════════════════════════════════════════════════════════════════════════
#  Broker Port Contract
# ═══════════════════════════════════════════════════════════════════════════════


class TestBrokerPortContract:
    def test_place_order_method_called(self, mock_broker_port: MagicMock):
        """Verify the manager calls place_order on the broker port."""
        mgr = OrderSubmissionManager(broker_port=mock_broker_port)
        req = OrderRequest(
            symbol="BANKNIFTY", quantity=25, price=None,
            order_type="MARKET", direction="BUY",
        )
        mock_broker_port.place_order.return_value = KernelOrderResult(
            order_id="BK-001", status="SUBMITTED", timestamp="now",
        )
        result = mgr.submit(req)
        assert result.order_id == "BK-001"
        mock_broker_port.place_order.assert_called_once()
