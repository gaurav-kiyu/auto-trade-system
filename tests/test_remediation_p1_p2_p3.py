"""
Tests for OPB v2.59.4 Remediation: DEF-P1-001, DEF-P2-001, DEF-P3-001,
Multi-Asset Market Sessions, 16-State Evaluation Telemetry, and Universal Coverage.
"""

from __future__ import annotations

import json
from datetime import datetime, date, time as dtime
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytz

import pytest

from core.signal_utils import calculate_directional_levels
from core.notifications.rich_signal_formatter import RichSignalFormatter
from core.exchange_calendar_engine import (
    CATEGORY_SESSION_SCHEDULES,
    is_category_session_open,
    get_category_session_state,
    get_calendar_engine,
)
from core.fno_universe import classify_instrument_market, is_fno_symbol
from core.all_nse_scanner import AllNSEScanner, ScannedStockSignal

_IST = pytz.timezone("Asia/Kolkata")


# ==============================================================================
# DEF-P1-001: Directional Levels Mathematics Tests
# ==============================================================================

class TestDefP1001DirectionalLevels:
    """Verify directional SL and target math for CALL/BUY vs PUT/SELL/SHORT."""

    def test_call_levels_calculation(self):
        """CALL/BUY: sl < entry < t1 < t2."""
        entry = 100.0
        sl, t1, t2 = calculate_directional_levels(entry_price=entry, direction="CALL")
        assert sl == 97.0
        assert t1 == 104.0
        assert t2 == 108.0
        assert sl < entry < t1 < t2

    def test_buy_long_aliases(self):
        """Aliases BUY and LONG calculate identical levels to CALL."""
        for direction in ("BUY", "LONG", "call"):
            sl, t1, t2 = calculate_directional_levels(entry_price=2500.0, direction=direction)
            assert sl == 2425.0
            assert t1 == 2600.0
            assert t2 == 2700.0
            assert sl < 2500.0 < t1 < t2

    def test_put_levels_calculation(self):
        """PUT/SELL/SHORT: t2 < t1 < entry < sl (NEVER inverted)."""
        entry = 100.0
        sl, t1, t2 = calculate_directional_levels(entry_price=entry, direction="PUT")
        assert sl == 103.0
        assert t1 == 96.0
        assert t2 == 92.0
        assert t2 < t1 < entry < sl

    def test_sell_short_aliases(self):
        """Aliases SELL and SHORT calculate identical levels to PUT."""
        for direction in ("SELL", "SHORT", "put"):
            sl, t1, t2 = calculate_directional_levels(entry_price=2500.0, direction=direction)
            assert sl == 2575.0
            assert t1 == 2400.0
            assert t2 == 2300.0
            assert t2 < t1 < 2500.0 < sl

    def test_put_sl_never_below_entry(self):
        """DEF-P1-001 Core Defect: Stop loss for PUT must strictly be above entry."""
        prices = [10.0, 50.25, 100.0, 750.50, 2400.0, 18500.0, 75000.0]
        for p in prices:
            sl, t1, t2 = calculate_directional_levels(entry_price=p, direction="PUT")
            assert sl > p, f"PUT Stop Loss {sl} must be > entry price {p}"
            assert t1 < p, f"PUT Target 1 {t1} must be < entry price {p}"
            assert t2 < t1, f"PUT Target 2 {t2} must be < Target 1 {t1}"

    def test_rich_formatter_signs(self):
        """Verify +/- signs in formatted Telegram and Email alerts."""
        # CALL / BUY
        call_tg = RichSignalFormatter.build_rich_telegram_html(
            symbol="TCS", category="LARGE_CAP_EQUITY", direction="CALL",
            price=3500.0, score=85, tier="STRONG",
            stop_loss=3395.0, target_1=3640.0, target_2=3780.0,
        )
        assert "-3.0%" in call_tg
        assert "+4.0%" in call_tg
        assert "+8.0%" in call_tg

        # PUT / SELL
        put_tg = RichSignalFormatter.build_rich_telegram_html(
            symbol="INFY", category="LARGE_CAP_EQUITY", direction="PUT",
            price=1500.0, score=85, tier="STRONG",
            stop_loss=1545.0, target_1=1440.0, target_2=1380.0,
        )
        assert "+3.0%" in put_tg
        assert "-4.0%" in put_tg
        assert "-8.0%" in put_tg


# ==============================================================================
# DEF-P2-001: Notification Presentation Unification Tests
# ==============================================================================

class TestDefP2001NotificationUnification:
    """Verify unified rich notification contract across all dispatch paths."""

    def test_build_canonical_notification_contract(self):
        """RichSignalFormatter.build_canonical_notification returns all standard keys."""
        mock_signal = {
            "symbol": "RELIANCE",
            "company_name": "Reliance Industries Ltd",
            "series": "EQ",
            "direction": "CALL",
            "price": 2800.0,
            "score": 88,
            "raw_score": 120.0,
            "tier": "STRONG",
            "regime": "TRENDING_BULL",
            "rsi": 62.5,
            "adx": 28.0,
            "vwap": 2790.0,
            "confidence": 0.85,
            "ml_probability": 0.72,
            "stop_loss": 2716.0,
            "target_1": 2912.0,
            "target_2": 3024.0,
        }

        canonical = RichSignalFormatter.build_canonical_notification(
            signal=mock_signal,
            base_url="https://opb-app.internal",
        )

        assert "subject" in canonical
        assert "telegram_html" in canonical
        assert "email_html" in canonical
        assert "plain_text" in canonical
        assert "metadata" in canonical

        # Verify HTML structure
        assert "<b>RELIANCE</b>" in canonical["telegram_html"]
        assert "href=" in canonical["email_html"]
        assert "2,800.00" in canonical["plain_text"]
        assert canonical["metadata"]["symbol"] == "RELIANCE"
        assert canonical["metadata"]["score"] == 88

    def test_telegram_adapter_parse_mode_and_fallback(self):
        """Telegram adapter supports parse_mode='HTML' and falls back cleanly."""
        from infrastructure.adapters.notifications.telegram_adapter import TelegramNotificationAdapter
        adapter = TelegramNotificationAdapter(bot_token="TEST_BOT_TOKEN", default_chat_id="12345678")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 999}}

        with patch.object(adapter._client._session, "post", return_value=mock_resp) as mock_post:
            res = adapter._client._send_message(chat_id="12345678", text="<b>Bold Test</b>", parse_mode="HTML")
            assert res is True
            # Verify payload contains parse_mode
            call_kwargs = mock_post.call_args[1]
            assert call_kwargs["json"].get("parse_mode") == "HTML"


# ==============================================================================
# DEF-P3-001: Profile Password Eye Icon Tests
# ==============================================================================

class TestDefP3001ProfilePasswordEye:
    """Verify password visibility toggle in templates/enterprise/profile.html."""

    def test_profile_template_contains_eye_svg_closed(self):
        """profile.html must contain .eye-svg-closed icons and JS toggle logic."""
        tmpl_path = Path("templates/enterprise/profile.html")
        assert tmpl_path.exists(), "templates/enterprise/profile.html must exist"
        content = tmpl_path.read_text(encoding="utf-8")

        # Must have both open and closed SVG elements
        assert 'class="eye-svg-open"' in content
        assert 'class="eye-svg-closed"' in content

        # Verify JS toggle references both SVGs and updates title/aria-label
        assert "openIcon.style.display" in content
        assert "closedIcon.style.display" in content
        assert "Show password" in content
        assert "Hide password" in content


# ==============================================================================
# Component 4: Multi-Asset Session Schedules & Market Clocks
# ==============================================================================

class TestMarketSessionAwarenessAndClocks:
    """Verify session schedules and market clocks for Equity, Derivatives, Currencies, Commodities."""

    def test_session_schedules_defined(self):
        """All 4 categories must have exact canonical session hours."""
        assert "EQUITY" in CATEGORY_SESSION_SCHEDULES
        assert "DERIVATIVES" in CATEGORY_SESSION_SCHEDULES
        assert "CURRENCIES" in CATEGORY_SESSION_SCHEDULES
        assert "COMMODITIES" in CATEGORY_SESSION_SCHEDULES

        assert CATEGORY_SESSION_SCHEDULES["EQUITY"]["open"] == dtime(9, 15)
        assert CATEGORY_SESSION_SCHEDULES["EQUITY"]["close"] == dtime(15, 30)

        assert CATEGORY_SESSION_SCHEDULES["DERIVATIVES"]["open"] == dtime(9, 15)
        assert CATEGORY_SESSION_SCHEDULES["DERIVATIVES"]["close"] == dtime(15, 40)

        assert CATEGORY_SESSION_SCHEDULES["CURRENCIES"]["open"] == dtime(9, 0)
        assert CATEGORY_SESSION_SCHEDULES["CURRENCIES"]["close"] == dtime(17, 0)

        assert CATEGORY_SESSION_SCHEDULES["COMMODITIES"]["open"] == dtime(9, 0)
        assert CATEGORY_SESSION_SCHEDULES["COMMODITIES"]["close"] == dtime(23, 30)

    def test_session_state_progression_across_trading_day(self):
        """Test is_category_session_open progression on a Monday."""
        monday = date(2026, 9, 21)  # A Monday

        # 08:30 IST - Pre-market: None open
        dt_0830 = datetime.combine(monday, dtime(8, 30), tzinfo=_IST)
        for cat in ("EQUITY", "DERIVATIVES", "CURRENCIES", "COMMODITIES"):
            assert not is_category_session_open(cat, dt_0830)

        # 09:05 IST - Currencies & Commodities open; Equity & Derivatives closed
        dt_0905 = datetime.combine(monday, dtime(9, 5), tzinfo=_IST)
        assert not is_category_session_open("EQUITY", dt_0905)
        assert not is_category_session_open("DERIVATIVES", dt_0905)
        assert is_category_session_open("CURRENCIES", dt_0905)
        assert is_category_session_open("COMMODITIES", dt_0905)

        # 11:00 IST - All 4 categories open
        dt_1100 = datetime.combine(monday, dtime(11, 0), tzinfo=_IST)
        assert is_category_session_open("EQUITY", dt_1100)
        assert is_category_session_open("DERIVATIVES", dt_1100)
        assert is_category_session_open("CURRENCIES", dt_1100)
        assert is_category_session_open("COMMODITIES", dt_1100)

        # 15:35 IST - Equity closed; Derivatives, Currencies, Commodities open
        dt_1535 = datetime.combine(monday, dtime(15, 35), tzinfo=_IST)
        assert not is_category_session_open("EQUITY", dt_1535)
        assert is_category_session_open("DERIVATIVES", dt_1535)
        assert is_category_session_open("CURRENCIES", dt_1535)
        assert is_category_session_open("COMMODITIES", dt_1535)

        # 16:15 IST - Equity & Derivatives closed; Currencies & Commodities open
        dt_1615 = datetime.combine(monday, dtime(16, 15), tzinfo=_IST)
        assert not is_category_session_open("EQUITY", dt_1615)
        assert not is_category_session_open("DERIVATIVES", dt_1615)
        assert is_category_session_open("CURRENCIES", dt_1615)
        assert is_category_session_open("COMMODITIES", dt_1615)

        # 18:00 IST - Evening: Commodities open (MCX till 23:30); others closed
        dt_1800 = datetime.combine(monday, dtime(18, 0), tzinfo=_IST)
        assert not is_category_session_open("EQUITY", dt_1800)
        assert not is_category_session_open("DERIVATIVES", dt_1800)
        assert not is_category_session_open("CURRENCIES", dt_1800)
        assert is_category_session_open("COMMODITIES", dt_1800)

        # 23:45 IST - Night: All closed
        dt_2345 = datetime.combine(monday, dtime(23, 45), tzinfo=_IST)
        for cat in ("EQUITY", "DERIVATIVES", "CURRENCIES", "COMMODITIES"):
            assert not is_category_session_open(cat, dt_2345)

    def test_weekend_strictly_closed(self):
        """Saturdays and Sundays are strictly closed unless Muhurat trading."""
        saturday = date(2026, 9, 26)
        sunday = date(2026, 9, 27)
        for dt_day in (saturday, sunday):
            for t in (dtime(10, 0), dtime(14, 0), dtime(20, 0)):
                dt = datetime.combine(dt_day, t, tzinfo=_IST)
                for cat in ("EQUITY", "DERIVATIVES", "CURRENCIES", "COMMODITIES"):
                    assert not is_category_session_open(cat, dt)


# ==============================================================================
# Component 5: Multi-Asset Scanner Universe & 16-State Telemetry
# ==============================================================================

class TestMultiAssetUniverseAndTelemetry:
    """Verify priority universe instruments, category classification, and evaluation telemetry."""

    def test_priority_instruments_include_mcx_and_currencies(self):
        """load_nse_universe includes Commodities and Currencies."""
        with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
            scanner = AllNSEScanner(cfg={"MIN_SCORE_THRESHOLD": 70})
        universe = scanner.load_nse_universe()
        symbols = {item["symbol"] for item in universe}

        # Indices
        for idx in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"):
            assert idx in symbols

        # Commodities
        for comm in ("GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "COPPER"):
            assert comm in symbols

        # Currencies
        for curr in ("USDINR", "EURINR", "GBPINR", "JPYINR"):
            assert curr in symbols

    def test_instrument_classification(self):
        """classify_instrument_market accurately tags multi-asset categories."""
        assert classify_instrument_market("GOLD", "COMMODITY") == "COMMODITIES"
        assert classify_instrument_market("SILVER", "COMMODITY") == "COMMODITIES"
        assert classify_instrument_market("CRUDEOIL", "COMMODITY") == "COMMODITIES"
        assert classify_instrument_market("USDINR", "CURRENCY") == "CURRENCIES"
        assert classify_instrument_market("EURINR", "CURRENCY") == "CURRENCIES"
        assert classify_instrument_market("NIFTY", "INDEX") == "INDEX_OPTIONS"
        assert classify_instrument_market("TCS", instrument_type="CASH") == "LARGE_CAP_EQUITY"
        assert classify_instrument_market("TCS") == "STOCK_OPTIONS"

    def test_18_state_evaluation_telemetry_recording(self):
        """Scanner records 18-state evaluation/delivery lifecycle and generates category summaries."""
        from core.all_nse_scanner import CANONICAL_LIFECYCLE_STATES, STATE_ALIASES
        assert len(CANONICAL_LIFECYCLE_STATES) == 18

        with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
            scanner = AllNSEScanner(cfg={"MIN_SCORE_THRESHOLD": 70})

        # Test all 18 states can be recorded and tracked without disappearing
        for idx, st in enumerate(CANONICAL_LIFECYCLE_STATES):
            scanner._record_evaluation_state(f"SYM_{idx}", st, f"Reason for {st}", category="TEST_CAT")

        # Test alias mapping (MARKET_CLOSED -> SESSION_WAIT)
        scanner._record_evaluation_state("SILVER", "MARKET_CLOSED", "Closed", category="COMMODITIES")

        states = scanner.get_evaluation_states()
        assert len(states) == 19

        summary = scanner.get_category_evaluation_summary()
        assert "TEST_CAT" in summary
        for st in CANONICAL_LIFECYCLE_STATES:
            assert summary["TEST_CAT"].get(st) == 1, f"State {st} must be recorded in summary"

        # Alias must be normalized to SESSION_WAIT
        assert summary["COMMODITIES"].get("SESSION_WAIT") == 1


# ==============================================================================
# Production Safety Invariants Verification
# ==============================================================================

class TestProductionSafetyInvariants:
    """Ensure absolute safety invariants are intact in config.json."""

    def test_safety_invariants_frozen(self):
        config_path = Path("json/config.json")
        assert config_path.exists()
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)

        assert cfg.get("BASE_CAPITAL") == 3000
        assert cfg.get("SL_PCT") == 0.88
        assert cfg.get("SIGNAL_ONLY") is True
        assert str(cfg.get("EXECUTION_MODE")).upper() in ("PAPER", "SIGNAL_ONLY")
        assert cfg.get("LIVE_TRADING_LOCKOUT") is True
        assert cfg.get("live_trading_lockout_enabled") is True
        assert cfg.get("full_auto_allowed") is False

        # Canonical score threshold must be strictly == 70 (MODERATE tier floor)
        assert cfg.get("MIN_SCORE_THRESHOLD") == 70
        assert cfg.get("MODERATE_THRESHOLD") == 70
        assert cfg.get("QUALITY_MIN_SCORE") == 70
        assert cfg.get("TIER_MODERATE_MIN") == 70

        cat_th = cfg.get("CATEGORY_SCORE_THRESHOLDS", {})
        assert cat_th.get("EQUITY_SWING_DELIVERY") == 70
        assert cat_th.get("LARGE_CAP_EQUITY") == 70
        assert cat_th.get("MID_SMALL_CAP") == 70
        assert cat_th.get("ETFS_REITS") == 70


# ==============================================================================
# Threshold Governance & Notification Boundary Verification (Blocker 1)
# ==============================================================================

class TestCanonicalThresholdGovernanceAndNotificationBoundary:
    """Verify strictly canonical score tiers and notification qualification boundaries.

    Canonical tiers:
      0-59:   IGNORE (no trade, no notification)
      60-69:  WEAK   (sub-threshold, no notification)
      70-79:  MODERATE (qualifying floor >= 70)
      80-100: STRONG   (high conviction >= 80)
    """

    def test_score_67_produces_no_notification(self):
        """Score 67 is WEAK and MUST NOT qualify for publication or notification."""
        from core.signal_utils import classify_strength
        from core.tier_engine import classify_tier
        from core.position_service import PositionService

        assert classify_strength(67) == "WEAK"
        assert classify_tier(67) == "WEAK"

        ps = PositionService.__new__(PositionService)
        ps._cfg = {"MIN_SCORE_THRESHOLD": 70, "MODERATE_THRESHOLD": 70, "TIER_MODERATE_MIN": 70}
        sig = {"symbol": "INFY", "score": 67, "raw_score": 67, "signal": "BUY", "tier": "WEAK"}
        assert ps._is_qualified_signal(sig) is False

    def test_score_68_produces_no_notification(self):
        """Score 68 is WEAK and MUST NOT qualify for publication or notification."""
        from core.signal_utils import classify_strength
        from core.tier_engine import classify_tier
        from core.position_service import PositionService

        assert classify_strength(68) == "WEAK"
        assert classify_tier(68) == "WEAK"

        ps = PositionService.__new__(PositionService)
        ps._cfg = {"MIN_SCORE_THRESHOLD": 70, "MODERATE_THRESHOLD": 70, "TIER_MODERATE_MIN": 70}
        sig = {"symbol": "RELIANCE", "score": 68, "raw_score": 68, "signal": "BUY", "tier": "WEAK"}
        assert ps._is_qualified_signal(sig) is False

        # Even with unspecified tier, score 68 must not qualify
        sig_no_tier = {"symbol": "RELIANCE", "score": 68, "signal": "BUY"}
        assert ps._is_qualified_signal(sig_no_tier) is False

    def test_score_69_produces_no_notification(self):
        """Score 69 is WEAK and MUST NOT qualify for publication or notification."""
        from core.signal_utils import classify_strength
        from core.tier_engine import classify_tier
        from core.position_service import PositionService

        assert classify_strength(69) == "WEAK"
        assert classify_tier(69) == "WEAK"

        ps = PositionService.__new__(PositionService)
        ps._cfg = {"MIN_SCORE_THRESHOLD": 70, "MODERATE_THRESHOLD": 70, "TIER_MODERATE_MIN": 70}
        sig = {"symbol": "TCS", "score": 69, "raw_score": 69, "signal": "BUY", "tier": "WEAK"}
        assert ps._is_qualified_signal(sig) is False

    def test_score_70_qualifies_for_notification(self):
        """Score 70 is MODERATE and DOES qualify for publication and notification."""
        from core.signal_utils import classify_strength
        from core.tier_engine import classify_tier
        from core.position_service import PositionService

        assert classify_strength(70) == "MODERATE"
        assert classify_tier(70) == "MODERATE"

        ps = PositionService.__new__(PositionService)
        ps._cfg = {"MIN_SCORE_THRESHOLD": 70, "MODERATE_THRESHOLD": 70, "TIER_MODERATE_MIN": 70}
        sig = {"symbol": "HDFCBANK", "score": 70, "raw_score": 70, "signal": "BUY", "tier": "MODERATE"}
        assert ps._is_qualified_signal(sig) is True

    def test_score_79_qualifies_for_notification(self):
        """Score 79 is MODERATE and DOES qualify for publication and notification."""
        from core.signal_utils import classify_strength
        from core.tier_engine import classify_tier
        from core.position_service import PositionService

        assert classify_strength(79) == "MODERATE"
        assert classify_tier(79) == "MODERATE"

        ps = PositionService.__new__(PositionService)
        ps._cfg = {"MIN_SCORE_THRESHOLD": 70, "MODERATE_THRESHOLD": 70, "TIER_MODERATE_MIN": 70}
        sig = {"symbol": "ICICIBANK", "score": 79, "raw_score": 79, "signal": "BUY", "tier": "MODERATE"}
        assert ps._is_qualified_signal(sig) is True

    def test_score_80_qualifies_for_notification(self):
        """Score 80 is STRONG and DOES qualify for publication and notification."""
        from core.signal_utils import classify_strength
        from core.tier_engine import classify_tier
        from core.position_service import PositionService

        assert classify_strength(80) == "STRONG"
        assert classify_tier(80) == "STRONG"

        ps = PositionService.__new__(PositionService)
        ps._cfg = {"MIN_SCORE_THRESHOLD": 70, "MODERATE_THRESHOLD": 70, "TIER_MODERATE_MIN": 70}
        sig = {"symbol": "NIFTY", "score": 80, "raw_score": 80, "signal": "BUY", "tier": "STRONG"}
        assert ps._is_qualified_signal(sig) is True

    def test_all_nse_scanner_minimum_floor_enforcement(self):
        """AllNSEScanner clamps any sub-70 category threshold up to canonical floor 70."""
        with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
            scanner = AllNSEScanner(cfg={
                "MIN_SCORE_THRESHOLD": 68,
                "CATEGORY_SCORE_THRESHOLDS": {"LARGE_CAP_EQUITY": 65, "ETFS_REITS": 68},
            })

        # Clamped to at least 70
        assert scanner.get_min_score_for_category("LARGE_CAP_EQUITY") >= 70
        assert scanner.get_min_score_for_category("ETFS_REITS") >= 70
        assert scanner.get_min_score_for_category("MID_SMALL_CAP") >= 70

    def test_single_evaluation_owner_governance_prevents_duplicate_evaluation(self):
        """AllNSEScanner marks INDEX_OPTIONS as NOT_EVALUATED when opb_bot is runtime owner."""
        with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
            scanner = AllNSEScanner(cfg={
                "INDEX_OPTIONS_EVALUATION_OWNER": "opb_bot",
                "EXECUTION_MODE": "SIGNAL_ONLY",
                "ALLOW_AFTER_HOURS_SCANNING": True,
            })

        stock_info = {"symbol": "NIFTY", "name": "Nifty 50", "series": "INDEX"}
        result = scanner.scan_single_stock(stock_info)

        # Must return None and record state NOT_EVALUATED
        assert result is None
        states = scanner.get_evaluation_states("INDEX_OPTIONS")
        assert len(states) == 1
        assert states[0]["state"] == "NOT_EVALUATED"
        assert "opb_bot" in states[0]["reason"]


# ==============================================================================
# Category Threshold Governance Verification (Universal Floor >= 70 vs Category Thresholds)
# ==============================================================================

class TestCategoryThresholdGovernance:
    """Explicit tests for Universal floor >= 70 vs Category-specific quality thresholds."""

    @pytest.fixture
    def scanner(self):
        cfg = {
            "CATEGORY_SCORE_THRESHOLDS": {
                "LARGE_CAP_EQUITY": 70,
                "MID_SMALL_CAP": 70,
                "ETFS_REITS": 70,
                "STOCK_OPTIONS": 80,
                "INDEX_OPTIONS": 80,
                "COMMODITIES": 80,
                "CURRENCIES": 80,
                "FUTURES": 80,
            },
            "MIN_SCORE_THRESHOLD": 70,
        }
        with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
            return AllNSEScanner(cfg=cfg)

    def test_score_69_never_qualifies_anywhere(self, scanner):
        """Score 69 is below the canonical universal floor (70) and never qualifies anywhere."""
        from core.signal_utils import classify_strength
        from core.tier_engine import classify_tier

        # Universal tier is strictly WEAK
        assert classify_strength(69) == "WEAK"
        assert classify_tier(69) == "WEAK"

        # Check against category with threshold 70
        assert scanner.get_min_score_for_category("LARGE_CAP_EQUITY") == 70
        assert 69 < scanner.get_min_score_for_category("LARGE_CAP_EQUITY")

        # Check against category with threshold 80
        assert scanner.get_min_score_for_category("STOCK_OPTIONS") == 80
        assert 69 < scanner.get_min_score_for_category("STOCK_OPTIONS")

    def test_score_70_qualifies_for_70_categories_but_not_80_categories(self, scanner):
        """Score 70 qualifies in categories with threshold 70, but does NOT qualify in 80 categories."""
        from core.signal_utils import classify_strength
        assert classify_strength(70) == "MODERATE"

        # 70-threshold category: qualifies
        assert 70 >= scanner.get_min_score_for_category("LARGE_CAP_EQUITY")
        assert 70 >= scanner.get_min_score_for_category("MID_SMALL_CAP")
        assert 70 >= scanner.get_min_score_for_category("ETFS_REITS")

        # 80-threshold category: rejected
        assert 70 < scanner.get_min_score_for_category("STOCK_OPTIONS")
        assert 70 < scanner.get_min_score_for_category("INDEX_OPTIONS")
        assert 70 < scanner.get_min_score_for_category("COMMODITIES")
        assert 70 < scanner.get_min_score_for_category("CURRENCIES")
        assert 70 < scanner.get_min_score_for_category("FUTURES")

    def test_score_79_qualifies_for_70_categories_but_not_80_categories(self, scanner):
        """Score 79 qualifies in categories with threshold 70, but does NOT qualify in 80 categories."""
        from core.signal_utils import classify_strength
        assert classify_strength(79) == "MODERATE"

        # 70-threshold category: qualifies
        assert 79 >= scanner.get_min_score_for_category("LARGE_CAP_EQUITY")
        assert 79 >= scanner.get_min_score_for_category("MID_SMALL_CAP")

        # 80-threshold category: rejected
        assert 79 < scanner.get_min_score_for_category("STOCK_OPTIONS")
        assert 79 < scanner.get_min_score_for_category("INDEX_OPTIONS")
        assert 79 < scanner.get_min_score_for_category("COMMODITIES")

    def test_score_80_qualifies_in_all_categories(self, scanner):
        """Score 80 is STRONG and can qualify across all categories subject to remaining gates."""
        from core.signal_utils import classify_strength
        assert classify_strength(80) == "STRONG"

        for cat in [
            "LARGE_CAP_EQUITY",
            "MID_SMALL_CAP",
            "ETFS_REITS",
            "STOCK_OPTIONS",
            "INDEX_OPTIONS",
            "COMMODITIES",
            "CURRENCIES",
            "FUTURES",
        ]:
            min_score = scanner.get_min_score_for_category(cat)
            assert 80 >= min_score, f"Score 80 must satisfy category {cat} threshold {min_score}"

