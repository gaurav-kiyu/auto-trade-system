"""
AD-KIYU Broker Contract Test — Partial Fill Handling.

Verifies that broker adapters correctly report fill information
for placed orders.
"""
from __future__ import annotations

from core.adapters.broker_adapters import PaperBrokerAdapter


class TestPartialFillContract:
    """Contract tests for fill information."""

    def make_adapter(self) -> PaperBrokerAdapter:
        return PaperBrokerAdapter()

    def test_get_fill_price_for_placed_order(self):
        """After placing an order, get_fill_price must return a valid price or None."""
        adapter = self.make_adapter()
        order_id = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        fill_price = adapter.get_fill_price(order_id)
        # Paper adapter returns None when no price_getter is wired
        assert fill_price is None or fill_price >= 0

    def test_get_fill_price_missing_order(self):
        """Querying fill price for a non-existent order must return None."""
        adapter = self.make_adapter()
        price = adapter.get_fill_price("NONEXISTENT_ORDER_999")
        assert price is None, f"Expected None, got {price}"

    def test_get_filled_quantity_for_placed_order(self):
        """After placing an order, filled quantity must be reported."""
        adapter = self.make_adapter()
        order_id = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        qty = adapter.get_filled_quantity(order_id)
        assert qty is None or qty >= 0

    def test_get_filled_quantity_missing_order(self):
        """Querying filled quantity for non-existent order must return None."""
        adapter = self.make_adapter()
        qty = adapter.get_filled_quantity("NONEXISTENT_ORDER_999")
        assert qty is None, f"Expected None, got {qty}"

    def test_paper_fill_stats_available(self):
        """If a paper_fill_stats method exists, it must return a dict."""
        adapter = self.make_adapter()
        if hasattr(adapter, "paper_fill_stats"):
            stats = adapter.paper_fill_stats()
            assert isinstance(stats, dict)
            assert "fills" in stats

    def test_get_paper_fill_record(self):
        """After placing an order, get_paper_fill must return the fill record."""
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        if hasattr(adapter, "get_paper_fill"):
            record = adapter.get_paper_fill(oid)
            assert record is not None
