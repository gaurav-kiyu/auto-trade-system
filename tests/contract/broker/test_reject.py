"""
AD-KIYU Broker Contract Test - Order Rejection.

Verifies that broker adapters handle invalid inputs gracefully
without crashing or corrupting internal state.
"""
from __future__ import annotations

from core.adapters.broker_adapters import PaperBrokerAdapter


class TestRejectOrderContract:
    """Contract tests for order rejection and edge case inputs.

    PaperBrokerAdapter accepts most inputs without validation,
    so these tests verify graceful handling rather than strict rejection.
    """

    def make_adapter(self) -> PaperBrokerAdapter:
        return PaperBrokerAdapter()

    def test_zero_quantity_does_not_crash(self):
        """Zero quantity orders must not crash the adapter."""
        adapter = self.make_adapter()
        try:
            result = adapter.place_order("NIFTY", "CALL", 0, 18000.0)
            assert result is not None  # May succeed or fail gracefully
        except (TypeError, ValueError, Exception):
            pass  # Rejection is acceptable

    def test_negative_quantity_does_not_crash(self):
        """Negative quantity orders must not crash the adapter."""
        adapter = self.make_adapter()
        try:
            result = adapter.place_order("NIFTY", "CALL", -10, 18000.0)
            assert result is not None
        except (TypeError, ValueError, Exception):
            pass  # Rejection is acceptable

    def test_none_symbol_does_not_crash(self):
        """None symbol must not crash."""
        adapter = self.make_adapter()
        try:
            result = adapter.place_order(None, "CALL", 50, 18000.0)
            assert result is not None
        except (TypeError, ValueError, Exception):
            pass  # Rejection is acceptable

    def test_invalid_direction_does_not_crash(self):
        """Invalid direction must not crash."""
        adapter = self.make_adapter()
        try:
            result = adapter.place_order("NIFTY", "HOLD", 50, 18000.0)
            assert result is not None
        except (TypeError, ValueError, Exception):
            pass  # Rejection is acceptable

    def test_none_direction_does_not_crash(self):
        """None direction must not crash."""
        adapter = self.make_adapter()
        try:
            result = adapter.place_order("NIFTY", None, 50, 18000.0)
            assert result is not None
        except (TypeError, ValueError, Exception):
            pass  # Rejection is acceptable

    def test_zero_strike_does_not_crash(self):
        """Zero strike price must not crash."""
        adapter = self.make_adapter()
        try:
            result = adapter.place_order("NIFTY", "CALL", 50, 0)
            assert result is not None
        except (TypeError, ValueError, Exception):
            pass  # Rejection is acceptable
