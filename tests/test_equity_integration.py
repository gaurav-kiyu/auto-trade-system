"""Integration tests for equity_trader - startup sequence, config wiring, and --equity flag."""

from __future__ import annotations

import pandas as pd
from unittest.mock import MagicMock, patch

from core.equity_trader import EquityTrader, run_equity_trader


# ── run_equity_trader factory integration ───────────────────────────────

def test_run_equity_trader_starts_and_stops() -> None:
    """Factory should start the trader immediately, and stop() should work."""
    trader = run_equity_trader()
    assert trader.is_running is True
    assert isinstance(trader, EquityTrader)
    trader.stop()
    assert trader.is_running is False


def test_run_equity_trader_with_callbacks() -> None:
    """Factory should wire up all callbacks correctly."""
    price_fn = MagicMock(return_value=2500.0)
    send_fn = MagicMock()
    entry_fn = MagicMock(return_value=True)
    exit_fn = MagicMock()

    trader = run_equity_trader(
        cfg={"EQUITY_MAP": {"RELIANCE": {"enabled": True}},
             "EQUITY_PRIORITY": ["RELIANCE"]},
        send_fn=send_fn,
        get_price_fn=price_fn,
        execute_entry_fn=entry_fn,
        execute_exit_fn=exit_fn,
    )
    assert trader.is_running is True
    assert trader._get_price_fn is price_fn
    assert trader._execute_entry_fn is entry_fn
    assert trader._execute_exit_fn is exit_fn
    trader.stop()


# ── Config-driven behavior ──────────────────────────────────────────────

def test_equity_trader_reads_config() -> None:
    """EquityTrader should read EQUITY_SL_PCT, EQUITY_TARGET_PCT from config."""
    cfg = {
        "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
        "EQUITY_PRIORITY": ["RELIANCE"],
        "EQUITY_SL_PCT": 0.98,
        "EQUITY_TARGET_PCT": 1.10,
        "EQUITY_MAX_DAILY_TRADES": 3,
        "EQUITY_DEFAULT_QTY": 10,
    }
    trader = EquityTrader(cfg=cfg)
    assert trader._sl_pct == 0.98
    assert trader._target_pct == 1.10
    assert trader._max_daily_trades == 3
    assert trader._default_qty == 10
    assert trader._equity_symbols == ["RELIANCE"]


def test_equity_trader_filters_disabled_symbols() -> None:
    """Symbols with enabled: false should be filtered out."""
    cfg = {
        "EQUITY_MAP": {
            "RELIANCE": {"enabled": True},
            "TCS": {"enabled": False},
        },
        "EQUITY_PRIORITY": ["RELIANCE", "TCS"],
    }
    trader = EquityTrader(cfg=cfg)
    assert "RELIANCE" in trader._equity_symbols
    assert "TCS" not in trader._equity_symbols


# ── Price resolution integration ────────────────────────────────────────

@patch("core.equity_trader.now_ist")
def test_equity_entry_with_price_resolution(mock_now) -> None:
    """Entry should use get_price_fn to resolve price and store it correctly."""
    from datetime import datetime
    mock_now.return_value = datetime(2026, 6, 11, 11, 0)

    price_fn = MagicMock(return_value=2500.0)
    trader = EquityTrader(
        cfg={
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE"],
        },
        get_price_fn=price_fn,
    )
    result = trader.enter_position("RELIANCE", "BUY", 80)
    assert result is True
    assert trader._positions["RELIANCE"]["entry_price"] == 2500.0
    price_fn.assert_called_with("RELIANCE")


# ── Multiple trades and daily limit ──────────────────────────────────────

@patch("core.equity_trader.now_ist")
def test_equity_max_daily_trades_enforced(mock_now) -> None:
    """Should block entry after max_daily_trades is reached."""
    from datetime import datetime
    mock_now.return_value = datetime(2026, 6, 11, 11, 0)

    price_fn = MagicMock(return_value=2500.0)
    cfg = {
        "EQUITY_MAP": {"RELIANCE": {"enabled": True}, "TCS": {"enabled": True}},
        "EQUITY_PRIORITY": ["RELIANCE", "TCS"],
        "EQUITY_MAX_DAILY_TRADES": 1,
    }
    trader = EquityTrader(cfg=cfg, get_price_fn=price_fn)

    # First trade should succeed
    assert trader.enter_position("RELIANCE", "BUY", 80) is True
    assert trader._daily_trades == 1

    # Second trade should be blocked
    assert trader.enter_position("TCS", "BUY", 75) is False


# ───--equity flag awareness ──────────────────────────────────────────────

def test_equity_cli_flag_detection() -> None:
    """EquityTrader does not directly read sys.argv, but the flag gating
    happens in index_trader.py's setup_di_container(). This test verifies
    that the module can be imported and instantiated without the flag."""
    # Should work without any special setup
    trader = EquityTrader()
    assert trader is not None
    assert trader._positions == {}
    trader.stop()


# ── Status reporting ─────────────────────────────────────────────────────

@patch("core.equity_trader.now_ist")
def test_equity_trader_status_after_entry(mock_now) -> None:
    """Status should reflect positions and daily trade count after entry."""
    from datetime import datetime
    mock_now.return_value = datetime(2026, 6, 11, 11, 0)

    price_fn = MagicMock(return_value=2500.0)
    cfg = {
        "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
        "EQUITY_PRIORITY": ["RELIANCE"],
    }
    trader = EquityTrader(cfg=cfg, get_price_fn=price_fn)
    trader.enter_position("RELIANCE", "BUY", 80)

    status = trader.status()
    assert status["positions"] == 1
    assert status["daily_trades"] == 1
    assert status["symbols"] == ["RELIANCE"]


# ── Background loop integration ─────────────────────────────────────────

def test_equity_trader_background_loop() -> None:
    """The background trading loop should run and stop cleanly."""
    trader = EquityTrader()
    trader.start()
    assert trader.is_running is True
    assert trader._thread is not None
    assert trader._thread.is_alive() is True

    trader.stop()
    assert trader.is_running is False
    # Thread should have terminated
    if trader._thread:
        trader._thread.join(timeout=5)
        assert trader._thread.is_alive() is False


# ── Concurrent entry and monitoring ──────────────────────────────────────

@patch("core.equity_trader.now_ist")
def test_equity_trader_enter_then_monitor(mock_now) -> None:
    """After entering a position, monitoring should not remove it if price is stable."""
    from datetime import datetime
    mock_now.return_value = datetime(2026, 6, 11, 11, 0)

    price_fn = MagicMock(return_value=2500.0)
    cfg = {
        "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
        "EQUITY_PRIORITY": ["RELIANCE"],
        "EQUITY_SL_PCT": 0.95,
        "EQUITY_TARGET_PCT": 1.05,
    }
    trader = EquityTrader(cfg=cfg, get_price_fn=price_fn)
    trader.enter_position("RELIANCE", "BUY", 80)

    # Monitor should not exit (price is same as entry, within range)
    trader._monitor_positions()
    assert "RELIANCE" in trader._positions
