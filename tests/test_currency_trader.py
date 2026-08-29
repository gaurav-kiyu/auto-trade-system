"""Tests for core.currency_trader."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.currency_trader import CurrencyTradePosition, CurrencyTrader, run_currency_trader


class TestCurrencyTradePosition:
    def test_basic_creation(self):
        pos = CurrencyTradePosition(symbol="USDINR", direction="BUY", qty=1000, entry_price=83.50)
        assert pos.symbol == "USDINR"
        assert pos.direction == "BUY"
        assert pos.qty == 1000
        assert pos.entry_price == 83.50
        assert pos.asset_class == "CURRENCY"

    def test_defaults(self):
        pos = CurrencyTradePosition(symbol="EURINR", direction="SELL", qty=1000, entry_price=92.0)
        assert pos.current_price == 0.0
        assert pos.margin_used == 0.0
        assert pos.expiry == ""


class TestCurrencyTrader:
    def test_init_defaults(self):
        t = CurrencyTrader()
        assert t.is_running is False
        assert t.positions == {}
        assert t.all_symbols == []

    def test_init_with_config(self):
        cfg = {"CURRENCY_MAP": {"USDINR": {"enabled": True}}, "CURRENCY_ENABLED": True, "CURRENCY_PRIORITY": ["USDINR"]}
        t = CurrencyTrader(cfg=cfg)
        assert "USDINR" in t.all_symbols

    def test_start_stop(self):
        t = CurrencyTrader()
        t.start()
        assert t.is_running is True
        t.stop()
        assert t.is_running is False

    def test_can_trade_no_symbols(self):
        t = CurrencyTrader()
        ok, reason = t.can_trade()
        assert ok is False
        assert "No currency symbols" in reason

    def test_can_trade_daily_limit(self):
        cfg = {"CURRENCY_MAP": {"USDINR": {"enabled": True}}, "CURRENCY_ENABLED": True, "CURRENCY_PRIORITY": ["USDINR"], "CURRENCY_MAX_DAILY_TRADES": 3}
        t = CurrencyTrader(cfg=cfg)
        t._daily_trades = 3
        with patch.object(t, '_is_market_open', return_value=True):
            ok, reason = t.can_trade()
            assert ok is False
            assert "Max daily trades" in reason

    def test_enter_position(self):
        t = CurrencyTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            result = t.enter_position("USDINR", "BUY", 75, entry_price=83.50)
            assert result is True
            assert "USDINR" in t.positions
            assert t.positions["USDINR"]["direction"] == "BUY"

    def test_enter_market_closed(self):
        t = CurrencyTrader()
        with patch.object(t, '_is_market_open', return_value=False):
            result = t.enter_position("USDINR", "BUY", 75, entry_price=83.50)
            assert result is False

    def test_enter_duplicate(self):
        t = CurrencyTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("USDINR", "BUY", 75, entry_price=83.50)
            result2 = t.enter_position("USDINR", "BUY", 80, entry_price=83.60)
            assert result2 is False

    def test_exit_position(self):
        t = CurrencyTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("USDINR", "BUY", 75, entry_price=83.50)
            result = t.exit_position("USDINR", "TARGET_HIT", exit_price=84.00)
            assert result is True
            assert "USDINR" not in t.positions

    def test_exit_nonexistent(self):
        t = CurrencyTrader()
        result = t.exit_position("USDINR", "MANUAL")
        assert result is False

    def test_sl_trigger(self):
        t = CurrencyTrader(cfg={"CURRENCY_SL_PCT": 0.97})
        mock_price = MagicMock(side_effect=lambda sym: 80.0 if sym == "USDINR" else None)
        t._get_price_fn = mock_price
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("USDINR", "BUY", 75, entry_price=83.50)
        t._monitor_positions()
        assert "USDINR" not in t.positions

    def test_target_trigger(self):
        t = CurrencyTrader(cfg={"CURRENCY_TARGET_PCT": 1.05})
        mock_price = MagicMock(side_effect=lambda sym: 88.0 if sym == "USDINR" else None)
        t._get_price_fn = mock_price
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("USDINR", "BUY", 75, entry_price=83.50)
        t._monitor_positions()
        assert "USDINR" not in t.positions

    def test_status(self):
        t = CurrencyTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("USDINR", "BUY", 75, entry_price=83.50, qty=1000)
        status = t.status()
        assert status["positions"] == 1
        assert status["symbols"] >= 0

    def test_run_factory(self):
        trader = run_currency_trader()
        assert isinstance(trader, CurrencyTrader)
        assert trader.is_running is True
        trader.stop()

    def test_symbol_building(self):
        cfg = {"CURRENCY_MAP": {"USDINR": {"enabled": True}, "EURINR": {"enabled": False}}, "CURRENCY_ENABLED": True, "CURRENCY_PRIORITY": ["USDINR", "EURINR"]}
        t = CurrencyTrader(cfg=cfg)
        assert "USDINR" in t.all_symbols
        assert "EURINR" not in t.all_symbols

    def test_default_qty(self):
        t = CurrencyTrader()
        assert t._default_qty == 1000  # CDS default lot size

    def test_send_fn_called_on_entry(self):
        send_fn = MagicMock()
        t = CurrencyTrader(send_fn=send_fn)
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("USDINR", "BUY", 75, entry_price=83.50)
        send_fn.assert_called()

    def test_send_fn_called_on_exit(self):
        send_fn = MagicMock()
        t = CurrencyTrader(send_fn=send_fn)
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("USDINR", "BUY", 75, entry_price=83.50)
        send_fn.reset_mock()
        t.exit_position("USDINR", "TARGET_HIT")
        send_fn.assert_called()

    def test_thread_safe_enter_exit(self):
        import threading
        cfg = {"CURRENCY_MAX_DAILY_TRADES": 30}
        t = CurrencyTrader(cfg=cfg)
        with patch.object(t, '_is_market_open', return_value=True):
            threads = []
            for i in range(15):
                sym = f"CCY{i}"
                thr = threading.Thread(target=t.enter_position, args=(sym, "BUY", 50), kwargs={"entry_price": 100.0})
                threads.append(thr)
                thr.start()
            for thr in threads:
                thr.join()
            assert len(t.positions) == 15

    def test_entry_callback_failure(self):
        mock_entry = MagicMock(return_value=False)
        t = CurrencyTrader(execute_entry_fn=mock_entry)
        with patch.object(t, '_is_market_open', return_value=True):
            result = t.enter_position("USDINR", "BUY", 75, entry_price=83.50)
            assert result is False
