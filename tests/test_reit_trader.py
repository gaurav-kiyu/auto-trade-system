"""Tests for REITTrader - REIT/InvIT trading entry, exit, monitoring, and status."""

from __future__ import annotations

from core.reit_trader import REITTradePosition, REITTrader, run_reit_trader


class TestREITTrader:
    """REITTrader - core trading logic."""

    def test_init_empty(self):
        """REITTrader initializes with no symbols when disabled."""
        t = REITTrader()
        assert t.is_running is False
        assert t.all_symbols == []

    def test_init_with_disabled_config(self):
        """REITTrader with REIT_ENABLED=False should have no symbols."""
        t = REITTrader(cfg={"REIT_ENABLED": False})
        assert t.all_symbols == []

    def test_start_stop(self):
        """REITTrader starts and stops cleanly."""
        t = REITTrader()
        t.start()
        assert t.is_running is True
        t.stop()
        assert t.is_running is False

    def test_can_trade_no_symbols(self):
        """can_trade returns False with no symbols."""
        t = REITTrader()
        ok, msg = t.can_trade()
        assert ok is False
        assert "No REIT/InvIT symbols" in msg

    def test_enter_position_not_enabled(self):
        """enter_position fails when no symbols configured."""
        t = REITTrader()
        assert t.enter_position("EMBASSY", "BUY", 50) is False

    def test_enter_exit_position(self):
        """Full enter/exit cycle for a REIT."""
        cfg = {"REIT_ENABLED": True, "REIT_MAP": {"EMBASSY": {"enabled": True, "distribution_yield": 0.06}}}
        def price_fn(sym):
            return 350.0
        t = REITTrader(cfg=cfg, get_price_fn=price_fn)
        t._is_market_open = lambda: True
        assert t.enter_position("EMBASSY", "BUY", 75, entry_price=350.0) is True
        assert len(t.positions) == 1
        pos = t.positions["EMBASSY"]
        assert pos["direction"] == "BUY"
        assert pos["qty"] == 1
        assert pos["entry_price"] == 350.0
        assert pos["trust_type"] == "REIT"
        assert pos["distribution_yield"] == 0.06

        t.exit_position("EMBASSY", "TARGET_HIT", exit_price=370.0)
        assert len(t.positions) == 0

    def test_enter_exit_invit(self):
        """Full enter/exit cycle for an InvIT."""
        cfg = {"INVIT_ENABLED": True, "INVIT_MAP": {"IRBINVIT": {"enabled": True, "sector": "Roads"}}}
        def price_fn(sym):
            return 120.0
        t = REITTrader(cfg=cfg, get_price_fn=price_fn)
        t._is_market_open = lambda: True
        assert t.enter_position("IRBINVIT", "BUY", 70, entry_price=120.0) is True
        assert t.positions["IRBINVIT"]["trust_type"] == "INVIT"
        assert t.positions["IRBINVIT"]["sector"] == "Roads"

        t.exit_position("IRBINVIT", "TARGET_HIT", exit_price=125.0)
        assert len(t.positions) == 0

    def test_double_entry_blocked(self):
        """Same symbol entered twice should be rejected."""
        cfg = {"REIT_ENABLED": True, "REIT_MAP": {"EMBASSY": {"enabled": True}}}
        def price_fn(sym):
            return 350.0
        t = REITTrader(cfg=cfg, get_price_fn=price_fn)
        t._is_market_open = lambda: True
        assert t.enter_position("EMBASSY", "BUY", 75, entry_price=350.0) is True
        assert t.enter_position("EMBASSY", "BUY", 80, entry_price=351.0) is False

    def test_exit_nonexistent_position(self):
        """Exiting a non-existent position returns False."""
        t = REITTrader()
        assert t.exit_position("NONEXISTENT", "MANUAL") is False

    def test_max_daily_trades(self):
        """Max daily trades limit is respected."""
        cfg = {"REIT_ENABLED": True, "REIT_MAP": {"EMBASSY": {"enabled": True}}, "REIT_MAX_DAILY_TRADES": 2}
        def price_fn(sym):
            return 350.0
        t = REITTrader(cfg=cfg, get_price_fn=price_fn)
        t._is_market_open = lambda: True
        t._daily_trades = 2
        assert t.can_trade()[0] is False

    def test_status(self):
        """status() returns expected keys."""
        t = REITTrader()
        s = t.status()
        assert "running" in s
        assert "positions" in s
        assert "symbols" in s
        assert "sector_exposure" in s

    def test_sector_exposure(self):
        """get_sector_exposure returns per-sector breakdown."""
        cfg = {
            "REIT_ENABLED": True,
            "REIT_MAP": {
                "EMBASSY": {"enabled": True, "sector": "Commercial"},
                "MINDSPACE": {"enabled": True, "sector": "Commercial"},
            },
        }
        def price_fn(sym):
            return 350.0
        t = REITTrader(cfg=cfg, get_price_fn=price_fn)
        t._is_market_open = lambda: True
        t.enter_position("EMBASSY", "BUY", 75, entry_price=350.0)
        exposure = t.get_sector_exposure()
        assert "Commercial" in exposure
        assert exposure["Commercial"] > 0

    def test_run_reit_trader_factory(self):
        """run_reit_trader creates and starts the trader."""
        t = run_reit_trader()
        assert t.is_running is True
        t.stop()
        assert t.is_running is False

    def test_sl_hit_exit(self):
        """Position should exit when price hits stop loss."""
        calls = []
        cfg = {"REIT_ENABLED": True, "REIT_MAP": {"EMBASSY": {"enabled": True}}}
        prices = {"EMBASSY": 100.0}

        def get_price(sym):
            return prices.get(sym)

        t = REITTrader(cfg=cfg, get_price_fn=get_price, send_fn=lambda msg, **kw: calls.append(msg))
        t._is_market_open = lambda: True
        t.enter_position("EMBASSY", "BUY", 75, entry_price=100.0)
        prices["EMBASSY"] = 92.0  # 8% loss > 7% SL (default SL_PCT=0.93)
        t._monitor_positions()
        assert len(t.positions) == 0
        assert any("SL_HIT" in m for m in calls)

    def test_send_fn_called(self):
        """send_fn should be called on enter/exit."""
        messages = []
        cfg = {"REIT_ENABLED": True, "REIT_MAP": {"EMBASSY": {"enabled": True}}}
        def price_fn(sym):
            return 350.0
        t = REITTrader(cfg=cfg, send_fn=lambda msg, **kw: messages.append(msg), get_price_fn=price_fn)
        t._is_market_open = lambda: True
        t.enter_position("EMBASSY", "BUY", 75, entry_price=350.0)
        assert any("Entered" in m for m in messages)
        t.exit_position("EMBASSY", "TARGET_HIT", exit_price=370.0)
        assert any("Exited" in m for m in messages)

    def test_trust_type_returns_default_for_unknown(self):
        """_get_trust_type returns REIT for unknown symbols."""
        t = REITTrader()
        assert t._get_trust_type("UNKNOWN_SYM") == "REIT"

    def test_start_ignores_if_already_running(self):
        """Calling start() twice should not create a second thread."""
        t = REITTrader()
        t.start()
        thread_id = id(t._thread)
        t.start()
        assert id(t._thread) == thread_id
        t.stop()


class TestREITTradePosition:
    """REITTradePosition dataclass behavior."""

    def test_to_dict(self):
        """to_dict returns expected keys."""
        pos = REITTradePosition(symbol="EMBASSY", direction="BUY", qty=10, entry_price=350.0,
                                trust_type="REIT", distribution_yield=0.06, sector="Commercial")
        d = pos.to_dict()
        assert d["symbol"] == "EMBASSY"
        assert d["direction"] == "BUY"
        assert d["qty"] == 10
        assert d["trust_type"] == "REIT"
        assert d["distribution_yield"] == 0.06
        assert d["sector"] == "Commercial"
