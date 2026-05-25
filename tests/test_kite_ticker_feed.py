"""Tests for core/kite_ticker_feed.py — KiteTickerFeedManager."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from core.kite_ticker_feed import KiteTickerFeedManager

# kiteconnect is not installed in test env — fake it via sys.modules
_FAKE_TICKER_CLASS = MagicMock()

@pytest.fixture(autouse=True)
def _fake_kiteconnect():
    fake_ticker_mod = MagicMock()
    fake_ticker_mod.KiteTicker = _FAKE_TICKER_CLASS
    fake_kiteconnect_mod = MagicMock()
    fake_kiteconnect_mod.ticker = fake_ticker_mod
    with patch.dict(sys.modules, {
        "kiteconnect": fake_kiteconnect_mod,
        "kiteconnect.ticker": fake_ticker_mod,
    }, clear=False):
        yield

# ── Helpers ──────────────────────────────────────────────────────────────

_LIVE_CFG = {
    "EXECUTION_MODE": "LIVE",
    "BROKER_API_ENABLED": True,
    "BROKER_DRIVER": "KITE",
    "kite_ticker_enabled": True,
    "kite_ticker_mode": "ltp",
}


def _mock_kite_ticker(connect_side_effect=None):
    """Create a Mock for kiteconnect.ticker.KiteTicker with standard attrs."""
    kws = MagicMock()
    kws.subscribe = MagicMock()
    kws.set_mode = MagicMock()
    kws.close = MagicMock()
    kws.stop_retry = MagicMock()
    kws.connect = MagicMock(side_effect=connect_side_effect)
    return kws


# ── Constructor ──────────────────────────────────────────────────────────

def test_constructor_defaults():
    m = KiteTickerFeedManager()
    assert m._enabled is False
    assert m._tick_mode == "ltp"
    assert m._index_tokens == [256265, 260105, 260937]
    assert m._extra_tokens == []
    assert m._ltp_cache == {}
    assert m._kite_gave_up.is_set() is False


def test_constructor_with_custom_cfg():
    cfg = {
        "kite_ticker_enabled": True,
        "kite_ticker_mode": "full",
        "kite_ticker_index_tokens": [256265],
        "kite_ticker_subscribe_tokens": [738561, 5633],
    }
    m = KiteTickerFeedManager(cfg)
    assert m._enabled is True
    assert m._tick_mode == "full"
    assert m._index_tokens == [256265]
    assert m._extra_tokens == [738561, 5633]


# ── Connect gating (no real KiteTicker needed) ──────────────────────────

def test_connect_disabled_by_config():
    m = KiteTickerFeedManager({})
    assert m._enabled is False
    assert m.connect() is False


def test_connect_blocked_in_paper_mode():
    m = KiteTickerFeedManager({
        "kite_ticker_enabled": True,
        "EXECUTION_MODE": "PAPER",
        "BROKER_API_ENABLED": True,
        "BROKER_DRIVER": "KITE",
    })
    assert m.connect() is False


def test_connect_blocked_when_broker_disabled():
    m = KiteTickerFeedManager({
        "kite_ticker_enabled": True,
        "EXECUTION_MODE": "LIVE",
        "BROKER_API_ENABLED": False,
        "BROKER_DRIVER": "KITE",
    })
    assert m.connect() is False


def test_connect_blocked_wrong_driver():
    m = KiteTickerFeedManager({
        "kite_ticker_enabled": True,
        "EXECUTION_MODE": "LIVE",
        "BROKER_API_ENABLED": True,
        "BROKER_DRIVER": "ANGEL",
    })
    assert m.connect() is False


def test_connect_blocked_when_kiteconnect_missing():
    """Simulate ImportError by patching _do_connect."""
    m = KiteTickerFeedManager(_LIVE_CFG)
    with patch.object(m, "_do_connect", return_value=False):
        assert m.connect() is False


def test_connect_blocked_missing_credentials():
    """_do_connect returns False when credentials are empty."""
    m = KiteTickerFeedManager(_LIVE_CFG)
    with patch(
        "core.kite_ticker_feed.KiteTickerFeedManager._broker_secrets",
        return_value={"api_key": "", "access_token": ""},
    ):
        assert m._do_connect() is False


# ── Connect success with mocked KiteTicker ──────────────────────────────

@patch("core.kite_ticker_feed.KiteTickerFeedManager._broker_secrets")
def test_connect_success(mock_secrets):
    mock_secrets.return_value = {"api_key": "mykey", "access_token": "mytoken"}

    m = KiteTickerFeedManager(_LIVE_CFG)
    result = m._do_connect()

    assert result is True
    _FAKE_TICKER_CLASS.assert_called_once_with(
        api_key="mykey",
        access_token="mytoken",
        debug=False,
        reconnect=True,
        reconnect_max_tries=50,
        reconnect_max_delay=60,
    )
    _FAKE_TICKER_CLASS.return_value.connect.assert_called_once_with(threaded=True)


@patch("core.kite_ticker_feed.KiteTickerFeedManager._broker_secrets")
def test_connect_sets_callbacks(mock_secrets):
    mock_secrets.return_value = {"api_key": "k", "access_token": "t"}

    m = KiteTickerFeedManager(_LIVE_CFG)
    m._do_connect()

    kws = _FAKE_TICKER_CLASS.return_value
    assert kws.on_connect == m._on_kite_connect
    assert kws.on_close == m._on_kite_close
    assert kws.on_error == m._on_kite_error
    assert kws.on_ticks == m._on_kite_ticks
    assert kws.on_reconnect == m._on_kite_reconnect
    assert kws.on_noreconnect == m._on_kite_noreconnect
    assert kws.on_order_update == m._on_kite_order_update


# ── KiteTicker callbacks ─────────────────────────────────────────────────

def test_on_kite_connect_subscribes():
    m = KiteTickerFeedManager(_LIVE_CFG)
    ws_mock = MagicMock()
    m._user_on_message = MagicMock()

    m._on_kite_connect(ws_mock, {"status": "ok"})

    assert m.is_connected() is True
    ws_mock.subscribe.assert_called_once()
    ws_mock.set_mode.assert_called_once()
    # Verify on_message was fired
    m._user_on_message.assert_called_once_with({"type": "connect", "status": "connected"})


def test_on_kite_ticks_updates_ltp_cache():
    m = KiteTickerFeedManager(_LIVE_CFG)
    m._user_on_message = MagicMock()

    ticks = [
        {"instrument_token": 256265, "last_price": 18500.0, "mode": "ltp"},
        {"instrument_token": 260105, "last_price": 42000.0, "mode": "ltp"},
    ]
    m._on_kite_ticks(None, ticks)

    assert m.get_ltp(256265) == 18500.0
    assert m.get_ltp(260105) == 42000.0
    assert m.get_ltp(999999) is None

    cache = m.get_ltp_cache()
    assert 256265 in cache
    assert cache[256265]["last_price"] == 18500.0
    assert "timestamp" in cache[256265]

    # Verify user callback
    m._user_on_message.assert_called_once()
    call_args = m._user_on_message.call_args[0][0]
    assert call_args["type"] == "ticks"
    assert len(call_args["data"]) == 2


def test_on_kite_close_records_disconnect():
    m = KiteTickerFeedManager(_LIVE_CFG)
    # Simulate connected state
    with m._lock:
        m._connected = True

    m._on_kite_close(None, 1006, "Abnormal closure")
    assert m.is_connected() is False
    assert "Abnormal closure" in m._last_error


def test_on_kite_error_calls_user_callback():
    m = KiteTickerFeedManager(_LIVE_CFG)
    mock_err = MagicMock()
    m._user_on_error = mock_err

    m._on_kite_error(None, 0, "test error")
    assert "test error" in m._last_error
    mock_err.assert_called_once()


def test_on_kite_noreconnect_signals_outer_layer():
    m = KiteTickerFeedManager(_LIVE_CFG)
    with m._lock:
        m._connected = True

    m._on_kite_noreconnect(None)
    assert m._kite_gave_up.is_set() is True
    assert m.is_connected() is False


def test_on_kite_order_update_forwards_to_user():
    m = KiteTickerFeedManager(_LIVE_CFG)
    m._user_on_message = MagicMock()

    m._on_kite_order_update(None, {"order_id": "123"})
    m._user_on_message.assert_called_once_with({
        "type": "order_update",
        "data": {"order_id": "123"},
    })


# ── subscribe / set_mode ─────────────────────────────────────────────────

def test_subscribe_forwards_to_kws():
    m = KiteTickerFeedManager(_LIVE_CFG)
    m._kws = MagicMock()
    with m._lock:
        m._connected = True

    assert m.subscribe([738561]) is True
    m._kws.subscribe.assert_called_once_with([738561])


def test_subscribe_queues_when_disconnected():
    m = KiteTickerFeedManager(_LIVE_CFG)
    assert m.subscribe([738561]) is False
    assert 738561 in m._extra_tokens


def test_set_mode_forwards_to_kws():
    m = KiteTickerFeedManager(_LIVE_CFG)
    m._kws = MagicMock()
    with m._lock:
        m._connected = True

    assert m.set_mode("full", [256265]) is True
    m._kws.set_mode.assert_called_once_with("full", [256265])


def test_set_mode_fails_when_disconnected():
    m = KiteTickerFeedManager(_LIVE_CFG)
    assert m.set_mode("full", [256265]) is False


# ── disconnect ───────────────────────────────────────────────────────────

@patch("core.kite_ticker_feed.KiteTickerFeedManager._broker_secrets")
def test_disconnect_closes_kws(mock_secrets):
    mock_secrets.return_value = {"api_key": "k", "access_token": "t"}

    m = KiteTickerFeedManager(_LIVE_CFG)
    m._do_connect()
    m._do_disconnect()

    kws = _FAKE_TICKER_CLASS.return_value
    kws.stop_retry.assert_called_once()
    kws.close.assert_called_once()
    assert m._kws is None


# ── status ───────────────────────────────────────────────────────────────

def test_status_includes_kite_fields():
    m = KiteTickerFeedManager(_LIVE_CFG)
    st = m.status()
    assert st["enabled"] is True
    assert st["tick_mode"] == "ltp"
    assert st["index_tokens"] == [256265, 260105, 260937]
    assert st["extra_tokens"] == []
    assert st["ltp_cache_size"] == 0
    assert st["kite_gave_up"] is False
    assert st["has_kws"] is False
    assert st["connected"] is False
