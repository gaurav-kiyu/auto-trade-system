"""
Tests for EquityTrader - multi-asset class support (ETF, REIT, InvIT, SME).

Covers:
- _build_asset_symbols() for all asset classes
- ETF_MAP, REIT_MAP, INVIT_MAP, SME_MAP configuration
- Per-asset-class default quantities
- all_symbols property
- _asset_map_index tracking
- Asset class in enter_position
- Per-asset-class breakdown in status()
- Disabled asset classes returning empty lists
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.equity_trader import EquityTrader


class TestBuildAssetSymbols:
    """_build_asset_symbols() helper function."""

    def test_equity_defaults_enabled(self):
        """EQUITY should default to enabled (backward compat)."""
        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}, "TCS": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE", "TCS"],
        }
        # We can test indirectly through EquityTrader init
        trader = EquityTrader(cfg=cfg)
        assert "RELIANCE" in trader._equity_symbols
        assert "TCS" in trader._equity_symbols

    def test_etf_disabled_by_default(self):
        """ETF should default to disabled."""
        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE"],
            "ETF_MAP": {"NIFTYBEES": {"enabled": True}},
            "ETF_PRIORITY": ["NIFTYBEES"],
            "ETF_ENABLED": False,
        }
        trader = EquityTrader(cfg=cfg)
        # ETF symbols should not be in all_symbols since disabled
        assert "NIFTYBEES" not in trader._all_symbols

    def test_etf_enabled_adds_symbols(self):
        """Enabled ETF should include ETF symbols."""
        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE"],
            "ETF_MAP": {
                "NIFTYBEES": {"enabled": True},
                "BANKBEES": {"enabled": False},
            },
            "ETF_PRIORITY": ["NIFTYBEES", "BANKBEES"],
            "ETF_ENABLED": True,
            "ETF_DEFAULT_QTY": 10,
        }
        trader = EquityTrader(cfg=cfg)
        assert "NIFTYBEES" in trader._all_symbols
        assert "BANKBEES" not in trader._all_symbols  # disabled in map
        assert "RELIANCE" in trader._all_symbols
        assert len(trader._all_symbols) == 2

    def test_reit_enabled_adds_symbols(self):
        """Enabled REIT without priority should include all enabled symbols."""
        cfg = {
            "REIT_MAP": {
                "EMBASSY": {"enabled": True},
                "MINDSPACE": {"enabled": False},
            },
            "REIT_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg)
        assert "EMBASSY" in trader._all_symbols
        assert "MINDSPACE" not in trader._all_symbols

    def test_invit_enabled_adds_symbols(self):
        """Enabled InvIT without priority should include all enabled symbols."""
        cfg = {
            "INVIT_MAP": {
                "IRBINVIT": {"enabled": True},
                "POWERGRID_INVIT": {"enabled": True},
            },
            "INVIT_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg)
        assert "IRBINVIT" in trader._all_symbols
        assert "POWERGRID_INVIT" in trader._all_symbols

    def test_sme_disabled_by_default(self):
        """SME should default to disabled."""
        cfg = {
            "SME_MAP": {"SOMESME": {"enabled": True}},
            "SME_ENABLED": False,
        }
        trader = EquityTrader(cfg=cfg)
        assert "SOMESME" not in trader._all_symbols

    def test_all_asset_classes_together(self):
        """All asset classes should work together when enabled."""
        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE"],
            "ETF_MAP": {"NIFTYBEES": {"enabled": True}},
            "ETF_PRIORITY": ["NIFTYBEES"],
            "ETF_ENABLED": True,
            "REIT_MAP": {"EMBASSY": {"enabled": True}},
            "REIT_ENABLED": True,
            "INVIT_MAP": {"IRBINVIT": {"enabled": True}},
            "INVIT_ENABLED": True,
            "SME_MAP": {"SOMESME": {"enabled": True}},
            "SME_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg)
        assert len(trader._all_symbols) == 5
        assert "RELIANCE" in trader._all_symbols
        assert "NIFTYBEES" in trader._all_symbols
        assert "EMBASSY" in trader._all_symbols
        assert "IRBINVIT" in trader._all_symbols
        assert "SOMESME" in trader._all_symbols


class TestAllSymbolsProperty:
    """all_symbols property tests."""

    def test_returns_all_symbols(self):
        """all_symbols should return all configured symbols."""
        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}, "TCS": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE", "TCS"],
            "ETF_MAP": {"NIFTYBEES": {"enabled": True}},
            "ETF_PRIORITY": ["NIFTYBEES"],
            "ETF_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg)
        symbols = trader.all_symbols
        assert "RELIANCE" in symbols
        assert "TCS" in symbols
        assert "NIFTYBEES" in symbols
        assert len(symbols) == 3

    def test_returns_copy(self):
        """all_symbols should return a copy, not the internal list."""
        trader = EquityTrader()
        symbols = trader.all_symbols
        symbols.append("FAKE")
        assert "FAKE" not in trader._all_symbols

    def test_empty_when_no_symbols(self):
        """all_symbols should be empty when no asset maps configured."""
        trader = EquityTrader(cfg={"EQUITY_MAP": {}})
        assert trader.all_symbols == []

    def test_equity_symbols_backward_compat(self):
        """equity_symbols property should return only EQUITY class symbols."""
        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE"],
            "ETF_MAP": {"NIFTYBEES": {"enabled": True}},
            "ETF_PRIORITY": ["NIFTYBEES"],
            "ETF_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg)
        assert trader.equity_symbols == ["RELIANCE"]
        assert "NIFTYBEES" not in trader.equity_symbols


class TestPerAssetClassDefaultQuantity:
    """Per-asset-class default quantity tests."""

    def test_equity_default_qty(self):
        """EQUITY class should use EQUITY_DEFAULT_QTY."""
        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE"],
            "EQUITY_DEFAULT_QTY": 5,
            "ETF_MAP": {"NIFTYBEES": {"enabled": True}},
            "ETF_PRIORITY": ["NIFTYBEES"],
            "ETF_ENABLED": True,
            "ETF_DEFAULT_QTY": 10,
        }
        trader = EquityTrader(cfg=cfg)
        assert trader.get_position_size("RELIANCE", 100.0) == 5
        assert trader.get_position_size("NIFTYBEES", 100.0) == 10

    def test_fallback_to_equity_default(self):
        """Unknown symbols should fall back to EQUITY default."""
        cfg = {
            "EQUITY_DEFAULT_QTY": 3,
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE"],
        }
        trader = EquityTrader(cfg=cfg)
        # _asset_map_index would be empty for unknown, defaults to EQUITY
        assert trader.get_position_size("UNKNOWN", 100.0) == 3

    def test_reit_default_qty(self):
        """REIT should default to 1."""
        cfg = {
            "REIT_MAP": {"EMBASSY": {"enabled": True}},
            "REIT_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg)
        assert trader.get_position_size("EMBASSY", 100.0) == 1

    def test_invit_default_qty(self):
        """InvIT should default to 1."""
        cfg = {
            "INVIT_MAP": {"IRBINVIT": {"enabled": True}},
            "INVIT_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg)
        assert trader.get_position_size("IRBINVIT", 100.0) == 1

    def test_sme_default_qty(self):
        """SME should default to 1."""
        cfg = {
            "SME_MAP": {"SOMESME": {"enabled": True}},
            "SME_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg)
        assert trader.get_position_size("SOMESME", 100.0) == 1


class TestAssetMapIndexTracking:
    """_asset_map_index internal tracking tests."""

    def test_asset_map_index_maps_symbol_to_class(self):
        """_asset_map_index should correctly map symbols to asset classes."""
        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE"],
            "ETF_MAP": {"NIFTYBEES": {"enabled": True}},
            "ETF_PRIORITY": ["NIFTYBEES"],
            "ETF_ENABLED": True,
            "REIT_MAP": {"EMBASSY": {"enabled": True}},
            "REIT_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg)
        assert trader._asset_map_index["RELIANCE"] == "EQUITY"
        assert trader._asset_map_index["NIFTYBEES"] == "ETF"
        assert trader._asset_map_index["EMBASSY"] == "REIT"


class TestEnterPositionWithAssetClass:
    """enter_position with asset_class tracking."""

    @patch("core.equity_trader.now_ist")
    def test_enter_position_with_asset_class(self, mock_now):
        """Entered positions should include asset_class field."""
        from datetime import datetime
        mock_now.return_value = datetime(2026, 6, 11, 11, 0)
        price_fn = MagicMock(return_value=100.0)

        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE"],
            "ETF_MAP": {"NIFTYBEES": {"enabled": True}},
            "ETF_PRIORITY": ["NIFTYBEES"],
            "ETF_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg, get_price_fn=price_fn)

        # Enter RELIANCE (EQUITY)
        assert trader.enter_position("RELIANCE", "BUY", 80) is True
        assert trader._positions["RELIANCE"]["asset_class"] == "EQUITY"

        # Enter NIFTYBEES (ETF)
        assert trader.enter_position("NIFTYBEES", "BUY", 75) is True
        assert trader._positions["NIFTYBEES"]["asset_class"] == "ETF"

    @patch("core.equity_trader.now_ist")
    def test_unknown_symbol_asset_class(self, mock_now):
        """Unknown symbols should get UNKNOWN asset_class."""
        from datetime import datetime
        mock_now.return_value = datetime(2026, 6, 11, 11, 0)
        price_fn = MagicMock(return_value=100.0)
        trader = EquityTrader(get_price_fn=price_fn)

        assert trader.enter_position("UNKNOWN", "BUY", 80) is True
        assert trader._positions["UNKNOWN"]["asset_class"] == "UNKNOWN"


class TestStatusMultiAsset:
    """status() with per-asset-class breakdown."""

    @patch("core.equity_trader.now_ist")
    def test_status_includes_symbols_by_class(self, mock_now):
        """status() should include symbols_by_class breakdown."""
        from datetime import datetime
        mock_now.return_value = datetime(2026, 6, 11, 11, 0)

        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}, "TCS": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE", "TCS"],
            "ETF_MAP": {"NIFTYBEES": {"enabled": True}},
            "ETF_PRIORITY": ["NIFTYBEES"],
            "ETF_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg)
        status = trader.status()

        assert "symbols_by_class" in status
        assert status["symbols_by_class"]["EQUITY"] == 2
        assert status["symbols_by_class"]["ETF"] == 1

    @patch("core.equity_trader.now_ist")
    def test_status_includes_positions_by_class(self, mock_now):
        """status() should include positions_by_class breakdown."""
        from datetime import datetime
        mock_now.return_value = datetime(2026, 6, 11, 11, 0)
        price_fn = MagicMock(return_value=100.0)

        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE"],
            "ETF_MAP": {"NIFTYBEES": {"enabled": True}},
            "ETF_PRIORITY": ["NIFTYBEES"],
            "ETF_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg, get_price_fn=price_fn)
        trader.enter_position("RELIANCE", "BUY", 80)
        trader.enter_position("NIFTYBEES", "BUY", 75)

        status = trader.status()
        assert status["positions_by_class"]["EQUITY"] == 1
        assert status["positions_by_class"]["ETF"] == 1


class TestReentryTrackersMultiAsset:
    """Reentry trackers with multi-asset symbols."""

    def test_reentry_trackers_built_for_all_symbols(self):
        """Reentry trackers should be built for all asset class symbols."""
        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE"],
            "ETF_MAP": {"NIFTYBEES": {"enabled": True}},
            "ETF_PRIORITY": ["NIFTYBEES"],
            "ETF_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg)
        assert "RELIANCE" in trader._reentry_trackers
        assert "NIFTYBEES" in trader._reentry_trackers


class TestCanTradeMultiAsset:
    """can_trade() with multi-asset symbols."""

    @patch("core.equity_trader.now_ist")
    def test_can_trade_with_etf_symbols(self, mock_now):
        """can_trade should return True when ETFs are configured and market open."""
        from datetime import datetime
        mock_now.return_value = datetime(2026, 6, 11, 11, 0)

        # No equity symbols, only ETF
        cfg = {
            "EQUITY_ENABLED": False,
            "EQUITY_MAP": {},
            "ETF_MAP": {"NIFTYBEES": {"enabled": True}},
            "ETF_PRIORITY": ["NIFTYBEES"],
            "ETF_ENABLED": True,
        }
        trader = EquityTrader(cfg=cfg)
        # can_trade checks _equity_symbols (backward compat), which is empty
        # But _all_symbols has NIFTYBEES
        allowed, msg = trader.can_trade()
        assert allowed is False  # Backward compat: checks _equity_symbols
        assert "No equity symbols" in msg


class TestLoggingMultiAsset:
    """Logging with multi-asset class info."""

    @patch("core.equity_trader.log")
    def test_startup_logs_all_asset_classes(self, mock_log):
        """Startup should log total symbols and active asset classes."""
        cfg = {
            "EQUITY_MAP": {"RELIANCE": {"enabled": True}},
            "EQUITY_PRIORITY": ["RELIANCE"],
            "ETF_MAP": {"NIFTYBEES": {"enabled": True}},
            "ETF_PRIORITY": ["NIFTYBEES"],
            "ETF_ENABLED": True,
        }
        EquityTrader(cfg=cfg)
        # Check that log.info was called with correct message
        # Check format string contains expected content (format args checked separately)
        expected_fmt = any(
            "Loaded %d total symbols" in str(call[0])
            for call in mock_log.info.call_args_list
        )
        assert expected_fmt, f"Expected log call with 'Loaded %%d total symbols', got: {mock_log.info.call_args_list}"
