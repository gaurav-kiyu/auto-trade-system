"""Tests for core.strategy.futures_trader."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.strategy.futures_trader import FuturesPosition, FuturesTrader, run_futures_trader


class TestFuturesPosition:
    """Tests for FuturesPosition dataclass."""

    def test_basic_creation(self):
        pos = FuturesPosition(symbol="NIFTY24DECFUT", direction="BUY", qty=50, entry_price=20000.0)
        assert pos.symbol == "NIFTY24DECFUT"
        assert pos.direction == "BUY"
        assert pos.qty == 50
        assert pos.entry_price == 20000.0
        assert pos.current_price == 0.0  # Default
        assert pos.asset_class == "FUTURES"

    def test_default_values(self):
        pos = FuturesPosition(symbol="TEST", direction="SELL", qty=1, entry_price=100.0)
        assert pos.margin_used == 0.0
        assert pos.unrealized_pnl == 0.0
        assert pos.realized_pnl == 0.0
        assert pos.expiry == ""
        assert pos.entry_time == 0.0
        assert pos.score == 0
        assert pos.reason == ""


class TestFuturesTrader:
    """Tests for FuturesTrader engine."""

    def test_initialization_defaults(self):
        t = FuturesTrader()
        assert t.is_running is False
        assert t.positions == {}
        assert t.all_symbols == []
        status = t.status()
        assert status["running"] is False
        assert status["positions"] == 0
        assert status["daily_trades"] == 0

    def test_initialization_with_config(self):
        cfg = {
            "FUTURES_MAP": {"NIFTY": {"enabled": True}},
            "FUTURES_ENABLED": True,
            "FUTURES_DEFAULT_QTY": 75,
            "FUTURES_SL_PCT": 0.97,
            "FUTURES_TARGET_PCT": 1.03,
        }
        t = FuturesTrader(cfg=cfg)
        assert "NIFTY" in t.all_symbols
        status = t.status()
        assert status["symbols_total"] >= 1
        assert t._default_qty == 75
        assert t._sl_pct == 0.97

    def test_start_stop(self):
        t = FuturesTrader()
        t.start()
        assert t.is_running is True
        t.stop()
        assert t.is_running is False

    def test_double_start(self):
        t = FuturesTrader()
        t.start()
        t.start()  # Should not crash
        assert t.is_running is True
        t.stop()

    def test_can_trade_no_symbols(self):
        t = FuturesTrader()
        ok, reason = t.can_trade()
        assert ok is False
        assert "No futures symbols configured" in reason

    def test_can_trade_with_symbols_market_closed(self):
        cfg = {"FUTURES_MAP": {"NIFTY": {"enabled": True}}, "FUTURES_ENABLED": True}
        t = FuturesTrader(cfg=cfg)
        ok, reason = t.can_trade()
        # On a real system, market may or may not be open. We just check it doesn't crash.
        assert isinstance(ok, bool)
        assert isinstance(reason, str)

    def test_can_trade_daily_limit_reached(self):
        cfg = {"FUTURES_MAP": {"NIFTY": {"enabled": True}}, "FUTURES_ENABLED": True, "FUTURES_MAX_DAILY_TRADES": 2}
        t = FuturesTrader(cfg=cfg)
        t._daily_trades = 2  # Manually set limit
        with patch.object(t, '_is_market_open', return_value=True):
            ok, reason = t.can_trade()
            assert ok is False
            assert "Max daily trades" in reason

    def test_enter_position_basic(self):
        t = FuturesTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            result = t.enter_position("TEST", "BUY", score=75, entry_price=100.0)
            assert result is True
            assert "TEST" in t.positions
            assert t.positions["TEST"]["direction"] == "BUY"
            assert t.positions["TEST"]["qty"] == 50  # default qty

    def test_enter_position_market_closed(self):
        t = FuturesTrader()
        with patch.object(t, '_is_market_open', return_value=False):
            result = t.enter_position("TEST", "BUY", score=75, entry_price=100.0)
            assert result is False
            assert "TEST" not in t.positions

    def test_enter_duplicate_position(self):
        t = FuturesTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("TEST", "BUY", score=75, entry_price=100.0)
            result2 = t.enter_position("TEST", "BUY", score=80, entry_price=105.0)
            assert result2 is False  # Already have position

    def test_enter_position_with_custom_qty(self):
        t = FuturesTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            result = t.enter_position("TEST", "BUY", score=75, entry_price=100.0, qty=100)
            assert result is True
            assert t.positions["TEST"]["qty"] == 100

    def test_exit_position(self):
        t = FuturesTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("TEST", "BUY", score=75, entry_price=100.0)
            result = t.exit_position("TEST", "TARGET_HIT", exit_price=105.0)
            assert result is True
            assert "TEST" not in t.positions

    def test_exit_nonexistent_position(self):
        t = FuturesTrader()
        result = t.exit_position("NONEXISTENT", "MANUAL")
        assert result is False

    def test_exit_with_execution_callback(self):
        mock_exit = MagicMock(return_value=True)
        t = FuturesTrader(execute_exit_fn=mock_exit)
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("TEST", "BUY", score=75, entry_price=100.0)
            t.exit_position("TEST", "TARGET_HIT", exit_price=105.0)
            mock_exit.assert_called_once()

    def test_exit_with_entry_callback(self):
        mock_entry = MagicMock(return_value=True)
        t = FuturesTrader(execute_entry_fn=mock_entry)
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("TEST", "BUY", score=75, entry_price=100.0)
            mock_entry.assert_called_once()

    def test_entry_callback_failure(self):
        mock_entry = MagicMock(return_value=False)
        t = FuturesTrader(execute_entry_fn=mock_entry)
        with patch.object(t, '_is_market_open', return_value=True):
            result = t.enter_position("TEST", "BUY", score=75, entry_price=100.0)
            assert result is False

    def test_sl_trigger(self):
        t = FuturesTrader(cfg={"FUTURES_SL_PCT": 0.97})
        mock_price = MagicMock(side_effect=lambda sym: 95.0 if sym == "TEST" else None)
        t._get_price_fn = mock_price
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("TEST", "BUY", score=75, entry_price=100.0)
        # Run monitor - should trigger SL (95 < 97 = 100*0.97)
        t._monitor_positions()
        assert "TEST" not in t.positions

    def test_target_trigger(self):
        t = FuturesTrader(cfg={"FUTURES_TARGET_PCT": 1.05})
        mock_price = MagicMock(side_effect=lambda sym: 106.0 if sym == "TEST" else None)
        t._get_price_fn = mock_price
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("TEST", "BUY", score=75, entry_price=100.0)
        t._monitor_positions()
        assert "TEST" not in t.positions

    def test_sell_sl_trigger(self):
        t = FuturesTrader(cfg={"FUTURES_SL_PCT": 0.97})
        mock_price = MagicMock(side_effect=lambda sym: 104.0 if sym == "TEST" else None)
        t._get_price_fn = mock_price
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("TEST", "SELL", score=75, entry_price=100.0)
        t._monitor_positions()
        assert "TEST" not in t.positions

    def test_status_with_positions(self):
        t = FuturesTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("NIFTY", "BUY", score=80, entry_price=20000.0, qty=50)
            t.enter_position("BANKNIFTY", "SELL", score=70, entry_price=45000.0, qty=30)
        status = t.status()
        assert status["positions"] == 2
        assert status["daily_trades"] == 2
        assert len(status["positions_detail"]) == 2

    def test_status_mtm_calculation(self):
        t = FuturesTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("TEST", "BUY", score=75, entry_price=100.0, qty=10)
        # Update current price to 110
        with t._lock:
            if "TEST" in t._positions:
                t._positions["TEST"].current_price = 110.0
        status = t.status()
        assert status["total_mtm"] == 100.0  # (110-100)*10

    def test_reset_daily_if_needed(self):
        t = FuturesTrader()
        t._daily_trades = 5
        t._current_day = "1999-01-01"  # Old date, will trigger reset
        t._reset_daily_if_needed()
        assert t._daily_trades == 0  # Reset happened

    def test_build_symbols_enabled(self):
        cfg = {
            "FUTURES_MAP": {"NIFTY": {"enabled": True}, "BANKNIFTY": {"enabled": False}},
            "FUTURES_ENABLED": True,
        }
        t = FuturesTrader(cfg=cfg)
        # _build_symbols called internally during init
        assert "NIFTY" in t.all_symbols
        assert "BANKNIFTY" not in t.all_symbols

    def test_build_symbols_disabled(self):
        cfg = {"FUTURES_ENABLED": False}
        t = FuturesTrader(cfg=cfg)
        assert len(t.all_symbols) == len(t._commodity_symbols)  # Only commodity if enabled separately

    def test_commodity_symbols(self):
        cfg = {"COMMODITY_MAP": {"GOLD": {"enabled": True}}, "COMMODITY_PRIORITY": ["GOLD"], "COMMODITY_ENABLED": True}
        t = FuturesTrader(cfg=cfg)
        assert "GOLD" in t.all_symbols

    def test_currency_symbols(self):
        cfg = {"CURRENCY_MAP": {"USDINR": {"enabled": True}}, "CURRENCY_PRIORITY": ["USDINR"], "CURRENCY_ENABLED": True}
        t = FuturesTrader(cfg=cfg)
        assert "USDINR" in t.all_symbols

    def test_run_futures_trader_factory(self):
        trader = run_futures_trader()
        assert isinstance(trader, FuturesTrader)
        assert trader.is_running is True
        trader.stop()

    def test_run_futures_trader_with_callbacks(self):
        send_fn = MagicMock()
        get_price = MagicMock()
        trader = run_futures_trader(send_fn=send_fn, get_price_fn=get_price)
        assert trader.is_running is True
        trader.stop()

    def test_enter_position_with_expiry(self):
        t = FuturesTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            result = t.enter_position("NIFTY", "BUY", score=75, entry_price=20000.0, expiry="2024-12-26")
            assert result is True
            assert t.positions["NIFTY"]["expiry"] == "2024-12-26"

    def test_exit_without_exit_price(self):
        t = FuturesTrader()
        mock_price = MagicMock(return_value=110.0)
        t._get_price_fn = mock_price
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("TEST", "BUY", score=75, entry_price=100.0)
        result = t.exit_position("TEST", "MANUAL")
        assert result is True
        mock_price.assert_called()

    def test_send_fn_called_on_entry(self):
        send_fn = MagicMock()
        t = FuturesTrader(send_fn=send_fn)
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("TEST", "BUY", score=75, entry_price=100.0)
        send_fn.assert_called()

    def test_send_fn_called_on_exit(self):
        send_fn = MagicMock()
        t = FuturesTrader(send_fn=send_fn)
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("TEST", "BUY", score=75, entry_price=100.0)
        send_fn.reset_mock()
        t.exit_position("TEST", "TARGET_HIT")
        send_fn.assert_called()

    def test_positions_property(self):
        t = FuturesTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("TEST", "BUY", score=75, entry_price=100.0, qty=10)
        pos = t.positions
        assert "TEST" in pos
        assert pos["TEST"]["direction"] == "BUY"
        assert pos["TEST"]["qty"] == 10
        assert pos["TEST"]["entry_price"] == 100.0

    def test_thread_safe_enter_exit(self):
        """Concurrent operations should not corrupt state."""
        import threading
        # Increase daily limit to allow all 20 entries
        cfg = {"FUTURES_MAX_DAILY_TRADES": 30}
        t = FuturesTrader(cfg=cfg)
        with patch.object(t, '_is_market_open', return_value=True):
            threads = []
            for i in range(20):
                sym = f"SYM{i}"
                thr = threading.Thread(target=t.enter_position, args=(sym, "BUY", 50), kwargs={"entry_price": 100.0})
                threads.append(thr)
                thr.start()
            for thr in threads:
                thr.join()
            # All 20 should have entered
            assert len(t.positions) == 20
