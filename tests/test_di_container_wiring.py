"""Tests for DI container wiring - verifies all services, adapters, and ports
resolve correctly through the dependency injection container.

Tests cover:
  - DIContainer basic unit operations
  - wire_default_services idempotency
  - Capital Allocation Port resolution
  - Multi-Asset Portfolio Aggregator resolution
  - Market data adapter registrations
  - Container isolation (reset_container)
"""

from __future__ import annotations

from typing import Any

import pytest

from core.di_container import (
    DIContainer,
    get_container,
    reset_container,
    wire_default_services,
)


# ═══════════════════════════════════════════════════════════════════════════
# DIContainer Unit Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDIContainerBasics:
    def test_construct_empty(self):
        c = DIContainer()
        assert c.is_registered(str) is False

    def test_register_and_resolve_singleton(self):
        c = DIContainer()
        c.register_singleton(dict, dict)
        instance = c.resolve(dict)
        assert isinstance(instance, dict)
        # Singleton - same instance on second resolve
        assert c.resolve(dict) is instance

    def test_register_and_resolve_transient(self):
        c = DIContainer()
        c.register_transient(list, list)
        a = c.resolve(list)
        b = c.resolve(list)
        assert a is not b  # Different instances

    def test_register_instance(self):
        c = DIContainer()
        obj = {"key": "value"}
        c.register_instance(dict, obj)
        assert c.resolve(dict) is obj

    def test_register_factory(self):
        c = DIContainer()
        counter: list[int] = [0]

        def factory() -> int:
            counter[0] += 1
            return counter[0]

        c.register_factory(int, factory)
        assert c.resolve(int) == 1
        assert c.resolve(int) == 2  # Factory called each time

    def test_resolve_unregistered_raises(self):
        c = DIContainer()
        with pytest.raises(KeyError, match="No registration found for interface"):
            c.resolve(float)

    def test_try_resolve_returns_none(self):
        c = DIContainer()
        assert c.try_resolve(float) is None

    def test_try_resolve_registered(self):
        c = DIContainer()
        c.register_singleton(str, str)
        assert c.try_resolve(str) is not None

    def test_clear(self):
        c = DIContainer()
        c.register_singleton(dict, dict)
        c.clear()
        assert c.is_registered(dict) is False


class TestDIContainerIsRegistered:
    def test_detects_singleton(self):
        c = DIContainer()
        c.register_singleton(int, int)
        assert c.is_registered(int) is True

    def test_detects_transient(self):
        c = DIContainer()
        c.register_transient(float, float)
        assert c.is_registered(float) is True

    def test_detects_factory(self):
        c = DIContainer()
        c.register_factory(str, lambda: "")
        assert c.is_registered(str) is True

    def test_false_for_unregistered(self):
        c = DIContainer()
        assert c.is_registered(list) is False


# ═══════════════════════════════════════════════════════════════════════════
# wire_default_services Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestWireDefaultServices:
    def test_wires_capital_allocation_port(self):
        """Verify CapitalAllocationPort is registered after wiring."""
        try:
            from core.ports.capital_allocation import CapitalAllocationPort
        except ImportError:
            pytest.skip("CapitalAllocationPort not available")

        c = DIContainer()
        wire_default_services(c)
        assert c.is_registered(CapitalAllocationPort) is True

    def test_resolves_capital_allocation_service(self):
        try:
            from core.ports.capital_allocation import CapitalAllocationPort
        except ImportError:
            pytest.skip("CapitalAllocationPort not available")

        c = DIContainer()
        wire_default_services(c)
        instance = c.resolve(CapitalAllocationPort)
        assert instance is not None
        assert hasattr(instance, "allocate")

    def test_wires_multi_asset_aggregator(self):
        try:
            from core.portfolio.adapters import MultiAssetPortfolioAggregator
        except ImportError:
            pytest.skip("MultiAssetPortfolioAggregator not available")

        c = DIContainer()
        wire_default_services(c)
        assert c.is_registered(MultiAssetPortfolioAggregator) is True

    def test_resolves_aggregator_via_factory(self):
        try:
            from core.portfolio.adapters import MultiAssetPortfolioAggregator
        except ImportError:
            pytest.skip("MultiAssetPortfolioAggregator not available")

        c = DIContainer()
        wire_default_services(c)
        aggregator = c.resolve(MultiAssetPortfolioAggregator)
        assert hasattr(aggregator, "aggregate")

    def test_wires_market_data_adapters(self):
        """Verify all three multi-asset market data adapters are registered."""
        try:
            from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
                NseEquityAdapter,
            )
        except ImportError:
            pytest.skip("NseEquityAdapter not available")

        c = DIContainer()
        wire_default_services(c)
        assert c.is_registered(NseEquityAdapter) is True

    def test_resolves_nse_equity_adapter(self):
        try:
            from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
                NseEquityAdapter,
            )
        except ImportError:
            pytest.skip("NseEquityAdapter not available")

        c = DIContainer()
        wire_default_services(c)
        adapter = c.resolve(NseEquityAdapter)
        assert adapter is not None
        assert hasattr(adapter, "connect")

    def test_wires_mcx_commodity_adapter(self):
        try:
            from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
                McxCommodityAdapter,
            )
        except ImportError:
            pytest.skip("McxCommodityAdapter not available")

        c = DIContainer()
        wire_default_services(c)
        assert c.is_registered(McxCommodityAdapter) is True

    def test_wires_cds_currency_adapter(self):
        try:
            from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
                CdsCurrencyAdapter,
            )
        except ImportError:
            pytest.skip("CdsCurrencyAdapter not available")

        c = DIContainer()
        wire_default_services(c)
        assert c.is_registered(CdsCurrencyAdapter) is True

    def test_idempotent_wiring(self):
        """Calling wire_default_services twice should not break anything."""
        try:
            from core.ports.capital_allocation import CapitalAllocationPort
        except ImportError:
            pytest.skip("CapitalAllocationPort not available")

        c = DIContainer()
        wire_default_services(c)
        wire_default_services(c)  # Second call
        assert c.is_registered(CapitalAllocationPort) is True
        # Resolve should work
        instance = c.resolve(CapitalAllocationPort)
        assert instance is not None


class TestGlobalContainer:
    def test_get_container_returns_wired_instance(self):
        c = get_container()
        assert c is not None
        assert isinstance(c, DIContainer)

    def test_reset_container_clears_and_rewires(self):
        reset_container()
        c = get_container()
        assert c is not None

    def test_container_has_capital_allocation(self):
        try:
            from core.ports.capital_allocation import CapitalAllocationPort
        except ImportError:
            pytest.skip("CapitalAllocationPort not available")

        c = get_container()
        assert c.is_registered(CapitalAllocationPort) is True

    def test_market_data_adapter_registered_in_global(self):
        """The global container should have market data adapters registered."""
        try:
            from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
                NseEquityAdapter,
            )
        except ImportError:
            pytest.skip("NseEquityAdapter not available")

        c = get_container()
        assert c.is_registered(NseEquityAdapter) is True


# ═══════════════════════════════════════════════════════════════════════════
# Market Data Service Wiring Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestMarketDataServiceWiring:
    def test_service_can_be_constructed(self):
        try:
            from core.services.market_data_service import MarketDataService
        except ImportError:
            pytest.skip("MarketDataService not available")

        service = MarketDataService()
        assert service is not None
        assert hasattr(service, "register")
        assert hasattr(service, "get_quote")

    def test_register_and_list_adapters(self):
        from core.services.market_data_service import MarketDataService

        service = MarketDataService()

        class DummyAdapter:
            def connect(self): return True
            def disconnect(self): return None
            def get_quote(self, symbol): return None
            def get_latest_data(self, symbol): return None
            def is_data_fresh(self, data, max_age=30): return False
            def subscribe_to_market_data(self, symbols, cb): return False
            def unsubscribe_from_market_data(self, sym): return False
            def get_historical_data(self, sym, f, t, i="day"): return []
            def get_option_chain(self, sym, exp=None): return []
            def get_instrument_details(self, sym): return {"symbol": sym}

        service.register("dummy", DummyAdapter(), asset_classes=["equity"], priority=50)
        adapters = service.list_adapters()
        assert "dummy" in adapters
        assert adapters["dummy"]["asset_classes"] == ["equity"]
        assert adapters["dummy"]["priority"] == 50

    def test_failover_empty_returns_none(self):
        from core.services.market_data_service import MarketDataService

        service = MarketDataService()
        result = service.get_quote("NIFTY", asset_class="index")
        assert result is None  # No adapters registered - natural failover

    def test_failover_primary_first(self):
        """Verify that higher-priority adapters are tried first."""
        from core.services.market_data_service import MarketDataService

        service = MarketDataService()

        calls: list[str] = []

        class TrackingAdapter:
            def __init__(self, name: str):
                self._name = name
            def connect(self): return True
            def disconnect(self): return None
            def get_quote(self, symbol):
                calls.append(self._name)
                if self._name == "primary":
                    return {"symbol": symbol, "price": 100.0}
                return None
            def get_latest_data(self, symbol): return None
            def is_data_fresh(self, data, max_age=30): return False
            def subscribe_to_market_data(self, symbols, cb): return False
            def unsubscribe_from_market_data(self, sym): return False
            def get_historical_data(self, sym, f, t, i="day"): return []
            def get_option_chain(self, sym, exp=None): return []
            def get_instrument_details(self, sym): return {"symbol": sym}

        service.register("primary", TrackingAdapter("primary"), asset_classes=["equity"], priority=100)
        service.register("fallback", TrackingAdapter("fallback"), asset_classes=["equity"], priority=10)

        result = service.get_quote("TEST")
        assert result is not None
        assert result["symbol"] == "TEST"
        # Only primary should have been called since it returned data
        assert calls == ["primary"]

    def test_failover_to_secondary(self):
        """When primary returns None, fallback should be tried."""
        from core.services.market_data_service import MarketDataService

        service = MarketDataService()

        calls: list[str] = []

        class NoneAdapter:
            def __init__(self, name: str):
                self._name = name
            def connect(self): return True
            def disconnect(self): return None
            def get_quote(self, symbol):
                calls.append(self._name)
                return None  # Primary returns nothing
            def get_latest_data(self, symbol): return None
            def is_data_fresh(self, data, max_age=30): return False
            def subscribe_to_market_data(self, symbols, cb): return False
            def unsubscribe_from_market_data(self, sym): return False
            def get_historical_data(self, sym, f, t, i="day"): return []
            def get_option_chain(self, sym, exp=None): return []
            def get_instrument_details(self, sym): return {"symbol": sym}

        service.register("primary", NoneAdapter("primary"), asset_classes=["equity"], priority=100)
        service.register("fallback", NoneAdapter("fallback"), asset_classes=["equity"], priority=10)

        result = service.get_quote("TEST")
        assert result is None  # Both returned None
        assert calls == ["primary", "fallback"]

    def test_unregister_removes_adapter(self):
        from core.services.market_data_service import MarketDataService

        service = MarketDataService()
        service.register("temp", None, asset_classes=["equity"])
        service.unregister("temp")
        assert "temp" not in service.list_adapters()

    def test_connect_all_disconnect_all(self):
        from core.services.market_data_service import MarketDataService

        service = MarketDataService()

        class SimpleAdapter:
            def __init__(self):
                self.connected = False
            def connect(self):
                self.connected = True
                return True
            def disconnect(self):
                self.connected = False
            def get_quote(self, symbol): return None
            def get_latest_data(self, symbol): return None
            def is_data_fresh(self, data, max_age=30): return False
            def subscribe_to_market_data(self, symbols, cb): return False
            def unsubscribe_from_market_data(self, sym): return False
            def get_historical_data(self, sym, f, t, i="day"): return []
            def get_option_chain(self, sym, exp=None): return []
            def get_instrument_details(self, sym): return {"symbol": sym}

        a1 = SimpleAdapter()
        a2 = SimpleAdapter()
        service.register("a1", a1, asset_classes=["equity"])
        service.register("a2", a2, asset_classes=["index"])

        results = service.connect_all()
        assert results["a1"] is True
        assert results["a2"] is True
        assert a1.connected
        assert a2.connected

        service.disconnect_all()
        assert not a1.connected
        assert not a2.connected

    def test_health_check(self):
        from core.services.market_data_service import MarketDataService

        service = MarketDataService()

        class DummyAdapter:
            def connect(self): return True
            def disconnect(self): return None
            def get_quote(self, symbol): return None
            def get_latest_data(self, symbol): return None
            def is_data_fresh(self, data, max_age=30): return data is not None
            def subscribe_to_market_data(self, symbols, cb): return False
            def unsubscribe_from_market_data(self, sym): return False
            def get_historical_data(self, sym, f, t, i="day"): return []
            def get_option_chain(self, sym, exp=None): return []
            def get_instrument_details(self, sym): return {"symbol": sym}

        service.register("d", DummyAdapter(), asset_classes=["equity"])
        health = service.health_check()
        assert health["total_adapters"] == 1
        assert "adapter_details" in health
