"""Unit tests for NseIndexWebSocketAdapter - self-contained KiteTicker WebSocket adapter.

Tests cover:
  - Constructor defaults and custom config
  - Token mapping (symbol -> token, token -> symbol)
  - LTP cache updates from tick callbacks
  - get_quote / get_latest_data / is_data_fresh
  - Subscribe / unsubscribe / instrument details
  - Connect/disconnect (gated: no real KiteTicker in tests)
  - Edge cases (cache expiry, unknown symbols, zero prices)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from core.ports.market_data import MarketDataPort


# ── Helpers ──────────────────────────────────────────────────────────────

_FAKE_KITE_TICKER = MagicMock()


@pytest.fixture(autouse=True)
def _fake_kiteconnect():
    """Fake kiteconnect.ticker module so no real SDK import is needed."""
    import sys
    fake_ticker_mod = MagicMock()
    fake_ticker_mod.KiteTicker = _FAKE_KITE_TICKER
    fake_kiteconnect_mod = MagicMock()
    fake_kiteconnect_mod.ticker = fake_ticker_mod
    with patch.dict(sys.modules, {
        "kiteconnect": fake_kiteconnect_mod,
        "kiteconnect.ticker": fake_ticker_mod,
    }, clear=False):
        yield


def _make_adapter(**overrides) -> "NseIndexWebSocketAdapter":
    """Create an adapter with kite_ticker_enabled=True + optional overrides."""
    from infrastructure.adapters.market_data.websocket.nse_index_ws_adapter import (
        NseIndexWebSocketAdapter,
    )
    cfg = {
        "kite_ticker_enabled": True,
        "kite_ticker_mode": "ltp",
        **overrides,
    }
    return NseIndexWebSocketAdapter(cfg)


def _sample_tick(token: int, price: float, **extra) -> dict:
    tick = {"instrument_token": token, "last_price": price, "mode": "ltp"}
    tick.update(extra)
    return tick


# ═══════════════════════════════════════════════════════════════════════════
# Constructor
# ═══════════════════════════════════════════════════════════════════════════

class TestConstructor:
    def test_defaults(self):
        adapter = _make_adapter(kite_ticker_enabled=True)
        assert adapter._enabled is True
        assert adapter._tick_mode == "ltp"
        assert adapter._cache_ttl == 5.0
        assert adapter._token_map == {
            "NIFTY": 256265, "BANKNIFTY": 260105, "FINNIFTY": 260937,
        }

    def test_disabled_by_default(self):
        from infrastructure.adapters.market_data.websocket.nse_index_ws_adapter import (
            NseIndexWebSocketAdapter,
        )
        adapter = NseIndexWebSocketAdapter()
        assert adapter._enabled is False

    def test_custom_config(self):
        adapter = _make_adapter(
            kite_ticker_enabled=True,
            kite_ticker_mode="full",
            ws_cache_ttl_seconds=10,
            kite_ticker_index_tokens={"NIFTY": 256265},
        )
        assert adapter._tick_mode == "full"
        assert adapter._cache_ttl == 10.0
        assert adapter._token_map == {"NIFTY": 256265}

    def test_implements_market_data_port(self):
        from infrastructure.adapters.market_data.websocket.nse_index_ws_adapter import (
            NseIndexWebSocketAdapter,
        )
        adapter = NseIndexWebSocketAdapter()
        assert isinstance(adapter, MarketDataPort)


# ═══════════════════════════════════════════════════════════════════════════
# Token Mapping
# ═══════════════════════════════════════════════════════════════════════════

class TestTokenMapping:
    def test_nifty_maps_to_256265(self):
        adapter = _make_adapter()
        assert adapter._token_map["NIFTY"] == 256265

    def test_banknifty_maps_to_260105(self):
        adapter = _make_adapter()
        assert adapter._token_map["BANKNIFTY"] == 260105

    def test_finnifty_maps_to_260937(self):
        adapter = _make_adapter()
        assert adapter._token_map["FINNIFTY"] == 260937

    def test_reverse_mapping(self):
        adapter = _make_adapter()
        assert adapter._symbol_by_token[256265] == "NIFTY"
        assert adapter._symbol_by_token[260105] == "BANKNIFTY"
        assert adapter._symbol_by_token[260937] == "FINNIFTY"

    def test_empty_token_map_uses_defaults(self):
        adapter = _make_adapter(kite_ticker_index_tokens={})  # type: ignore[arg-type]
        assert adapter._token_map == {}
        assert adapter._symbol_by_token == {}
        assert adapter._index_token_list == []


# ═══════════════════════════════════════════════════════════════════════════
# LTP Cache - Tick Processing
# ═══════════════════════════════════════════════════════════════════════════

class TestLtpCache:
    def test_cache_empty_on_construction(self):
        adapter = _make_adapter()
        assert adapter.get_all_cached() == {}

    def test_tick_updates_cache(self):
        adapter = _make_adapter()
        ticks = [_sample_tick(256265, 18500.0)]
        adapter._on_kite_ticks(None, ticks)
        cached = adapter.get_all_cached()
        assert "NIFTY" in cached
        assert cached["NIFTY"]["last_price"] == 18500.0
        assert cached["NIFTY"]["source"] == "websocket"

    def test_multiple_ticks(self):
        adapter = _make_adapter()
        ticks = [
            _sample_tick(256265, 18500.0),
            _sample_tick(260105, 42000.0),
            _sample_tick(260937, 18000.0),
        ]
        adapter._on_kite_ticks(None, ticks)
        assert adapter.get_ltp("NIFTY") == 18500.0
        assert adapter.get_ltp("BANKNIFTY") == 42000.0
        assert adapter.get_ltp("FINNIFTY") == 18000.0

    def test_ignores_unknown_token(self):
        adapter = _make_adapter()
        ticks = [_sample_tick(999999, 100.0)]
        adapter._on_kite_ticks(None, ticks)
        assert adapter.get_all_cached() == {}

    def test_ignores_zero_price_tick(self):
        adapter = _make_adapter()
        ticks = [_sample_tick(256265, 0.0)]
        adapter._on_kite_ticks(None, ticks)
        assert adapter.get_ltp("NIFTY") is None

    def test_latest_tick_overwrites_previous(self):
        adapter = _make_adapter()
        ticks1 = [_sample_tick(256265, 18500.0)]
        ticks2 = [_sample_tick(256265, 18600.0)]
        adapter._on_kite_ticks(None, ticks1)
        adapter._on_kite_ticks(None, ticks2)
        assert adapter.get_ltp("NIFTY") == 18600.0

    def test_cache_has_timestamp(self):
        adapter = _make_adapter()
        adapter._on_kite_ticks(None, [_sample_tick(256265, 18500.0)])
        entry = adapter.get_all_cached()["NIFTY"]
        assert "timestamp" in entry
        assert entry["timestamp"] > 0


# ═══════════════════════════════════════════════════════════════════════════
# get_quote
# ═══════════════════════════════════════════════════════════════════════════

class TestGetQuote:
    def test_returns_none_when_no_cache(self):
        adapter = _make_adapter()
        assert adapter.get_quote("NIFTY") is None

    def test_returns_quote_after_tick(self):
        adapter = _make_adapter()
        adapter._on_kite_ticks(None, [_sample_tick(256265, 18500.0)])
        quote = adapter.get_quote("NIFTY")
        assert quote is not None
        assert quote.last == 18500.0
        assert quote.symbol == "NIFTY"

    def test_returns_quote_with_volume(self):
        adapter = _make_adapter()
        tick = _sample_tick(256265, 18500.0, volume=5000)
        adapter._on_kite_ticks(None, [tick])
        quote = adapter.get_quote("NIFTY")
        assert quote.volume == 5000

    def test_case_insensitive_symbol(self):
        adapter = _make_adapter()
        adapter._on_kite_ticks(None, [_sample_tick(256265, 18500.0)])
        assert adapter.get_quote("nifty").symbol == "NIFTY"
        assert adapter.get_quote("Nifty").last == 18500.0

    def test_returns_none_on_cache_expiry(self):
        adapter = _make_adapter(ws_cache_ttl_seconds=0.001)  # Very short TTL
        adapter._on_kite_ticks(None, [_sample_tick(256265, 18500.0)])
        time.sleep(0.01)  # Wait for cache to expire
        assert adapter.get_quote("NIFTY") is None


# ═══════════════════════════════════════════════════════════════════════════
# get_latest_data
# ═══════════════════════════════════════════════════════════════════════════

class TestGetLatestData:
    def test_returns_none_when_no_data(self):
        adapter = _make_adapter()
        assert adapter.get_latest_data("NIFTY") is None

    def test_returns_dict_after_tick(self):
        adapter = _make_adapter()
        adapter._on_kite_ticks(None, [_sample_tick(256265, 18500.0)])
        data = adapter.get_latest_data("NIFTY")
        assert isinstance(data, dict)
        assert data["last_price"] == 18500.0

    def test_returns_none_on_cache_expiry(self):
        adapter = _make_adapter(ws_cache_ttl_seconds=0.001)
        adapter._on_kite_ticks(None, [_sample_tick(256265, 18500.0)])
        time.sleep(0.01)
        assert adapter.get_latest_data("NIFTY") is None

    def test_returns_copy_not_reference(self):
        adapter = _make_adapter()
        adapter._on_kite_ticks(None, [_sample_tick(256265, 18500.0)])
        data = adapter.get_latest_data("NIFTY")
        data["last_price"] = 999.0  # Modify copy
        assert adapter.get_ltp("NIFTY") == 18500.0  # Original unchanged


# ═══════════════════════════════════════════════════════════════════════════
# is_data_fresh
# ═══════════════════════════════════════════════════════════════════════════

class TestIsDataFresh:
    def test_false_for_none(self):
        adapter = _make_adapter()
        assert adapter.is_data_fresh(None) is False

    def test_false_for_empty_dict(self):
        adapter = _make_adapter()
        assert adapter.is_data_fresh({}) is False

    def test_false_for_non_dict(self):
        adapter = _make_adapter()
        assert adapter.is_data_fresh("string") is False

    def test_true_for_recent_data(self):
        adapter = _make_adapter()
        data = {"timestamp": time.time()}
        assert adapter.is_data_fresh(data) is True

    def test_false_for_stale_data(self):
        adapter = _make_adapter()
        data = {"timestamp": time.time() - 100}
        assert adapter.is_data_fresh(data, max_age_seconds=30) is False


# ═══════════════════════════════════════════════════════════════════════════
# subscribe_to_market_data
# ═══════════════════════════════════════════════════════════════════════════

class TestSubscribe:
    def test_false_when_disconnected(self):
        adapter = _make_adapter()
        assert adapter.subscribe_to_market_data(["NIFTY"], None) is False

    def test_false_for_unknown_symbols(self):
        adapter = _make_adapter()
        adapter._kws = MagicMock()
        adapter._connected = True
        assert adapter.subscribe_to_market_data(["UNKNOWN"], None) is False

    def test_subscribes_known_symbols(self):
        adapter = _make_adapter()
        adapter._kws = MagicMock()
        adapter._connected = True
        result = adapter.subscribe_to_market_data(["NIFTY", "BANKNIFTY"], None)
        assert result is True
        adapter._kws.subscribe.assert_called_once_with([256265, 260105])


# ═══════════════════════════════════════════════════════════════════════════
# unsubscribe / option_chain / historical_data / instrument_details
# ═══════════════════════════════════════════════════════════════════════════

class TestUnsupportedMethods:
    def test_unsubscribe_not_supported(self):
        adapter = _make_adapter()
        assert adapter.unsubscribe_from_market_data("NIFTY") is False

    def test_option_chain_not_supported(self):
        adapter = _make_adapter()
        assert adapter.get_option_chain("NIFTY") == []

    def test_historical_data_not_supported(self):
        from datetime import datetime
        adapter = _make_adapter()
        assert adapter.get_historical_data("NIFTY", datetime.now(), datetime.now()) == []

class TestInstrumentDetails:
    def test_known_symbol(self):
        adapter = _make_adapter()
        details = adapter.get_instrument_details("NIFTY")
        assert details["symbol"] == "NIFTY"
        assert details["exchange"] == "NSE"
        assert details["asset_class"] == "index"
        assert details["instrument_token"] == 256265

    def test_unknown_symbol(self):
        adapter = _make_adapter()
        details = adapter.get_instrument_details("UNKNOWN")
        assert details["symbol"] == "UNKNOWN"
        assert details["instrument_token"] is None


# ═══════════════════════════════════════════════════════════════════════════
# get_ltp
# ═══════════════════════════════════════════════════════════════════════════

class TestGetLtp:
    def test_returns_none_when_no_data(self):
        adapter = _make_adapter()
        assert adapter.get_ltp("NIFTY") is None

    def test_returns_price_after_tick(self):
        adapter = _make_adapter()
        adapter._on_kite_ticks(None, [_sample_tick(256265, 18500.0)])
        assert adapter.get_ltp("NIFTY") == 18500.0

    def test_returns_float(self):
        adapter = _make_adapter()
        adapter._on_kite_ticks(None, [_sample_tick(256265, 18500.0)])
        price = adapter.get_ltp("NIFTY")
        assert isinstance(price, float)


# ═══════════════════════════════════════════════════════════════════════════
# Connect / Disconnect
# ═══════════════════════════════════════════════════════════════════════════

class TestConnect:
    def test_connect_disabled_no_op(self):
        from infrastructure.adapters.market_data.websocket.nse_index_ws_adapter import (
            NseIndexWebSocketAdapter,
        )
        adapter = NseIndexWebSocketAdapter({"kite_ticker_enabled": False})
        assert adapter.connect() is False
        assert adapter._kws is None

    def test_connect_blocked_missing_credentials(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_broker_secrets", return_value={"api_key": "", "access_token": ""}):
            assert adapter.connect() is False

    def test_connect_blocked_kiteconnect_not_installed(self):
        adapter = _make_adapter()
        # Remove the fake module so import fails
        with patch.dict("sys.modules", {"kiteconnect.ticker": None}, clear=False):
            with patch("importlib.import_module", side_effect=ImportError("not installed")):
                assert adapter.connect() is False

    def test_connect_success(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_broker_secrets", return_value={"api_key": "k", "access_token": "t"}):
            result = adapter.connect()
            assert result is True
            assert adapter._kws is not None
            assert adapter._connected is True

    def test_connect_callback_wiring(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_broker_secrets", return_value={"api_key": "k", "access_token": "t"}):
            adapter.connect()
            kws = adapter._kws
            assert kws.on_connect == adapter._on_kite_connect
            assert kws.on_close == adapter._on_kite_close
            assert kws.on_error == adapter._on_kite_error
            assert kws.on_ticks == adapter._on_kite_ticks
            assert kws.on_reconnect == adapter._on_kite_reconnect
            assert kws.on_noreconnect == adapter._on_kite_noreconnect


class TestDisconnect:
    def test_disconnect_clears_cache(self):
        adapter = _make_adapter()
        adapter._on_kite_ticks(None, [_sample_tick(256265, 18500.0)])
        assert len(adapter.get_all_cached()) == 1
        adapter._kws = MagicMock()
        adapter._connected = True
        adapter.disconnect()
        assert adapter.get_all_cached() == {}
        assert adapter._connected is False
        assert adapter._kws is None

    def test_disconnect_when_not_connected(self):
        adapter = _make_adapter()
        adapter.disconnect()  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════
# KiteTicker callbacks
# ═══════════════════════════════════════════════════════════════════════════

class TestCallbacks:
    def test_on_kite_connect_subscribes(self):
        adapter = _make_adapter()
        ws_mock = MagicMock()
        adapter._on_kite_connect(ws_mock, {"status": "ok"})
        assert adapter._connected is True
        ws_mock.subscribe.assert_called_once()
        ws_mock.set_mode.assert_called_once()

    def test_on_kite_close_sets_disconnected(self):
        adapter = _make_adapter()
        adapter._connected = True
        adapter._on_kite_close(None, 1006, "Abnormal closure")
        assert adapter._connected is False

    def test_on_kite_noreconnect_sets_disconnected(self):
        adapter = _make_adapter()
        adapter._connected = True
        adapter._on_kite_noreconnect(None)
        assert adapter._connected is False

    def test_on_kite_error_logs(self):
        adapter = _make_adapter()
        adapter._on_kite_error(None, 0, "test error")  # Should not raise

    def test_on_kite_reconnect_logs(self):
        adapter = _make_adapter()
        adapter._on_kite_reconnect(None, 1)  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════
# status
# ═══════════════════════════════════════════════════════════════════════════

class TestStatus:
    def test_initial_state(self):
        adapter = _make_adapter()
        st = adapter.status()
        assert st["enabled"] is True
        assert st["connected"] is False
        assert st["cache_size"] == 0
        assert st["has_kws"] is False
        assert st["tick_mode"] == "ltp"

    def test_after_ticks(self):
        adapter = _make_adapter()
        adapter._on_kite_ticks(None, [_sample_tick(256265, 18500.0)])
        st = adapter.status()
        assert st["cache_size"] == 1

    def test_after_connect(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_broker_secrets", return_value={"api_key": "k", "access_token": "t"}):
            adapter.connect()
            st = adapter.status()
            assert st["has_kws"] is True
