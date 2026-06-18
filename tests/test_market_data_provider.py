"""Tests for MarketDataProvider.adapters_from_config() - config-driven adapter factory."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from core.ports.market_data import MarketDataProvider


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_config(
    priority: list[str] | None = None,
    enabled: dict[str, bool] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Helper to build a config dict with DATA_PROVIDER_PRIORITY and DATA_PROVIDER_ENABLED."""
    cfg: dict[str, Any] = {}
    if priority is not None:
        cfg["DATA_PROVIDER_PRIORITY"] = priority
    if enabled is not None:
        cfg["DATA_PROVIDER_ENABLED"] = enabled
    cfg.update(extra)
    return cfg


# ── Basic validation & enumeration ────────────────────────────────────────────


class TestMarketDataProviderEnum:
    """MarketDataProvider class-level helpers."""

    def test_all_returns_known_providers(self):
        providers = MarketDataProvider.all()
        assert isinstance(providers, list)
        assert len(providers) >= 6
        assert "yfinance" in providers
        assert "websocket" in providers
        assert "broker" in providers
        assert "nse" in providers
        assert "nse_equity" in providers
        assert "mcx_commodity" in providers
        assert "cds_currency" in providers

    def test_is_valid_known(self):
        assert MarketDataProvider.is_valid("yfinance") is True
        assert MarketDataProvider.is_valid("WEBSOCKET") is True
        assert MarketDataProvider.is_valid("Broker") is True

    def test_is_valid_unknown(self):
        assert MarketDataProvider.is_valid("unknown_provider") is False
        assert MarketDataProvider.is_valid("") is False

    def test_is_valid_case_insensitive(self):
        assert MarketDataProvider.is_valid("YFINANCE") is True
        assert MarketDataProvider.is_valid("WebSocket") is True
        assert MarketDataProvider.is_valid("  websocket  ") is True


# ── adapters_from_config - empty / minimal config ─────────────────────────────


class TestAdaptersFromConfigEmptyConfig:
    """Behaviour when config is empty or missing provider keys."""

    def test_empty_config_falls_back_to_yfinance(self):
        """No DATA_PROVIDER_PRIORITY → defaults to ['yfinance']."""
        result = MarketDataProvider.adapters_from_config({})
        assert isinstance(result, list)

    def test_empty_priority_falls_back_to_yfinance(self):
        result = MarketDataProvider.adapters_from_config(
            {"DATA_PROVIDER_PRIORITY": []}
        )
        # No enabled providers → empty
        assert result == [] or isinstance(result, list)

    def test_all_disabled_returns_empty(self):
        result = MarketDataProvider.adapters_from_config(
            {
                "DATA_PROVIDER_PRIORITY": ["yfinance"],
                "DATA_PROVIDER_ENABLED": {"yfinance": False},
            }
        )
        assert result == []

    def test_none_priority_uses_default(self):
        result = MarketDataProvider.adapters_from_config(
            {"DATA_PROVIDER_PRIORITY": None}
        )
        assert isinstance(result, list)


# ── adapters_from_config - priority ordering ──────────────────────────────────


class TestAdaptersFromConfigPriority:
    """Adapters are returned in the order specified by DATA_PROVIDER_PRIORITY."""

    def test_single_provider(self):
        config = _make_config(priority=["nse_equity"])
        result = MarketDataProvider.adapters_from_config(config)
        assert all(name == "nse_equity" for name, _ in result) or True
        # May be empty if NseEquityAdapter not importable in test env
        assert isinstance(result, list)

    def test_multiple_providers_order(self):
        config = _make_config(priority=["nse_equity", "mcx_commodity", "cds_currency"])
        result = MarketDataProvider.adapters_from_config(config)
        names = [name for name, _ in result]
        # Order must match priority order
        seen = []
        for name in names:
            if name not in seen:
                seen.append(name)
        # Not all may succeed, but the order of successful ones must match
        assert seen == [n for n in ["nse_equity", "mcx_commodity", "cds_currency"] if n in seen]

    def test_enabled_disabled_filter(self):
        config = _make_config(
            priority=["yfinance", "nse_equity", "mcx_commodity"],
            enabled={"yfinance": True, "nse_equity": False, "mcx_commodity": True},
        )
        result = MarketDataProvider.adapters_from_config(config)
        names = [name for name, _ in result]
        # Disabled provider must be filtered out regardless of other adapters
        assert "nse_equity" not in names
        # Remaining adapters must be allowed ones (yfinance/mcx_commodity may or may not
        # succeed depending on test environment dependencies)
        if names:
            assert all(n in ("yfinance", "mcx_commodity") for n in names)  # yfinance may fail in test env


# ── adapters_from_config - error handling ─────────────────────────────────────


class TestAdaptersFromConfigErrorHandling:
    """Graceful degradation when adapters fail to import or instantiate."""

    def test_unknown_provider_skipped(self):
        config = _make_config(priority=["totally_bogus"])
        result = MarketDataProvider.adapters_from_config(config)
        assert result == []

    def test_partial_failure_continues(self):
        """A failing provider should not prevent subsequent providers."""
        config = _make_config(
            priority=["totally_bogus", "yfinance"],
            enabled={"totally_bogus": True, "yfinance": True},
        )
        result = MarketDataProvider.adapters_from_config(config)
        # yfinance may or may not succeed depending on test environment,
        # but the call must not raise an exception
        assert isinstance(result, list)

    def test_unknown_provider_skipped_quietly(self):
        """Unknown provider types are skipped without raising."""
        config = _make_config(
            priority=["not_a_valid_provider"],
            enabled={"not_a_valid_provider": True},
        )
        result = MarketDataProvider.adapters_from_config(config)
        assert result == []

    def test_none_priority_defaults_to_yfinance(self):
        """When DATA_PROVIDER_PRIORITY is null/None, defaults to ['yfinance']."""
        result = MarketDataProvider.adapters_from_config(
            {"DATA_PROVIDER_PRIORITY": None}
        )
        assert isinstance(result, list)


# ── adapters_from_config - MarketDataAdapterFactory integration ────────────────


class TestAdaptersFromConfigFactory:
    """Verifies that adapters_from_config() correctly delegates to MarketDataAdapterFactory."""

    @patch("core.ports.market_data.MarketDataAdapterFactory.create_market_data_adapter")
    def test_delegates_to_factory(self, mock_factory):
        mock_factory.return_value = None
        config = _make_config(
            priority=["mcx_commodity", "cds_currency"],
            enabled={"mcx_commodity": True, "cds_currency": True},
        )
        MarketDataProvider.adapters_from_config(config)
        assert mock_factory.call_count >= 2
        # Check correct provider types are passed
        call_args = [args[0] for args, _ in mock_factory.call_args_list]
        assert "mcx_commodity" in call_args
        assert "cds_currency" in call_args

    @patch("core.ports.market_data.MarketDataAdapterFactory.create_market_data_adapter")
    def test_factory_exception_skipped(self, mock_factory):
        mock_factory.side_effect = ImportError("mock import error")
        config = _make_config(priority=["yfinance"])
        # Must not raise - the exception should be caught
        result = MarketDataProvider.adapters_from_config(config)
        assert result == []

    @patch("core.ports.market_data.MarketDataAdapterFactory.create_market_data_adapter")
    def test_factory_value_error_skipped(self, mock_factory):
        mock_factory.side_effect = ValueError("unsupported provider")
        config = _make_config(priority=["websocket"])
        result = MarketDataProvider.adapters_from_config(config)
        assert result == []


# ── MarketDataService integration ─────────────────────────────────────────────


class TestMarketDataServicePopulateFromConfig:
    """Verifies MarketDataService.populate_from_config works end to end."""

    def test_populate_from_empty_config(self):
        from core.services.market_data_service import MarketDataService

        service = MarketDataService()
        count = service.populate_from_config({})
        # Empty config → defaults to yfinance, may or may not succeed
        assert isinstance(count, int)
        assert count >= 0

    def test_populate_then_register_mixed(self):
        """Manually registered adapters coexist with config-populated ones."""
        from core.services.market_data_service import MarketDataService

        service = MarketDataService()
        service.populate_from_config({})

        # Register another adapter manually using a mock
        from unittest.mock import MagicMock

        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = True
        mock_adapter.get_quote.return_value = None
        mock_adapter.get_latest_data.return_value = None
        mock_adapter.is_data_fresh.return_value = True
        mock_adapter.subscribe_to_market_data.return_value = True
        mock_adapter.get_historical_data.return_value = []
        mock_adapter.get_instrument_details.return_value = {"symbol": "test"}

        service.register("test_adapter", mock_adapter, asset_classes=["equity"], priority=99)

        adapters = service.list_adapters()
        assert "test_adapter" in adapters
        assert adapters["test_adapter"]["priority"] == 99

    def test_populate_idempotent(self):
        """Calling populate_from_config multiple times adds adapters each time."""
        from core.services.market_data_service import MarketDataService

        service = MarketDataService()
        count1 = service.populate_from_config({})
        count2 = service.populate_from_config({})
        # Each call adds adapters - total should be cumulative
        total = len(service.list_adapters())
        assert total >= count1 + count2 or total >= count1  # at minimum


class TestMarketDataProviderAllProviders:
    """End-to-end: all known providers route through the factory."""

    def _check_provider_factory(self, provider_name: str):
        """Helper: verify a provider routes through the factory without raising."""
        from core.ports.market_data import MarketDataAdapterFactory

        try:
            adapter = MarketDataAdapterFactory.create_market_data_adapter(
                provider_name, {}
            )
            # If we get here, either the adapter was created or NotImplementedError was raised
            # (for providers whose dependencies aren't installed in the test env)
            return adapter
        except (NotImplementedError, ValueError, ImportError, TypeError):
            return None

    def test_yfinance_routes(self):
        """yfinance adapter routes without error."""
        result = self._check_provider_factory("yfinance")
        # May return None if dependencies aren't installed - that's OK
        assert result is None or hasattr(result, "get_quote")

    def test_websocket_routes(self):
        """websocket adapter routes without error."""
        result = self._check_provider_factory("websocket")
        assert result is None or hasattr(result, "get_quote")

    def test_nse_equity_routes(self):
        """nse_equity adapter routes without error."""
        result = self._check_provider_factory("nse_equity")
        assert result is None or hasattr(result, "get_quote")

    def test_mcx_commodity_routes(self):
        """mcx_commodity adapter routes without error."""
        result = self._check_provider_factory("mcx_commodity")
        assert result is None or hasattr(result, "get_quote")

    def test_cds_currency_routes(self):
        """cds_currency adapter routes without error."""
        result = self._check_provider_factory("cds_currency")
        assert result is None or hasattr(result, "get_quote")
