"""
AD-KIYU Broker Contract Test — Connection / Reconnection.

Verifies that broker adapters can handle multiple sequential
operations without connection-related errors.
"""
from __future__ import annotations

from core.adapters.broker_adapters import PaperBrokerAdapter


class TestReconnectContract:
    """Contract tests for connection resilience.

    PaperBrokerAdapter has no transport layer so these verify
    basic operational continuity across sequential calls.
    """

    def make_adapter(self) -> PaperBrokerAdapter:
        return PaperBrokerAdapter()

    def test_place_order_without_explicit_connect(self):
        """Order placement must work without an explicit connect() call."""
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        assert oid is not None
        assert isinstance(oid, str)

    def test_health_check_before_and_after_place(self):
        """Health check must be callable at any point."""
        adapter = self.make_adapter()
        pre = adapter.health_check()
        assert isinstance(pre, dict)
        assert "status" in pre

        adapter.place_order("NIFTY", "CALL", 50, 18000.0)

        post = adapter.health_check()
        assert isinstance(post, dict)
        assert "status" in post

    def test_health_check_returns_healthy_for_paper(self):
        """Paper adapter health check must report 'healthy'."""
        adapter = self.make_adapter()
        health = adapter.health_check()
        assert health.get("status") == "healthy", f"Unexpected status: {health}"

    def test_health_check_contains_adapter_info(self):
        """Health check must identify the adapter."""
        adapter = self.make_adapter()
        health = adapter.health_check()
        # Must have mode or adapter key
        has_mode = "mode" in health or "adapter" in health
        assert has_mode, f"Health check missing mode info: {health.keys()}"

    def test_sequential_place_and_health(self):
        """Multiple order placements must each succeed with consistent health."""
        adapter = self.make_adapter()
        for i in range(3):
            oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0 + i * 10)
            assert oid is not None
            health = adapter.health_check()
            assert health.get("status") == "healthy"

    def test_exit_order_after_place(self):
        """Exit order must work after place order."""
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        assert oid is not None
        exit_oid = adapter.exit_order("NIFTY", "CALL", 50, 18000.0)
        assert exit_oid is not None
        assert exit_oid != oid

    def test_modify_order_returns_bool(self):
        """Modify order must return a boolean."""
        adapter = self.make_adapter()
        result = adapter.modify_order("TEST_ID", qty=75)
        assert isinstance(result, bool)

    def test_full_lifecycle(self):
        """Full order lifecycle: place → status → cancel → health."""
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        status = adapter.get_order_status(oid)
        assert status is not None
        cancel_ok = adapter.cancel_order(oid)
        assert cancel_ok is True
        health = adapter.health_check()
        assert health.get("status") == "healthy"
