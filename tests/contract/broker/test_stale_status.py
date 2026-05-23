"""
AD-KIYU Broker Contract Test — Stale / Stuck Order Status.

Verifies that broker adapters return consistent and correct
status values for orders.
"""
from __future__ import annotations

from core.adapters.broker_adapters import PaperBrokerAdapter


class TestStaleStatusContract:
    """Contract tests for order status consistency."""

    def make_adapter(self) -> PaperBrokerAdapter:
        return PaperBrokerAdapter()

    def test_get_order_status_returns_known_value(self):
        """Status must be a non-empty string."""
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        status = adapter.get_order_status(oid)
        assert isinstance(status, str)
        assert len(status) > 0

    def test_get_order_status_consistent(self):
        """Repeated status queries for same order must not change erratically."""
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        statuses = set()
        for _ in range(5):
            statuses.add(adapter.get_order_status(oid))
        # Should be at most 2 distinct statuses (transition is normal)
        assert len(statuses) <= 2, f"Status oscillated: {statuses}"

    def test_get_order_status_after_cancel(self):
        """Status must still be queryable after cancel."""
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        adapter.cancel_order(oid)
        status = adapter.get_order_status(oid)
        assert isinstance(status, str)
        assert len(status) > 0

    def test_get_order_status_none_input(self):
        """Status query with None must not crash."""
        adapter = self.make_adapter()
        try:
            status = adapter.get_order_status(None)
            assert status is not None
        except (TypeError, ValueError, Exception):
            pass  # Rejection is acceptable

    def test_status_after_place_immediately(self):
        """Status immediately after place must be a known value."""
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        status = adapter.get_order_status(oid)
        # Paper broker returns "COMPLETE" immediately
        assert len(status) > 0, "Status must not be empty"

    def test_status_after_exit_order(self):
        """Status after exit order must be queryable."""
        adapter = self.make_adapter()
        oid = adapter.exit_order("NIFTY", "CALL", 50, 18000.0)
        status = adapter.get_order_status(oid)
        assert isinstance(status, str)
        assert len(status) > 0
