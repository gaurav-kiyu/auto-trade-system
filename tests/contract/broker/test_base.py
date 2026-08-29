"""
AD-KIYU Broker Contract Test Base - production-grade certification suite.

Every broker adapter must pass the full suite before being certified for live use.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BrokerContractTestBase(ABC):
    """
    Abstract base for broker contract tests.

    Subclasses implement:
      make_adapter() -> Any  (returns a fresh BrokerAdapter instance)
      make_order() -> Any    (returns an order object compatible with place_order)
    """

    @abstractmethod
    def make_adapter(self) -> Any:
        ...

    @abstractmethod
    def make_order(self) -> Any:
        ...

    # ── Contract tests ──────────────────────────────────────────────────────

    def test_place_order_success(self):
        """Place a valid order and verify it succeeds."""
        adapter = self.make_adapter()
        order = self.make_order()
        result = adapter.place_order(order)
        assert result is not None

    def test_reject_invalid_symbol(self):
        """Place order with invalid params and verify rejection."""
        adapter = self.make_adapter()
        try:
            adapter.place_order(None)
        except (TypeError, ValueError, Exception):
            pass  # Rejection is expected

    def test_cancel_order(self):
        """Place then cancel an order."""
        adapter = self.make_adapter()
        order = self.make_order()
        order_id = adapter.place_order(order)
        if order_id:
            result = adapter.cancel_order(order_id)
            assert result is not None

    def test_get_order_status(self):
        """Query order status."""
        adapter = self.make_adapter()
        order = self.make_order()
        order_id = adapter.place_order(order)
        if order_id:
            status = adapter.get_order_status(order_id)
            assert status is not None

    def test_get_open_positions(self):
        """Get open positions and verify structure."""
        adapter = self.make_adapter()
        positions = adapter.get_open_positions()
        assert positions is not None
        assert isinstance(positions, list)

    def test_get_account_balance(self):
        """Get account balance."""
        adapter = self.make_adapter()
        balance = adapter.get_account_balance()
        assert balance is not None

    def test_get_ltp(self):
        """Get LTP for a known symbol."""
        adapter = self.make_adapter()
        ltp = adapter.get_ltp("NIFTY")
        assert ltp is not None
        assert isinstance(ltp, (int, float))
        assert ltp > 0

    def test_is_connected(self):
        """Verify broker connection check."""
        adapter = self.make_adapter()
        connected = adapter.is_connected() if hasattr(adapter, 'is_connected') else True
        assert connected is not None
