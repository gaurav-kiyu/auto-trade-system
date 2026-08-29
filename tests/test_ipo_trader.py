"""Tests for IPOTrader - IPO/FPO/OFS/QIP tracking, subscription, and listing-day trading."""

from __future__ import annotations

from core.ipo_trader import IPOTradePosition, IPOTrader, run_ipo_trader


class TestIPOTrader:
    """IPOTrader - core trading logic."""

    def test_init_empty(self):
        """IPOTrader initializes with no symbols when disabled."""
        t = IPOTrader()
        assert t.is_running is False
        assert t.all_symbols == []

    def test_init_with_disabled_config(self):
        """IPOTrader with IPO_ENABLED=False should have no symbols."""
        t = IPOTrader(cfg={"IPO_ENABLED": False})
        assert t.all_symbols == []

    def test_start_stop(self):
        """IPOTrader starts and stops cleanly."""
        t = IPOTrader()
        t.start()
        assert t.is_running is True
        t.stop()
        assert t.is_running is False

    def test_can_trade_no_symbols(self):
        """can_trade returns False with no symbols."""
        t = IPOTrader()
        ok, msg = t.can_trade()
        assert ok is False
        assert "No IPO issues" in msg

    def test_can_trade_max_active(self):
        """can_trade returns False when max active issues reached."""
        cfg = {"IPO_ENABLED": True, "IPO_MAP": {"XYZIPO": {"enabled": True}}, "IPO_MAX_ACTIVE_ISSUES": 1}
        t = IPOTrader(cfg=cfg)
        t._is_market_open = lambda: True
        # Fill up to max
        t.enter_position("XYZIPO", "BUY", 75, entry_price=120.0)
        ok, msg = t.can_trade()
        assert ok is False
        assert "Max active" in msg

    def test_enter_subscription(self):
        """Enter a new IPO subscription."""
        cfg = {"IPO_ENABLED": True, "IPO_MAP": {"XYZIPO": {"enabled": True, "issue_type": "IPO",
                                                             "price_band_low": 115.0, "price_band_high": 120.0,
                                                             "lot_size": 50, "issuer_name": "XYZ Corp"}}}
        t = IPOTrader(cfg=cfg)
        assert t.enter_position("XYZIPO", "BUY", 80, entry_price=120.0) is True
        assert len(t.positions) == 1
        pos = t.positions["XYZIPO"]
        assert pos["direction"] == "BUY"
        assert pos["qty"] == 1
        assert pos["entry_price"] == 120.0
        assert pos["issue_type"] == "IPO"

    def test_double_entry_blocked(self):
        """Same issue entered twice should be rejected."""
        cfg = {"IPO_ENABLED": True, "IPO_MAP": {"XYZIPO": {"enabled": True}}}
        t = IPOTrader(cfg=cfg)
        assert t.enter_position("XYZIPO", "BUY", 80, entry_price=120.0) is True
        assert t.enter_position("XYZIPO", "BUY", 85, entry_price=121.0) is False

    def test_exit_position(self):
        """Exit a tracked issue."""
        cfg = {"IPO_ENABLED": True, "IPO_MAP": {"XYZIPO": {"enabled": True}}}
        t = IPOTrader(cfg=cfg)
        t.enter_position("XYZIPO", "BUY", 80, entry_price=120.0)
        assert t.exit_position("XYZIPO", "CANCELLED") is True
        assert len(t.positions) == 0

    def test_exit_nonexistent(self):
        """Exiting a non-existent issue returns False."""
        t = IPOTrader()
        assert t.exit_position("NONEXISTENT", "CANCELLED") is False

    def test_track_issue(self):
        """track_issue starts tracking a new issue."""
        t = IPOTrader()
        result = t.track_issue("NEWIPO", {
            "issue_type": "IPO",
            "issuer_name": "New Corp",
            "price_band_low": 100.0,
            "price_band_high": 120.0,
            "lot_size": 75,
        })
        assert result is True
        assert len(t.positions) == 1
        assert t.positions["NEWIPO"]["status"] == "UPCOMING"

    def test_track_duplicate(self):
        """track_issue with an already-tracked issue returns False."""
        t = IPOTrader()
        t.track_issue("NEWIPO", {"issue_type": "IPO"})
        assert t.track_issue("NEWIPO", {"issue_type": "IPO"}) is False

    def test_update_issue_status(self):
        """update_issue_status changes the lifecycle status."""
        t = IPOTrader()
        t.track_issue("NEWIPO", {"issue_type": "IPO"})
        assert t.update_issue_status("NEWIPO", "OPEN") is True
        assert t.positions["NEWIPO"]["status"] == "OPEN"

    def test_update_nonexistent(self):
        """update_issue_status on unknown issue returns False."""
        t = IPOTrader()
        assert t.update_issue_status("GHOST", "LISTED") is False

    def test_update_with_metadata(self):
        """update_issue_status updates additional metadata fields."""
        t = IPOTrader()
        t.track_issue("NEWIPO", {"issue_type": "IPO", "listing_price": 0})
        assert t.update_issue_status("NEWIPO", "LISTED", listing_price=150.0) is True
        assert t.positions["NEWIPO"]["listing_price"] == 150.0

    def test_status(self):
        """status() returns expected keys."""
        t = IPOTrader()
        s = t.status()
        assert "running" in s
        assert "active_issues" in s
        assert "max_active_issues" in s
        assert "issues_by_status" in s

    def test_status_with_tracked_issue(self):
        """status() reflects active tracked issues."""
        t = IPOTrader()
        t.track_issue("XYZIPO", {"issue_type": "IPO"})
        s = t.status()
        assert s["active_issues"] == 1

    def test_run_ipo_trader_factory(self):
        """run_ipo_trader creates and starts the trader."""
        t = run_ipo_trader()
        assert t.is_running is True
        t.stop()
        assert t.is_running is False

    def test_send_fn_called(self):
        """send_fn should be called on subscription and exit."""
        messages = []
        cfg = {"IPO_ENABLED": True, "IPO_MAP": {"XYZIPO": {"enabled": True, "issuer_name": "Test"}}}
        t = IPOTrader(cfg=cfg, send_fn=lambda msg, **kw: messages.append(msg))
        t.enter_position("XYZIPO", "BUY", 80, entry_price=120.0)
        assert any("Subscribed" in m for m in messages)
        t.exit_position("XYZIPO", "CANCELLED")
        assert any("Exited" in m for m in messages)

    def test_start_ignores_if_already_running(self):
        """Calling start() twice should not create a second thread."""
        t = IPOTrader()
        t.start()
        thread_id = id(t._thread)
        t.start()
        assert id(t._thread) == thread_id
        t.stop()

    def test_stop_ignores_if_not_running(self):
        """Calling stop() when not running should not raise."""
        t = IPOTrader()
        t.stop()

    def test_enter_fpo_subscription(self):
        """Enter an FPO subscription."""
        cfg = {"IPO_ENABLED": True, "IPO_MAP": {"XYZFPO": {"enabled": True, "issue_type": "FPO"}}}
        t = IPOTrader(cfg=cfg)
        assert t.enter_position("XYZFPO", "BUY", 80, entry_price=200.0) is True
        assert t.positions["XYZFPO"]["issue_type"] == "FPO"

    def test_max_active_issues_enforced_on_entry(self):
        """Max active issues limit is enforced on enter_position."""
        cfg = {"IPO_ENABLED": True, "IPO_MAP": {"IPO1": {"enabled": True}, "IPO2": {"enabled": True}}, "IPO_MAX_ACTIVE_ISSUES": 1}
        t = IPOTrader(cfg=cfg)
        assert t.enter_position("IPO1", "BUY", 80, entry_price=100.0) is True
        assert t.enter_position("IPO2", "BUY", 80, entry_price=100.0) is False


class TestIPOTradePosition:
    """IPOTradePosition dataclass behavior."""

    def test_to_dict(self):
        """to_dict returns expected keys."""
        pos = IPOTradePosition(symbol="XYZIPO", issue_type="IPO", issuer_name="XYZ Corp",
                               direction="BUY", qty=50, entry_price=120.0,
                               price_band_low=115.0, price_band_high=120.0,
                               lot_size=50, status="OPEN")
        d = pos.to_dict()
        assert d["symbol"] == "XYZIPO"
        assert d["issue_type"] == "IPO"
        assert d["direction"] == "BUY"
        assert d["qty"] == 50
        assert d["lot_size"] == 50
        assert d["status"] == "OPEN"

    def test_expected_listing_gain_with_listing_price(self):
        """expected_listing_gain_pct uses listing price when available."""
        pos = IPOTradePosition(symbol="XYZIPO", entry_price=100.0, listing_price=120.0)
        assert pos.expected_listing_gain_pct == 0.2

    def test_expected_listing_gain_with_gmp(self):
        """expected_listing_gain_pct uses grey market premium when no listing price."""
        pos = IPOTradePosition(symbol="XYZIPO", entry_price=100.0, grey_market_premium=0.25,
                               price_band_low=95.0, price_band_high=105.0)
        assert pos.expected_listing_gain_pct == 0.25

    def test_expected_listing_gain_zero_entry(self):
        """expected_listing_gain_pct returns 0 when entry price is 0."""
        pos = IPOTradePosition(symbol="XYZIPO", entry_price=0.0)
        assert pos.expected_listing_gain_pct == 0.0
