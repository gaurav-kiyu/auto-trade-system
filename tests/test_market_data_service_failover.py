"""Tests for MarketDataService failover - get_quote, get_historical_data, get_latest_data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from core.services.market_data_service import MarketDataService


# ── Mock adapters ─────────────────────────────────────────────────────────────


class MockMarketDataAdapter:
    """A controllable mock that implements MarketDataPort."""

    def __init__(
        self,
        name: str = "mock",
        quote_return: Any = None,
        historical_return: list[dict[str, Any]] | None = None,
        latest_return: Any = None,
        fail_connect: bool = False,
        fail_get_quote: bool = False,
        fail_historical: bool = False,
        fail_latest: bool = False,
    ):
        self.name = name
        self.connected = False
        self._quote_return = quote_return
        self._historical_return = historical_return or []
        self._latest_return = latest_return
        self._fail_connect = fail_connect
        self._fail_get_quote = fail_get_quote
        self._fail_historical = fail_historical
        self._fail_latest = fail_latest
        self.call_log: list[str] = []

    def connect(self) -> bool:
        self.call_log.append(f"connect:{self.name}")
        if self._fail_connect:
            return False
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.call_log.append(f"disconnect:{self.name}")
        self.connected = False

    def get_quote(self, symbol: str) -> Any:
        self.call_log.append(f"get_quote:{self.name}:{symbol}")
        if self._fail_get_quote:
            raise ConnectionError(f"{self.name} get_quote failed")
        return self._quote_return

    def get_latest_data(self, symbol: str) -> Any:
        self.call_log.append(f"get_latest:{self.name}:{symbol}")
        if self._fail_latest:
            raise ConnectionError(f"{self.name} get_latest failed")
        return self._latest_return

    def is_data_fresh(self, market_data: Any, max_age_seconds: int = 30) -> bool:
        return market_data is not None

    def subscribe_to_market_data(
        self, symbols: list[str], callback: Any
    ) -> bool:
        self.call_log.append(f"subscribe:{self.name}:{symbols}")
        return True

    def unsubscribe_from_market_data(self, symbol: str) -> bool:
        self.call_log.append(f"unsubscribe:{self.name}:{symbol}")
        return True

    def get_historical_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
    ) -> list[dict[str, Any]]:
        self.call_log.append(f"historical:{self.name}:{symbol}:{interval}")
        if self._fail_historical:
            raise ConnectionError(f"{self.name} historical failed")
        return self._historical_return

    def get_option_chain(
        self,
        symbol: str,
        expiry_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return []

    def get_instrument_details(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "exchange": "NSE"}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def empty_service() -> MarketDataService:
    return MarketDataService()


@pytest.fixture
def service_with_two_adapters() -> MarketDataService:
    """Primary (high pri) returns data; secondary (low pri) never called."""
    svc = MarketDataService()
    svc.register(
        "primary",
        MockMarketDataAdapter(
            name="primary",
            quote_return={"symbol": "NIFTY", "price": 23500.0},
            historical_return=[{"date": "2024-01-01", "close": 23500}],
            latest_return={"close": 23500.0},
        ),
        asset_classes=["index"],
        priority=100,
    )
    svc.register(
        "secondary",
        MockMarketDataAdapter(name="secondary", quote_return=None, historical_return=[], latest_return=None),
        asset_classes=["index"],
        priority=10,
    )
    return svc


# ── get_quote failover tests ─────────────────────────────────────────────────


class TestFailoverGetQuote:
    """MarketDataService.get_quote() failover behavior."""

    def test_no_adapters_returns_none(self, empty_service: MarketDataService):
        result = empty_service.get_quote("NIFTY", "index")
        assert result is None

    def test_primary_returns_quote(self, service_with_two_adapters: MarketDataService):
        result = service_with_two_adapters.get_quote("NIFTY", "index")
        assert result is not None
        assert result["symbol"] == "NIFTY"
        assert result["price"] == 23500.0

    def test_primary_none_falls_back_to_secondary(self):
        """Primary returns None → secondary is called."""
        svc = MarketDataService()
        primary = MockMarketDataAdapter(name="primary", quote_return=None)
        secondary = MockMarketDataAdapter(
            name="secondary", quote_return={"symbol": "NIFTY", "price": 23400.0}
        )
        svc.register("primary", primary, asset_classes=["index"], priority=100)
        svc.register("secondary", secondary, asset_classes=["index"], priority=10)

        result = svc.get_quote("NIFTY", "index")
        assert result is not None
        assert result["price"] == 23400.0
        assert "get_quote:primary:NIFTY" in primary.call_log
        assert "get_quote:secondary:NIFTY" in secondary.call_log

    def test_primary_exception_falls_back(self):
        """Primary raises → secondary is called."""
        svc = MarketDataService()
        primary = MockMarketDataAdapter(name="primary", fail_get_quote=True)
        secondary = MockMarketDataAdapter(
            name="secondary", quote_return={"symbol": "NIFTY", "price": 23300.0}
        )
        svc.register("primary", primary, asset_classes=["index"], priority=100)
        svc.register("secondary", secondary, asset_classes=["index"], priority=10)

        result = svc.get_quote("NIFTY", "index")
        assert result is not None
        assert result["price"] == 23300.0
        assert "get_quote:primary:NIFTY" in primary.call_log

    def test_all_exhausted_returns_none(self):
        """All adapters return None → returns None."""
        svc = MarketDataService()
        svc.register(
            "a",
            MockMarketDataAdapter(name="a", quote_return=None),
            asset_classes=["index"],
            priority=100,
        )
        svc.register(
            "b",
            MockMarketDataAdapter(name="b", quote_return=None),
            asset_classes=["index"],
            priority=10,
        )
        result = svc.get_quote("NIFTY", "index")
        assert result is None

    def test_wrong_asset_class_not_called(self):
        """Adapter for different asset class is not used."""
        svc = MarketDataService()
        equity_adapter = MockMarketDataAdapter(
            name="equity_only", quote_return={"symbol": "RELIANCE"}
        )
        index_adapter = MockMarketDataAdapter(
            name="index_only", quote_return=None
        )
        svc.register(
            "equity", equity_adapter, asset_classes=["equity"], priority=100
        )
        svc.register(
            "index", index_adapter, asset_classes=["index"], priority=10
        )
        result = svc.get_quote("NIFTY", "index")
        # equity adapter should NOT be called for index asset class
        assert "get_quote:equity_only:NIFTY" not in equity_adapter.call_log


# ── get_historical_data failover tests ────────────────────────────────────────


class TestFailoverGetHistoricalData:
    """MarketDataService.get_historical_data() failover behavior."""

    def test_empty_service_returns_empty(self, empty_service: MarketDataService):
        result = empty_service.get_historical_data(
            "NIFTY", datetime(2024, 1, 1), datetime(2024, 1, 31)
        )
        assert result == []

    def test_primary_returns_data(self, service_with_two_adapters: MarketDataService):
        result = service_with_two_adapters.get_historical_data(
            "NIFTY", datetime(2024, 1, 1), datetime(2024, 1, 31), "day", "index"
        )
        assert len(result) == 1
        assert result[0]["close"] == 23500

    def test_primary_empty_falls_back(self):
        """Primary returns empty list → secondary is called."""
        svc = MarketDataService()
        primary = MockMarketDataAdapter(name="primary", historical_return=[])
        secondary = MockMarketDataAdapter(
            name="secondary",
            historical_return=[{"date": "2024-01-01", "close": 23400}],
        )
        svc.register("primary", primary, asset_classes=["index"], priority=100)
        svc.register("secondary", secondary, asset_classes=["index"], priority=10)

        result = svc.get_historical_data(
            "NIFTY", datetime(2024, 1, 1), datetime(2024, 1, 31), "day", "index"
        )
        assert len(result) == 1
        assert "historical:primary:NIFTY:day" in primary.call_log
        assert "historical:secondary:NIFTY:day" in secondary.call_log

    def test_all_empty_returns_empty(self):
        """All adapters return empty → returns empty list."""
        svc = MarketDataService()
        svc.register(
            "a",
            MockMarketDataAdapter(name="a", historical_return=[]),
            asset_classes=["index"],
            priority=100,
        )
        svc.register(
            "b",
            MockMarketDataAdapter(name="b", historical_return=[]),
            asset_classes=["index"],
            priority=10,
        )
        result = svc.get_historical_data(
            "NIFTY", datetime(2024, 1, 1), datetime(2024, 1, 31), "day", "index"
        )
        assert result == []

    def test_exception_falls_back(self):
        """Primary raises → secondary is called."""
        svc = MarketDataService()
        primary = MockMarketDataAdapter(name="primary", fail_historical=True)
        secondary = MockMarketDataAdapter(
            name="secondary",
            historical_return=[{"date": "2024-01-01", "close": 23300}],
        )
        svc.register("primary", primary, asset_classes=["index"], priority=100)
        svc.register("secondary", secondary, asset_classes=["index"], priority=10)

        result = svc.get_historical_data(
            "NIFTY", datetime(2024, 1, 1), datetime(2024, 1, 31), "day", "index"
        )
        assert len(result) == 1
        assert result[0]["close"] == 23300


# ── get_latest_data failover tests ────────────────────────────────────────────


class TestFailoverGetLatestData:
    """MarketDataService.get_latest_data() failover behavior."""

    def test_empty_returns_none(self, empty_service: MarketDataService):
        result = empty_service.get_latest_data("NIFTY", "index")
        assert result is None

    def test_primary_returns_latest(self, service_with_two_adapters: MarketDataService):
        result = service_with_two_adapters.get_latest_data("NIFTY", "index")
        assert result is not None
        assert result["close"] == 23500.0

    def test_primary_none_falls_back(self):
        """Primary returns None → secondary is called."""
        svc = MarketDataService()
        primary = MockMarketDataAdapter(name="primary", latest_return=None)
        secondary = MockMarketDataAdapter(
            name="secondary", latest_return={"close": 23400.0}
        )
        svc.register("primary", primary, asset_classes=["index"], priority=100)
        svc.register("secondary", secondary, asset_classes=["index"], priority=10)

        result = svc.get_latest_data("NIFTY", "index")
        assert result is not None
        assert result["close"] == 23400.0
        assert "get_latest:primary:NIFTY" in primary.call_log
        assert "get_latest:secondary:NIFTY" in secondary.call_log

    def test_all_none_returns_none(self):
        """All adapters return None → returns None."""
        svc = MarketDataService()
        svc.register(
            "a",
            MockMarketDataAdapter(name="a", latest_return=None),
            asset_classes=["index"],
            priority=100,
        )
        svc.register(
            "b",
            MockMarketDataAdapter(name="b", latest_return=None),
            asset_classes=["index"],
            priority=10,
        )
        result = svc.get_latest_data("NIFTY", "index")
        assert result is None


# ── get_instrument_details failover tests ─────────────────────────────────────


class TestFailoverGetInstrumentDetails:
    """MarketDataService.get_instrument_details() failover behavior."""

    def test_empty_returns_default(self, empty_service: MarketDataService):
        result = empty_service.get_instrument_details("NIFTY", "index")
        assert result == {"symbol": "NIFTY", "note": "unresolved"}

    def test_primary_returns_details(self, service_with_two_adapters: MarketDataService):
        result = service_with_two_adapters.get_instrument_details("NIFTY", "index")
        assert result["symbol"] == "NIFTY"
        assert "exchange" in result

    def test_primary_empty_falls_back(self):
        """Primary returns empty dict → secondary is called."""
        svc = MarketDataService()
        primary = MockMarketDataAdapter(name="primary")
        primary.get_instrument_details = lambda s: {"symbol": s}
        secondary = MockMarketDataAdapter(name="secondary")

        svc.register("primary", primary, asset_classes=["index"], priority=100)
        svc.register("secondary", secondary, asset_classes=["index"], priority=10)

        result = svc.get_instrument_details("BANKNIFTY", "index")
        # Primary should be called first
        assert result.get("symbol") == "BANKNIFTY"


# ── subscribe_to_market_data tests ────────────────────────────────────────────


class TestSubscribeMarketData:
    """MarketDataService.subscribe_to_market_data() behavior."""

    def test_subscribe_no_adapters_empty(self, empty_service: MarketDataService):
        result = empty_service.subscribe_to_market_data(["NIFTY"], None)
        assert result == {}

    def test_subscribe_calls_all_adapters(self):
        svc = MarketDataService()
        a1 = MockMarketDataAdapter(name="a1")
        a2 = MockMarketDataAdapter(name="a2")
        svc.register("a1", a1, asset_classes=["index"], priority=100)
        svc.register("a2", a2, asset_classes=["index"], priority=10)

        result = svc.subscribe_to_market_data(["NIFTY", "BANKNIFTY"], lambda x: None)
        assert result["a1"] is True
        assert result["a2"] is True
        assert "subscribe:a1:['NIFTY', 'BANKNIFTY']" in a1.call_log
        assert "subscribe:a2:['NIFTY', 'BANKNIFTY']" in a2.call_log
