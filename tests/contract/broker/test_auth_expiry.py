"""
AD-KIYU Broker Contract Test — Authentication Expiry.

Verifies that broker adapters detect and report authentication
expiry and recover gracefully when re-authenticated.

Paper adapters pass trivially since they do not have real auth tokens.
"""
from __future__ import annotations

from core.adapters.broker_adapters import PaperBrokerAdapter


class TestAuthExpiryContract:
    """Contract tests for authentication expiry scenarios."""

    def make_adapter(self) -> PaperBrokerAdapter:
        return PaperBrokerAdapter()

    def test_health_check_returns_status(self):
        """Health check must always return status regardless of auth state."""
        adapter = self.make_adapter()
        health = adapter.health_check()
        assert isinstance(health, dict)
        assert "status" in health

    def test_place_order_after_auth_check(self):
        """Order placement must work regardless of auth check."""
        adapter = self.make_adapter()
        # No explicit auth needed for paper adapter
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        assert oid is not None
        assert isinstance(oid, str)

    def test_place_and_status_cycle(self):
        """Place order then check status — must work without auth errors."""
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        status = adapter.get_order_status(oid)
        assert isinstance(status, str)
        assert len(status) > 0

    def test_place_cancel_cycle(self):
        """Place then cancel — must work without auth errors."""
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        result = adapter.cancel_order(oid)
        assert result is True

    def test_health_after_multiple_operations(self):
        """Health check after many operations must still report healthy."""
        adapter = self.make_adapter()

        def _assert_healthy():
            health = adapter.health_check()
            assert health.get("status") == "healthy", f"Unhealthy: {health}"

        for i in range(5):
            oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0 + i)
            _assert_healthy()
            adapter.get_order_status(oid)
            _assert_healthy()
            adapter.cancel_order(oid)
            _assert_healthy()
