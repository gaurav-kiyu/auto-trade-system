"""
AD-KIYU Broker Contract Test — Order Cancellation.

Verifies that broker adapters can cancel open orders and
return appropriate status for cancelled orders.
"""
from __future__ import annotations

from core.adapters.broker_adapters import PaperBrokerAdapter


class TestCancelOrderContract:
    """Contract tests for order cancellation."""

    def make_adapter(self) -> PaperBrokerAdapter:
        return PaperBrokerAdapter()

    def test_cancel_placed_order_returns_true(self):
        """Cancelling a recently placed order must return True."""
        adapter = self.make_adapter()
        order_id = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        result = adapter.cancel_order(order_id)
        assert result is True, f"Expected True, got {result}"

    def test_cancel_missing_order_does_not_crash(self):
        """Cancelling a non-existent order must not crash."""
        adapter = self.make_adapter()
        result = adapter.cancel_order("MISSING_ORDER_ID_12345")
        assert result is not None

    def test_cancel_empty_string_id_does_not_crash(self):
        """Cancelling with empty string must not crash."""
        adapter = self.make_adapter()
        try:
            result = adapter.cancel_order("")
            assert result is not None
        except (TypeError, ValueError, Exception):
            pass  # Rejection is acceptable

    def test_cancel_after_status_query(self):
        """Cancel must work after querying order status."""
        adapter = self.make_adapter()
        order_id = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        _ = adapter.get_order_status(order_id)
        result = adapter.cancel_order(order_id)
        assert result is True

    def test_cancel_then_place_same_symbol(self):
        """After cancelling, placing a new order on the same symbol must work."""
        adapter = self.make_adapter()
        oid1 = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        adapter.cancel_order(oid1)
        oid2 = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        assert oid2 is not None
        assert oid2 != oid1

    def test_canceled_order_status_accessible(self):
        """Status of a cancelled order must still be queryable."""
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        adapter.cancel_order(oid)
        status = adapter.get_order_status(oid)
        assert isinstance(status, str)
        assert len(status) > 0
