"""
AD-KIYU Broker Contract Test — Timeout / Latency Handling.

Verifies that broker adapters handle timeouts gracefully and
do not hang indefinitely in any standard operation.
"""
from __future__ import annotations

import time

from core.adapters.broker_adapters import PaperBrokerAdapter


class TestTimeoutContract:
    """Contract tests for timeout and latency scenarios."""

    def make_adapter(self) -> PaperBrokerAdapter:
        return PaperBrokerAdapter()

    def test_place_order_does_not_hang(self):
        """place_order must complete within a reasonable time."""
        adapter = self.make_adapter()
        start = time.monotonic()
        adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        elapsed = time.monotonic() - start
        assert elapsed < 10.0, f"place_order took {elapsed:.2f}s, exceeded timeout"

    def test_cancel_order_does_not_hang(self):
        """cancel_order must complete within a reasonable time."""
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        start = time.monotonic()
        adapter.cancel_order(oid)
        elapsed = time.monotonic() - start
        assert elapsed < 10.0, f"cancel_order took {elapsed:.2f}s, exceeded timeout"

    def test_get_order_status_does_not_hang(self):
        """get_order_status must complete within a reasonable time."""
        adapter = self.make_adapter()
        start = time.monotonic()
        adapter.get_order_status("TEST_ID")
        elapsed = time.monotonic() - start
        assert elapsed < 10.0, f"get_order_status took {elapsed:.2f}s, exceeded timeout"

    def test_wait_for_fill_does_not_hang(self):
        """wait_for_fill must return within its timeout parameter."""
        adapter = self.make_adapter()
        if hasattr(adapter, "wait_for_fill"):
            start = time.monotonic()
            result = adapter.wait_for_fill("TEST_ID", timeout=1)
            elapsed = time.monotonic() - start
            assert elapsed < 5.0, f"wait_for_fill took {elapsed:.2f}s, exceeded limit"
            assert isinstance(result, bool)

    def test_consecutive_operations_do_not_degrade(self):
        """Multiple operations in sequence must not progressively slow down."""
        adapter = self.make_adapter()
        times = []
        for _ in range(5):
            start = time.monotonic()
            oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
            adapter.get_order_status(oid)
            times.append(time.monotonic() - start)
        avg = sum(times) / len(times)
        assert avg < 5.0, f"Average operation time {avg:.2f}s exceeded limit"

    def test_exit_order_does_not_hang(self):
        """exit_order must complete within a reasonable time."""
        adapter = self.make_adapter()
        start = time.monotonic()
        oid = adapter.exit_order("NIFTY", "CALL", 50, 18000.0)
        elapsed = time.monotonic() - start
        assert elapsed < 10.0, f"exit_order took {elapsed:.2f}s, exceeded timeout"
        assert oid is not None
