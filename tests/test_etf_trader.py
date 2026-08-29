"""Tests for ETFTrader - ETF trading entry, exit, monitoring, and status."""

from __future__ import annotations

from core.etf_trader import ETFTradePosition, ETFTrader, run_etf_trader


class TestETFTrader:
    """ETFTrader - core trading logic."""

    def test_init_empty(self):
        """ETFTrader initializes with no symbols when disabled."""
        t = ETFTrader()
        assert t.is_running is False
        assert t.all_symbols == []

    def test_init_with_disabled_config(self):
        """ETFTrader with ETF_ENABLED=False should have no symbols."""
        t = ETFTrader(cfg={"ETF_ENABLED": False})
        assert t.all_symbols == []

    def test_start_stop(self):
        """ETFTrader starts and stops cleanly."""
        t = ETFTrader()
        t.start()
        assert t.is_running is True
        t.stop()
        assert t.is_running is False

    def test_can_trade_no_symbols(self):
        """can_trade returns False with no symbols."""
        t = ETFTrader()
        ok, msg = t.can_trade()
        assert ok is False
        assert "No ETF symbols" in msg

    def test_can_trade_market_closed(self):
        """can_trade returns False when market is closed (deterministic mock)."""
        cfg = {"ETF_ENABLED": True, "ETF_MAP": {"NIFTYBEES": {"enabled": True}}}
        t = ETFTrader(cfg=cfg)
        # Force market-closed regardless of wall-clock time (test was
        # time-dependent and failed whenever run during live market hours)
        t._is_market_open = lambda: False
        ok, msg = t.can_trade()
        assert ok is False
        assert "closed" in msg or "symbols" in msg

    def test_enter_position_not_enabled(self):
        """enter_position fails when no symbols configured."""
        t = ETFTrader()
        assert t.enter_position("NIFTYBEES", "BUY", 50) is False

    def test_enter_exit_position(self):
        """Full enter/exit cycle."""
        cfg = {"ETF_ENABLED": True, "ETF_MAP": {"NIFTYBEES": {"enabled": True, "expense_ratio": 0.0005}}}
        def price_fn(sym):
            return 250.0
        t = ETFTrader(cfg=cfg, get_price_fn=price_fn)
        # Mock market open
        t._is_market_open = lambda: True
        assert t.enter_position("NIFTYBEES", "BUY", 75, entry_price=250.0) is True
        assert len(t.positions) == 1
        pos = t.positions["NIFTYBEES"]
        assert pos["direction"] == "BUY"
        assert pos["qty"] == 1
        assert pos["entry_price"] == 250.0
        assert pos["expense_ratio"] == 0.0005

        # Exit
        assert t.exit_position("NIFTYBEES", "TARGET_HIT", exit_price=262.0) is True
        assert len(t.positions) == 0

    def test_double_entry_blocked(self):
        """Same symbol entered twice should be rejected."""
        cfg = {"ETF_ENABLED": True, "ETF_MAP": {"NIFTYBEES": {"enabled": True}}}
        def price_fn(sym):
            return 250.0
        t = ETFTrader(cfg=cfg, get_price_fn=price_fn)
        t._is_market_open = lambda: True
        assert t.enter_position("NIFTYBEES", "BUY", 75, entry_price=250.0) is True
        assert t.enter_position("NIFTYBEES", "BUY", 80, entry_price=251.0) is False

    def test_exit_nonexistent_position(self):
        """Exiting a non-existent position returns False."""
        t = ETFTrader()
        assert t.exit_position("NONEXISTENT", "MANUAL") is False

    def test_max_daily_trades(self):
        """Max daily trades limit is respected."""
        cfg = {"ETF_ENABLED": True, "ETF_MAP": {"NIFTYBEES": {"enabled": True}}, "ETF_MAX_DAILY_TRADES": 2}
        def price_fn(sym):
            return 250.0
        t = ETFTrader(cfg=cfg, get_price_fn=price_fn)
        t._is_market_open = lambda: True
        t._daily_trades = 2
        assert t.can_trade()[0] is False

    def test_status(self):
        """status() returns expected keys."""
        t = ETFTrader()
        s = t.status()
        assert "running" in s
        assert "positions" in s
        assert "symbols" in s

    def test_status_with_position(self):
        """status() reflects active positions."""
        cfg = {"ETF_ENABLED": True, "ETF_MAP": {"NIFTYBEES": {"enabled": True}}}
        def price_fn(sym):
            return 250.0
        t = ETFTrader(cfg=cfg, get_price_fn=price_fn)
        t._is_market_open = lambda: True
        t.enter_position("NIFTYBEES", "BUY", 75, entry_price=250.0)
        s = t.status()
        assert s["positions"] == 1

    def test_run_etf_trader_factory(self):
        """run_etf_trader creates and starts the trader."""
        t = run_etf_trader()
        assert t.is_running is True
        t.stop()
        assert t.is_running is False

    def test_premium_too_high_blocks_entry(self):
        """ETF with >2% premium over NAV should be rejected."""
        cfg = {"ETF_ENABLED": True, "ETF_MAP": {"GOLDBEES": {"enabled": True}}}
        def price_fn(sym):
            return 520.0  # Market price 520
        def nav_fn(sym):
            return 500.0    # NAV 500 -> 4% premium -> blocked
        t = ETFTrader(cfg=cfg, get_price_fn=price_fn, get_nav_fn=nav_fn)
        t._is_market_open = lambda: True
        assert t.enter_position("GOLDBEES", "BUY", 75, entry_price=520.0) is False

    def test_premium_acceptable_allows_entry(self):
        """ETF with <2% premium over NAV should be accepted."""
        cfg = {"ETF_ENABLED": True, "ETF_MAP": {"GOLDBEES": {"enabled": True}}}
        def price_fn(sym):
            return 505.0  # Market price 505
        def nav_fn(sym):
            return 500.0    # NAV 500 -> 1% premium -> accepted
        t = ETFTrader(cfg=cfg, get_price_fn=price_fn, get_nav_fn=nav_fn)
        t._is_market_open = lambda: True
        assert t.enter_position("GOLDBEES", "BUY", 75, entry_price=505.0) is True

    def test_start_ignores_if_already_running(self):
        """Calling start() twice should not create a second thread."""
        t = ETFTrader()
        t.start()
        thread_id = id(t._thread)
        t.start()  # Second call should be no-op
        assert id(t._thread) == thread_id
        t.stop()

    def test_stop_ignores_if_not_running(self):
        """Calling stop() when not running should not raise."""
        t = ETFTrader()
        t.stop()  # Should not raise

    def test_send_fn_called(self):
        """send_fn should be called on enter/exit."""
        messages = []
        cfg = {"ETF_ENABLED": True, "ETF_MAP": {"NIFTYBEES": {"enabled": True}}}
        def price_fn(sym):
            return 250.0
        t = ETFTrader(cfg=cfg, send_fn=lambda msg, **kw: messages.append(msg), get_price_fn=price_fn)
        t._is_market_open = lambda: True
        t.enter_position("NIFTYBEES", "BUY", 75, entry_price=250.0)
        assert any("Entered" in m for m in messages)
        t.exit_position("NIFTYBEES", "TARGET_HIT", exit_price=260.0)
        assert any("Exited" in m for m in messages)

    def test_enter_sell_direction(self):
        """Enter a SELL position."""
        cfg = {"ETF_ENABLED": True, "ETF_MAP": {"NIFTYBEES": {"enabled": True}}}
        def price_fn(sym):
            return 250.0
        t = ETFTrader(cfg=cfg, get_price_fn=price_fn)
        t._is_market_open = lambda: True
        assert t.enter_position("NIFTYBEES", "SELL", 70, entry_price=250.0) is True
        assert t.positions["NIFTYBEES"]["direction"] == "SELL"

    def test_sl_hit_exit(self):
        """Position should exit when price hits stop loss."""
        calls = []
        cfg = {"ETF_ENABLED": True, "ETF_MAP": {"NIFTYBEES": {"enabled": True}}}
        prices = {"NIFTYBEES": 100.0}

        def get_price(sym):
            return prices.get(sym)

        t = ETFTrader(cfg=cfg, get_price_fn=get_price, send_fn=lambda msg, **kw: calls.append(msg))
        t._is_market_open = lambda: True
        t.enter_position("NIFTYBEES", "BUY", 75, entry_price=100.0)
        # Price drops below SL (default SL_PCT=0.95, so 5% loss = price <= 95)
        prices["NIFTYBEES"] = 94.0
        t._monitor_positions()
        assert len(t.positions) == 0
        assert any("SL_HIT" in m for m in calls)


class TestETFTradePosition:
    """ETFTradePosition dataclass behavior."""

    def test_to_dict(self):
        """to_dict returns expected keys."""
        pos = ETFTradePosition(symbol="NIFTYBEES", direction="BUY", qty=10, entry_price=250.0,
                               nav_price=248.0, expense_ratio=0.0005, aum_crores=10000.0)
        d = pos.to_dict()
        assert d["symbol"] == "NIFTYBEES"
        assert d["direction"] == "BUY"
        assert d["qty"] == 10
        assert d["entry_price"] == 250.0
        assert d["nav_price"] == 248.0
        assert d["expense_ratio"] == 0.0005
        assert d["aum_crores"] == 10000.0
