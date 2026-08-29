"""
AD-KIYU Paper Broker Contract Test.
"""
from __future__ import annotations

from core.adapters.broker_adapters import PaperBrokerAdapter


class TestPaperBrokerContract:

    def make_adapter(self):
        return PaperBrokerAdapter()

    def test_place_order_returns_order_id(self):
        adapter = self.make_adapter()
        result = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_order_status(self):
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        status = adapter.get_order_status(oid)
        assert status is not None

    def test_cancel_order(self):
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        result = adapter.cancel_order(oid)
        assert result is not None

    def test_get_fill_price(self):
        adapter = self.make_adapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 18000.0)
        fp = adapter.get_fill_price(oid)
        assert fp is None or fp > 0

    def test_paper_fill_stats(self):
        adapter = self.make_adapter()
        stats = adapter.paper_fill_stats()
        assert stats is not None
