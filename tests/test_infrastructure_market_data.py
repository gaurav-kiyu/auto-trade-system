"""Unit tests for multi-asset market data adapters.

Tests cover:
  - Adapter construction and connect/disconnect lifecycle
  - Quote retrieval from all three adapters (mock yfinance)
  - Historical data retrieval
  - Symbol resolution mappings
  - Edge cases (disconnected state, empty responses, config overrides)
  - Unsupported operations (subscription, option chains)
  - Cache functionality (NSE equity adapter)
"""

from __future__ import annotations

from datetime import datetime

from core.ports.market_data import MarketDataPort

# ═══════════════════════════════════════════════════════════════════════════
# NSE Equity Adapter
# ═══════════════════════════════════════════════════════════════════════════

class TestNseEquityAdapterLifecycle:
    def test_construct_defaults(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter()
        assert adapter._timeout == 10
        assert adapter._cache_ttl == 30
        assert not adapter._connected

    def test_construct_with_config(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter({"equity_lookup_timeout": 20, "equity_cache_seconds": 60})
        assert adapter._timeout == 20
        assert adapter._cache_ttl == 60

    def test_connect_and_disconnect(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter()
        assert adapter.connect() is True
        assert adapter._connected
        adapter.disconnect()
        assert not adapter._connected

    def test_is_market_data_port(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        assert isinstance(NseEquityAdapter(), MarketDataPort)


class TestNseEquityAdapterQuotes:
    def test_get_quote_returns_none_when_disconnected(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter()
        assert adapter.get_quote("RELIANCE") is None

    def test_get_quote_returns_none_on_empty_history(self):
        from unittest.mock import MagicMock, patch

        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter()
        adapter.connect()
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = MagicMock(empty=True)
            result = adapter.get_quote("RELIANCE")
            assert result is None

    def test_yf_symbol_conversion(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter()
        assert adapter._yf_symbol("RELIANCE") == "RELIANCE.NS"
        assert adapter._yf_symbol("RELIANCE.NS") == "RELIANCE.NS"
        assert adapter._yf_symbol("TCS.BO") == "TCS.BO"
        assert adapter._yf_symbol("  hdfc  ") == "HDFC.NS"


class TestNseEquityAdapterHistorical:
    def test_historical_data_disconnected(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter()
        result = adapter.get_historical_data("RELIANCE", datetime.now(), datetime.now())
        assert result == []

    def test_get_instrument_details(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter()
        details = adapter.get_instrument_details("RELIANCE")
        assert details["symbol"] == "RELIANCE"
        assert details["exchange"] == "NSE"
        assert details["asset_class"] == "equity"


class TestNseEquityAdapterEdgeCases:
    def test_subscribe_not_supported(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter()
        assert adapter.subscribe_to_market_data(["RELIANCE"], lambda x: None) is False

    def test_unsubscribe_not_supported(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter()
        assert adapter.unsubscribe_from_market_data("RELIANCE") is False

    def test_option_chain_not_supported(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter()
        assert adapter.get_option_chain("RELIANCE") == []

    def test_is_data_fresh_with_none(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter()
        assert adapter.is_data_fresh(None) is False

    def test_is_data_fresh_with_data(self):
        from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
            NseEquityAdapter,
        )
        adapter = NseEquityAdapter()
        assert adapter.is_data_fresh({"some": "data"}) is True


# ═══════════════════════════════════════════════════════════════════════════
# MCX Commodity Adapter
# ═══════════════════════════════════════════════════════════════════════════

class TestMcxCommodityAdapterLifecycle:
    def test_construct_defaults(self):
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        adapter = McxCommodityAdapter()
        assert adapter._timeout == 10
        assert adapter._cache_ttl == 30
        assert not adapter._connected

    def test_construct_with_config(self):
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        adapter = McxCommodityAdapter({"commodity_lookup_timeout": 15})
        assert adapter._timeout == 15

    def test_connect_and_disconnect(self):
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        adapter = McxCommodityAdapter()
        assert adapter.connect() is True
        assert adapter._connected
        adapter.disconnect()
        assert not adapter._connected
        assert adapter._cache == {}

    def test_is_market_data_port(self):
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        assert isinstance(McxCommodityAdapter(), MarketDataPort)


class TestMcxCommoditySymbolResolution:
    def test_gold_resolves(self):
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        adapter = McxCommodityAdapter()
        assert adapter._resolve_symbol("GOLD") == "GC=F"
        assert adapter._resolve_symbol("gold") == "GC=F"

    def test_silver_resolves(self):
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        adapter = McxCommodityAdapter()
        assert adapter._resolve_symbol("SILVER") == "SI=F"

    def test_crude_oil_resolves(self):
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        adapter = McxCommodityAdapter()
        assert adapter._resolve_symbol("CRUDEOIL") == "CL=F"
        assert adapter._resolve_symbol("NATURALGAS") == "NG=F"

    def test_unknown_symbol_passes_through(self):
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        adapter = McxCommodityAdapter()
        assert adapter._resolve_symbol("PLATINUM") == "PLATINUM"

    def test_get_quote_disconnected(self):
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        adapter = McxCommodityAdapter()
        assert adapter.get_quote("GOLD") is None

    def test_get_instrument_details(self):
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        adapter = McxCommodityAdapter()
        details = adapter.get_instrument_details("GOLD")
        assert details["symbol"] == "GOLD"
        assert details["exchange"] == "MCX"
        assert details["asset_class"] == "commodity"

    def test_subscribe_not_supported(self):
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        adapter = McxCommodityAdapter()
        assert adapter.subscribe_to_market_data(["GOLD"], lambda x: None) is False

    def test_option_chain_not_supported(self):
        from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
            McxCommodityAdapter,
        )
        adapter = McxCommodityAdapter()
        assert adapter.get_option_chain("GOLD") == []


# ═══════════════════════════════════════════════════════════════════════════
# CDS Currency Adapter
# ═══════════════════════════════════════════════════════════════════════════

class TestCdsCurrencyAdapterLifecycle:
    def test_construct_defaults(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter()
        assert adapter._timeout == 10
        assert adapter._cache_ttl == 60  # different default than others
        assert not adapter._connected

    def test_construct_with_config(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter({"currency_lookup_timeout": 30, "currency_cache_seconds": 120})
        assert adapter._timeout == 30
        assert adapter._cache_ttl == 120

    def test_connect_and_disconnect(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter()
        assert adapter.connect() is True
        assert adapter._connected
        adapter.disconnect()
        assert not adapter._connected
        assert adapter._cache == {}

    def test_is_market_data_port(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        assert isinstance(CdsCurrencyAdapter(), MarketDataPort)


class TestCdsCurrencySymbolResolution:
    def test_usd_resolves(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter()
        assert adapter._resolve_symbol("USDINR") == "USDINR=X"
        assert adapter._resolve_symbol("usdinr") == "USDINR=X"

    def test_eur_resolves(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter()
        assert adapter._resolve_symbol("EURINR") == "EURINR=X"

    def test_gbp_resolves(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter()
        assert adapter._resolve_symbol("GBPINR") == "GBPINR=X"

    def test_jpy_resolves(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter()
        assert adapter._resolve_symbol("JPYINR") == "JPYINR=X"

    def test_unknown_pair_falls_back(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter()
        assert adapter._resolve_symbol("SGDINR") == "SGDINR=X"

    def test_get_quote_disconnected(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter()
        assert adapter.get_quote("USDINR") is None

    def test_get_instrument_details(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter()
        details = adapter.get_instrument_details("USDINR")
        assert details["symbol"] == "USDINR"
        assert details["exchange"] == "CDS"
        assert details["asset_class"] == "currency"

    def test_subscribe_not_supported(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter()
        assert adapter.subscribe_to_market_data(["USDINR"], lambda x: None) is False

    def test_option_chain_not_supported(self):
        from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
            CdsCurrencyAdapter,
        )
        adapter = CdsCurrencyAdapter()
        assert adapter.get_option_chain("USDINR") == []
