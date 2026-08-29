"""Tests for core.commodity_trader."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.commodity_trader import CommodityTradePosition, CommodityTrader, run_commodity_trader


class TestCommodityTradePosition:
    def test_basic_creation(self):
        pos = CommodityTradePosition(symbol="GOLD", direction="BUY", qty=1, entry_price=65000.0)
        assert pos.symbol == "GOLD"
        assert pos.direction == "BUY"
        assert pos.qty == 1
        assert pos.entry_price == 65000.0
        assert pos.asset_class == "COMMODITY"

    def test_defaults(self):
        pos = CommodityTradePosition(symbol="CRUDEOIL", direction="SELL", qty=100, entry_price=5000.0)
        assert pos.margin_used == 0.0
        assert pos.current_price == 0.0
        assert pos.expiry == ""


class TestCommodityTrader:
    def test_init_defaults(self):
        t = CommodityTrader()
        assert t.is_running is False
        assert t.positions == {}
        assert t.all_symbols == []

    def test_init_with_config(self):
        cfg = {"COMMODITY_MAP": {"GOLD": {"enabled": True}}, "COMMODITY_ENABLED": True, "COMMODITY_PRIORITY": ["GOLD"]}
        t = CommodityTrader(cfg=cfg)
        assert "GOLD" in t.all_symbols

    def test_start_stop(self):
        t = CommodityTrader()
        t.start()
        assert t.is_running is True
        t.stop()
        assert t.is_running is False

    def test_can_trade_no_symbols(self):
        t = CommodityTrader()
        ok, reason = t.can_trade()
        assert ok is False
        assert "No commodity symbols" in reason

    def test_can_trade_daily_limit(self):
        cfg = {"COMMODITY_MAP": {"GOLD": {"enabled": True}}, "COMMODITY_ENABLED": True, "COMMODITY_PRIORITY": ["GOLD"], "COMMODITY_MAX_DAILY_TRADES": 5}
        t = CommodityTrader(cfg=cfg)
        t._daily_trades = 5
        with patch.object(t, '_is_market_open', return_value=True):
            ok, reason = t.can_trade()
            assert ok is False
            assert "Max daily trades" in reason

    def test_enter_position(self):
        t = CommodityTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            result = t.enter_position("GOLD", "BUY", 80, entry_price=65000.0)
            assert result is True
            assert "GOLD" in t.positions
            assert t.positions["GOLD"]["direction"] == "BUY"

    def test_enter_market_closed(self):
        t = CommodityTrader()
        with patch.object(t, '_is_market_open', return_value=False):
            result = t.enter_position("GOLD", "BUY", 80, entry_price=65000.0)
            assert result is False

    def test_enter_duplicate(self):
        t = CommodityTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("GOLD", "BUY", 80, entry_price=65000.0)
            result2 = t.enter_position("GOLD", "BUY", 80, entry_price=65100.0)
            assert result2 is False

    def test_exit_position(self):
        t = CommodityTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("GOLD", "BUY", 80, entry_price=65000.0)
            result = t.exit_position("GOLD", "TARGET_HIT", exit_price=68000.0)
            assert result is True
            assert "GOLD" not in t.positions

    def test_exit_nonexistent(self):
        t = CommodityTrader()
        result = t.exit_position("GOLD", "MANUAL")
        assert result is False

    def test_sl_trigger(self):
        t = CommodityTrader(cfg={"COMMODITY_SL_PCT": 0.97})
        mock_price = MagicMock(side_effect=lambda sym: 62000.0 if sym == "GOLD" else None)
        t._get_price_fn = mock_price
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("GOLD", "BUY", 80, entry_price=65000.0)
        t._monitor_positions()
        assert "GOLD" not in t.positions

    def test_target_trigger(self):
        t = CommodityTrader(cfg={"COMMODITY_TARGET_PCT": 1.05})
        mock_price = MagicMock(side_effect=lambda sym: 69000.0 if sym == "GOLD" else None)
        t._get_price_fn = mock_price
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("GOLD", "BUY", 80, entry_price=65000.0)
        t._monitor_positions()
        assert "GOLD" not in t.positions

    def test_status(self):
        t = CommodityTrader()
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("GOLD", "BUY", 80, entry_price=65000.0, qty=1)
        status = t.status()
        assert status["positions"] == 1
        assert status["symbols"] >= 0
        assert "sl_pct" in status
        assert "target_pct" in status

    def test_run_factory(self):
        trader = run_commodity_trader()
        assert isinstance(trader, CommodityTrader)
        assert trader.is_running is True
        trader.stop()

    def test_symbol_building(self):
        cfg = {"COMMODITY_MAP": {"GOLD": {"enabled": True}, "SILVER": {"enabled": False}}, "COMMODITY_ENABLED": True, "COMMODITY_PRIORITY": ["GOLD", "SILVER"]}
        t = CommodityTrader(cfg=cfg)
        assert "GOLD" in t.all_symbols
        assert "SILVER" not in t.all_symbols

    def test_send_fn_called_on_entry(self):
        send_fn = MagicMock()
        t = CommodityTrader(send_fn=send_fn)
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("GOLD", "BUY", 80, entry_price=65000.0)
        send_fn.assert_called()

    def test_send_fn_called_on_exit(self):
        send_fn = MagicMock()
        t = CommodityTrader(send_fn=send_fn)
        with patch.object(t, '_is_market_open', return_value=True):
            t.enter_position("GOLD", "BUY", 80, entry_price=65000.0)
        send_fn.reset_mock()
        t.exit_position("GOLD", "TARGET_HIT")
        send_fn.assert_called()

    def test_thread_safe_enter_exit(self):
        import threading
        cfg = {"COMMODITY_MAX_DAILY_TRADES": 30}
        t = CommodityTrader(cfg=cfg)
        with patch.object(t, '_is_market_open', return_value=True):
            threads = []
            for i in range(15):
                sym = f"SYM{i}"
                thr = threading.Thread(target=t.enter_position, args=(sym, "BUY", 50), kwargs={"entry_price": 100.0})
                threads.append(thr)
                thr.start()
            for thr in threads:
                thr.join()
            assert len(t.positions) == 15

    def test_entry_callback_failure(self):
        mock_entry = MagicMock(return_value=False)
        t = CommodityTrader(execute_entry_fn=mock_entry)
        with patch.object(t, '_is_market_open', return_value=True):
            result = t.enter_position("GOLD", "BUY", 80, entry_price=65000.0)
            assert result is False
