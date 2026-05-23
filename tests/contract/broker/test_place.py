"""
AD-KIYU Broker Contract Test — Order Placement.

Verifies that a broker adapter can place valid orders and returns
a well-formed order ID for every successful submission.
"""
from __future__ import annotations

from core.adapters.broker_adapters import PaperBrokerAdapter


class TestPlaceOrderContract:
    """Contract tests for order placement."""

    def make_adapter(self) -> PaperBrokerAdapter:
        return PaperBrokerAdapter()

    def make_order(self) -> tuple:
        return ("NIFTY", "CALL", 50, 18000.0)

    def test_place_order_returns_string_id(self):
        """Order ID must be a non-empty string."""
        adapter = self.make_adapter()
        order_id = adapter.place_order(*self.make_order())
        assert isinstance(order_id, str), f"Expected str, got {type(order_id)}"
        assert len(order_id) > 0, "Order ID must not be empty"

    def test_place_order_increments_counter(self):
        """Consecutive placements produce unique IDs."""
        adapter = self.make_adapter()
        id1 = adapter.place_order(*self.make_order())
        id2 = adapter.place_order(*self.make_order())
        assert id1 != id2, "Order IDs must be unique"

    def test_place_order_sell_direction(self):
        """Sell orders must also return valid order IDs."""
        adapter = self.make_adapter()
        order_id = adapter.place_order("NIFTY", "PUT", 50, 18200.0)
        assert isinstance(order_id, str)
        assert len(order_id) > 0

    def test_place_order_large_quantity(self):
        """Large quantities must still be accepted."""
        adapter = self.make_adapter()
        order_id = adapter.place_order("BANKNIFTY", "CALL", 500, 42000.0)
        assert isinstance(order_id, str)
        assert len(order_id) > 0

    def test_place_order_multiple_instruments(self):
        """Different instruments in quick succession must all succeed."""
        adapter = self.make_adapter()
        ids = [
            adapter.place_order("NIFTY", "CALL", 50, 18000.0),
            adapter.place_order("BANKNIFTY", "PUT", 30, 42000.0),
            adapter.place_order("FINNIFTY", "CALL", 75, 20000.0),
        ]
        assert len(set(ids)) == 3, "All order IDs must be unique"
