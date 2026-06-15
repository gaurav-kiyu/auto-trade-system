"""Tests for core/ltp_resolver.py — LtpResolver fallback chain."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.ltp_resolver import LtpResolver

# ── Constructor ──────────────────────────────────────────────────────────

def test_constructor_defaults():
    r = LtpResolver()
    assert r._ws_feed is None
    assert r._broker_port is None
    assert r._yf_cache == {}
    assert r._yf_cache_ts == 0


def test_constructor_with_deps():
    ws = MagicMock()
    bp = MagicMock()
    r = LtpResolver(cfg={"key": "val"}, ws_feed=ws, broker_port=bp)
    assert r._ws_feed is ws
    assert r._broker_port is bp
    assert r._cfg == {"key": "val"}


# ── Layer 1: WS cache ────────────────────────────────────────────────────

def test_resolve_ws_hit():
    ws = MagicMock()
    ws.is_connected.return_value = True
    ws.get_ltp.return_value = 18500.0
    r = LtpResolver(ws_feed=ws)
    assert r.resolve("NIFTY") == 18500.0
    ws.get_ltp.assert_called_once_with(256265)


def test_resolve_ws_disconnected():
    ws = MagicMock()
    ws.is_connected.return_value = False
    r = LtpResolver(ws_feed=ws)
    # No broker, no yf — returns None
    assert r.resolve("NIFTY") is not None  # yfinance fallback may work
    # If we really want to test the WS layer in isolation, disable yf
    with patch.object(r, "_resolve_yfinance", return_value=None):
        assert r.resolve("NIFTY") is None


def test_resolve_ws_unknown_index():
    ws = MagicMock()
    ws.is_connected.return_value = True
    r = LtpResolver(ws_feed=ws)
    with patch.object(r, "_resolve_broker", return_value=None), \
         patch.object(r, "_resolve_yfinance", return_value=None):
        assert r.resolve("UNKNOWN") is None
    ws.get_ltp.assert_not_called()


def test_resolve_token():
    ws = MagicMock()
    ws.get_ltp.return_value = 42000.0
    r = LtpResolver(ws_feed=ws)
    assert r.resolve_token(260105) == 42000.0


# ── Layer 2: Broker REST ─────────────────────────────────────────────────

def test_resolve_broker_hit():
    bp = MagicMock()
    bp.get_ltp.return_value = 18510.5
    r = LtpResolver(broker_port=bp)
    with patch.object(r, "_resolve_yfinance", return_value=None):
        assert r.resolve("NIFTY") == 18510.5


def test_resolve_broker_missing_get_ltp():
    bp = MagicMock(spec=[])  # no get_ltp
    r = LtpResolver(broker_port=bp)
    with patch.object(r, "_resolve_yfinance", return_value=None):
        assert r.resolve("NIFTY") is None


def test_resolve_broker_fallback_to_yf():
    bp = MagicMock()
    bp.get_ltp.side_effect = RuntimeError("API error")
    r = LtpResolver(broker_port=bp)
    with patch.object(r, "_resolve_yfinance", return_value=18500.0):
        price = r.resolve("NIFTY")
        assert price == 18500.0


# ── Layer 3: yfinance fallback ───────────────────────────────────────────

@patch("yfinance.Ticker")
def test_resolve_yfinance_hit(mock_ticker_cls):
    mock_ticker = MagicMock()
    mock_ticker_cls.return_value = mock_ticker
    import pandas as pd
    mock_ticker.history.return_value = pd.DataFrame(
        {"Close": [18450.0, 18500.0]},
        index=pd.date_range("2026-05-15", periods=2),
    )

    r = LtpResolver()
    price = r._resolve_yfinance("NIFTY")
    assert price == 18500.0
    assert r._yf_cache.get("NIFTY") == 18500.0


@patch("yfinance.Ticker")
def test_resolve_yfinance_cache(mock_ticker_cls):
    """Cache returns stale data without re-fetching."""
    mock_ticker = MagicMock()
    mock_ticker_cls.return_value = mock_ticker
    import pandas as pd
    mock_ticker.history.return_value = pd.DataFrame(
        {"Close": [18450.0, 18500.0]},
        index=pd.date_range("2026-05-15", periods=2),
    )

    r = LtpResolver()
    price1 = r._resolve_yfinance("NIFTY")
    assert price1 == 18500.0

    # Second call within TTL uses cache
    price2 = r._resolve_yfinance("NIFTY")
    assert price2 == 18500.0
    assert mock_ticker.history.call_count == 1  # not called again


def test_resolve_yfinance_unknown_index():
    r = LtpResolver()
    assert r._resolve_yfinance("UNKNOWN") is None


# ── Full fallback chain ──────────────────────────────────────────────────

def test_full_chain_ws_over_broker():
    ws = MagicMock()
    ws.is_connected.return_value = True
    ws.get_ltp.return_value = 18500.0
    bp = MagicMock()
    bp.get_ltp.return_value = 18400.0
    r = LtpResolver(ws_feed=ws, broker_port=bp)
    # WS wins
    assert r.resolve("NIFTY") == 18500.0


def test_full_chain_broker_over_yf():
    ws = MagicMock()
    ws.is_connected.return_value = False
    bp = MagicMock()
    bp.get_ltp.return_value = 18400.0
    r = LtpResolver(ws_feed=ws, broker_port=bp)
    with patch.object(r, "_resolve_yfinance", return_value=18000.0):
        # Broker wins over yf
        assert r.resolve("NIFTY") == 18400.0


# ── warm_cache ───────────────────────────────────────────────────────────

@patch("yfinance.Ticker")
def test_warm_cache(mock_ticker_cls):
    mock_ticker = MagicMock()
    mock_ticker_cls.return_value = mock_ticker
    import pandas as pd
    mock_ticker.history.return_value = pd.DataFrame(
        {"Close": [18450.0, 18500.0]},
        index=pd.date_range("2026-05-15", periods=2),
    )

    r = LtpResolver()
    r.warm_cache("NIFTY")
    assert r._yf_cache.get("NIFTY") == 18500.0


# ── resolve_token edge cases ──────────────────────────────────────────────

def test_resolve_token_no_ws():
    r = LtpResolver()
    assert r.resolve_token(256265) is None


def test_resolve_token_ws_exception():
    ws = MagicMock()
    ws.get_ltp.side_effect = RuntimeError("feed down")
    r = LtpResolver(ws_feed=ws)
    assert r.resolve_token(256265) is None


# ── _resolve_ws exception handler ────────────────────────────────────────

def test_resolve_ws_is_connected_raises():
    ws = MagicMock()
    ws.is_connected.side_effect = RuntimeError("connection check failed")
    r = LtpResolver(ws_feed=ws)
    with patch.object(r, "_resolve_broker", return_value=None), \
         patch.object(r, "_resolve_yfinance", return_value=None):
        assert r.resolve("NIFTY") is None


def test_resolve_ws_get_ltp_raises():
    ws = MagicMock()
    ws.is_connected.return_value = True
    ws.get_ltp.side_effect = RuntimeError("get_ltp failed")
    r = LtpResolver(ws_feed=ws)
    with patch.object(r, "_resolve_broker", return_value=None), \
         patch.object(r, "_resolve_yfinance", return_value=None):
        assert r.resolve("NIFTY") is None


# ── _resolve_yfinance edge cases ─────────────────────────────────────────

@patch("yfinance.Ticker")
def test_resolve_yfinance_empty_hist(mock_ticker_cls):
    import pandas as pd
    mock_ticker = MagicMock()
    mock_ticker_cls.return_value = mock_ticker
    mock_ticker.history.return_value = pd.DataFrame()

    r = LtpResolver()
    assert r._resolve_yfinance("NIFTY") is None


@patch("yfinance.Ticker")
def test_resolve_yfinance_nan_close(mock_ticker_cls):
    import pandas as pd
    mock_ticker = MagicMock()
    mock_ticker_cls.return_value = mock_ticker
    mock_ticker.history.return_value = pd.DataFrame(
        {"Close": [float("nan")]},
        index=pd.date_range("2026-05-15", periods=1),
    )

    r = LtpResolver()
    assert r._resolve_yfinance("NIFTY") is None


@patch("yfinance.Ticker")
def test_resolve_yfinance_exception(mock_ticker_cls):
    mock_ticker = MagicMock()
    mock_ticker_cls.return_value = mock_ticker
    mock_ticker.history.side_effect = ValueError("bad data")

    r = LtpResolver()
    assert r._resolve_yfinance("NIFTY") is None


# ── status ───────────────────────────────────────────────────────────────

def test_status():
    ws = MagicMock()
    ws.is_connected.return_value = True
    bp = MagicMock()
    r = LtpResolver(ws_feed=ws, broker_port=bp)
    st = r.status()
    assert st["ws_connected"] is True
    assert st["has_broker"] is True
    assert st["yf_cache_size"] == 0
