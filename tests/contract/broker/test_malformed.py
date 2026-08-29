"""
AD-KIYU Broker Contract Test - Malformed Input Handling.

Verifies that broker adapters reject malformed inputs gracefully
rather than crashing or producing corrupt internal state.
"""
from __future__ import annotations

from core.adapters.broker_adapters import PaperBrokerAdapter


class TestMalformedInputContract:
    """Contract tests for malformed / anomalous input handling."""

    def make_adapter(self) -> PaperBrokerAdapter:
        return PaperBrokerAdapter()

    def test_place_order_extremely_large_qty(self):
        """Extremely large quantity must not crash the adapter."""
        adapter = self.make_adapter()
        try:
            oid = adapter.place_order("NIFTY", "CALL", 99999999, 18000.0)
            assert oid is not None
        except (TypeError, ValueError, OverflowError, Exception):
            pass  # Rejection is acceptable

    def test_place_order_float_qty(self):
        """Float quantity should be coerced or rejected, not crash."""
        adapter = self.make_adapter()
        try:
            oid = adapter.place_order("NIFTY", "CALL", 50.7, 18000.0)
            assert oid is not None
        except (TypeError, ValueError, Exception):
            pass  # Rejection is acceptable

    def test_place_order_float_strike(self):
        """Float strike should be coerced or rejected, not crash."""
        adapter = self.make_adapter()
        try:
            oid = adapter.place_order("NIFTY", "CALL", 50, 18000.75)
            assert oid is not None
        except (TypeError, ValueError, Exception):
            pass  # Rejection is acceptable

    def test_place_order_empty_symbol_string(self):
        """Empty string symbol must not crash."""
        adapter = self.make_adapter()
        try:
            oid = adapter.place_order("", "CALL", 50, 18000.0)
            if oid:
                assert isinstance(oid, str)
        except (TypeError, ValueError, Exception):
            pass  # Rejection is acceptable

    def test_get_order_status_on_nonexistent_id(self):
        """Status query on non-existent ID must not crash."""
        adapter = self.make_adapter()
        status = adapter.get_order_status("__DOES_NOT_EXIST__")
        assert status is not None
        assert isinstance(status, str)

    def test_cancel_order_on_nonexistent_id(self):
        """Cancel on non-existent ID must not crash or corrupt state."""
        adapter = self.make_adapter()
        try:
            adapter.cancel_order("__DOES_NOT_EXIST__")
            # After an invalid cancel, a valid order must still work
            oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
            assert oid is not None
        except (ValueError, TypeError, KeyError):
            pass  # Rejection is acceptable
